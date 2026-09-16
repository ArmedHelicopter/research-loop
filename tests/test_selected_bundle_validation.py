"""Synthetic held-out inputs and model, real custody, native modules and Docker."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular.primary_validation_custody import PrimaryValidationCustodian, PrimaryValidationResult, primary_validation_design_digest
from evaluation.modular.train_io import prepare_primary_public_task
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.full_loo_composition import _arm, MODULES, SCHEMA
from research_loop.modular.full_loo_modules import slots, MEASUREMENT
from research_loop.modular.joint_deployment import JointComponentVersion, JointDeploymentBundle
from research_loop.modular.joint_train_runtime import CONSUMERS, ROOT, runtime_sources
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell, SignedAuthority
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.selected_bundle_validation import (
    SelectedBundleValidationPanel, serialize_selected_panel, parse_selected_panel)
from research_loop.modular.selected_bundle_validation_executor import (
    run_validation_target, verify_validation_target, derive_validation_score_input,
    validation_score_request, replay_validation_score_request, load_validation_target, evaluate_selected_primary_bundles)
from research_loop.ontology import ContractError, digest
from test_primary_validation_custody import fixture as primary_fixture, verifier as panel_verifier
from test_modular_custody_panel import DIGEST, calibration, obligations, acceptance
from test_validation_bundle_material import materials, IMAGE
from test_modular_combination_benchmark_driver import _plan
from test_state_retrieval_combination_driver import Provider

R = FrozenRecord.from_dict
FREEZE_KEYS = {'train': b'f'*32}
CUSTODY_KEYS = {'custody': b's'*32}
SOURCE_KEYS = {'val-csv-a': b'a'*32, 'val-csv-b': b'b'*32}


def bundle(role):
    manifest = TrainingManifest.freeze([DataIdentity('blade', 'synthetic-train', 'train-family', 'fixture', 'a'*64, 'train')])
    package = CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={'prompt': {'instructions': 'offset='+str(int(role == 'candidate'))}}, search_cost=1)
    recipe = _arm(arm_id='B0' if role == 'baseline' else 'full',
        procedure='baseline_b0' if role == 'baseline' else 'full_bundle',
        enabled=() if role == 'baseline' else MODULES, comparison='fixed synthetic TRAIN choice',
        history_binding_digest='b'*64, builder_digest='c'*64, history_input_budget=16000, schema=SCHEMA)
    components = {}
    for name, consumer in CONSUMERS.items():
        config = {'schema': 'c5-fixed-stage-consumer-v1', 'module_id': name, 'consumer': consumer, 'pipeline': 'full_loo_modules-v1'}
        template = JointComponentVersion.capture(name, source_root=ROOT,
            source_files=[consumer, 'research_loop/modular/full_loo_modules.py', 'research_loop/modular/full_loo_driver.py'],
            config=R(config), state=R({'synthetic_template': True}), training_manifest=manifest)
        components[name] = JointComponentVersion(R({**template.record.data(),
            'config': {'schema': 'c5-selected-component-consumer-v1', 'module_id': name, 'template_digest': template.digest,
                'consumer_config': config, 'history_build_level': recipe['history_build_levels'][name],
                'target_level': recipe['target_levels'][name]},
            'state': {'schema': 'c5-selected-component-state-v1', 'template_state': template.record.data()['state'],
                'selected_package': package.record.data(), 'selection_digest': digest('synthetic train choice'),
                'history_receipt_digest': digest('synthetic complete TRAIN original')}}))
    return JointDeploymentBundle.create(parent_digest=None, baseline_digest='a'*64, p0_digest='d'*64,
        resource_schedule=R({'schema': 'c5-selected-target-schedule-v1', 'recipe': recipe,
            'slots': list(slots(recipe, 'target')), 'context_budget_bytes': 16000, 'timeout_seconds': 20}), components=components)


def prepare_fixture(root, scope='C5'):
    old, _, args, buffers, qualified, freeze = primary_fixture(root/'source-fixture')
    tasks = {}; material_by_task = {}; sources = {}; csvs = {}
    pins = {row['token']: row for row in qualified['sources']}
    for identity in old.identities():
        metadata, csv = buffers[identity.task_id]
        task = prepare_primary_public_task(identity, pins[identity.task_id], json.loads(metadata), csv)
        _, path, material, source = materials(root/'materials'/identity.task_id, task, csv)
        tasks[task.content_hash] = task; material_by_task[task.content_hash] = material
        sources[task.content_hash] = source; csvs[task.content_hash] = path
    bundles = {role: bundle(role) for role in ('baseline', 'candidate')}
    binding = next(iter(sources.values())).binding().data()
    execution = {'objective': {'question': 'Report the public mean with frozen procedure outputs.'}, 'image': IMAGE,
        'model_config': {'schema': 'synthetic-fixed-model-v1'}, 'runtime_sources': runtime_sources(),
        'source_authorities': {k: v for k, v in binding.items() if k != 'csv_measurement'}}
    selected = SignedAuthority('train', FREEZE_KEYS['train']).issue({'schema': 'selected-bundle-train-freeze-v1',
        'scope': scope, 'domain': 'train', 'status': 'frozen', 'bundle_digests': {k: v.digest for k, v in bundles.items()},
        'selection_digest': digest('synthetic train choice'), 'training_receipts_digest': digest('synthetic originals'),
        'selection_rule_digest': digest('synthetic rule'), 'protocol_digest': freeze['protocol_digest'],
        'selected_snapshot_digest': digest('synthetic snapshot'), 'execution_digest': R(execution).content_hash})
    design = R({'schema': 'selected-bundle-validation-design-v1', 'scope': scope,
        'bundles': {k: v.record.data() for k, v in bundles.items()}, 'train_freeze': selected.data(), 'execution': execution})
    criteria = R({'schema': 'selected-bundle-validation-criteria-v1', 'per_benchmark': {name:
        {'minimum_paired_targets': 1, 'minimum_mean_candidate': 0.5, 'minimum_mean_delta': 0.0,
         'maximum_regressed_pairs': 0} for name in ('discoverybench', 'blade')}})
    panel_shell = SimpleNamespace(stage='V_final', scope_ids=(scope+'-final-bundle',),
        legal_arm_grids={scope+'-final-bundle': design}, combinations=obligations(), required_benchmarks=('discoverybench', 'blade'))
    args.update(private_root=root/'private', candidate=bundles['candidate'].record, config=R(execution))
    freeze.update(candidate_digest=args['candidate'].content_hash, config_digest=args['config'].content_hash,
        acceptance_criteria_digest=criteria.content_hash, panel_design_digest=primary_validation_design_digest(panel_shell),
        package_digests=sorted(v.digest for v in bundles.values()))
    args['freeze'] = SignedAuthority('train', FREEZE_KEYS['train']).issue(freeze)
    custodian = PrimaryValidationCustodian(**args)
    cells = []
    for task in tasks.values():
        for role, subject in bundles.items():
            recipe = subject.record.data()['resource_schedule']['recipe']
            arm = default_compatibility('a'*64).arm([m for m, v in recipe['target_levels'].items() if v])
            cells.append(PanelCell(scope+'-final-bundle', task.identity, 'r1', 'fixed_acceptance', role, arm,
                task.content_hash, material_by_task[task.content_hash].record.content_hash, subject.digest, DIGEST))
    panel = SelectedBundleValidationPanel('V_final', 'validation', custodian._allocation['digest'], bundles['candidate'].digest,
        panel_shell.scope_ids, panel_shell.legal_arm_grids, criteria, tuple(cells), obligations(), ('discoverybench', 'blade'))
    return dict(root=root, custodian=custodian, panel=panel, buffers=buffers, tasks=tasks, materials=material_by_task,
                sources=sources, csvs=csvs, execution=execution, args=args)


def synthetic_model(seen, *, fail=False):
    def respond(request):
        body = request.data(); seen.append(body); slot = body['slot']; context = body['module_context']
        assert all(v not in request.encoded for v in ('"arm_id"', '"enabled"', 'PRIVATE_TASK_ANSWER'))
        if fail: raise RuntimeError('synthetic isolated model outage')
        if slot == 'm4_plan':
            proposal = _plan()
            for branch in proposal['branches']:
                for p in branch['predictions']: p.update(observable=MEASUREMENT['observable'], discriminator_id=MEASUREMENT['discriminator_id'])
            return R(proposal)
        if slot.startswith('review_'):
            assert context['prior_responses'] == []
            return R({'assessment': 'concern', 'evidence_refs': [], 'counterexamples': ['Check outliers.'], 'uncertainty': 'Use a probe.'})
        if slot == 'bounded_choice':
            return R({'job_id': context['alternative_checks'][1]['id'], 'rationale': 'Probe after both independent critiques and counter-source.'})
        if slot == 'analysis_program':
            joined = context['joint_mechanism']; offset = int(joined['candidate_context']['instructions'].split('=')[1])
            actual = {'offset': offset, 'aux_count': len(joined.get('execution_observations', [])),
                'roots': len(joined.get('state_projection', {}).get('observations', [])),
                'predictions': len(joined.get('prediction_proposal', {}).get('branches', [])),
                'reviews': len(joined.get('reviews', [])), 'counter': len(joined.get('retrieval', {}).get('by_lane', {}).get('counter', []))}
            return R({'analysis': 'Consume the learned state and each native diagnostic output.',
                'program': "import csv,json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nresult="+repr(actual)+"\nresult['mean']=sum(xs)/len(xs)\nprint(json.dumps(result))"})
        return R({'objective_digest': context['required_objective_digest'], 'outcome': 'unknown', 'evidence_ids': [],
            'conclusion': body['execution_feedback'][0]['stdout'].strip(), 'programme_complete': False})
    return respond


def verification(setup, cell, lease):
    return dict(panel=setup['panel'], task=setup['tasks'][cell.task_digest], material=setup['materials'][cell.task_digest],
        source_verifier=setup['sources'][cell.task_digest], broker=DockerExecutionBroker([setup['root']]),
        inputs={'public_csv': setup['csvs'][cell.task_digest]}, freeze_keys=FREEZE_KEYS, lease=lease, custody_keys=CUSTODY_KEYS)


def execute_fixture(setup, *, fail=False):
    panel = setup['panel']; custodian = setup['custodian']; results = []; requests = []; seen = []
    calibrated = calibration(panel.digest, panel.required_benchmarks); lease_id = custodian.lease(panel, calibrated)
    def score_and_accept(frozen, manifests, rows, lease):
        requests.extend(manifests)
        results.extend(load_validation_target(Path(r.data()['result_root'])) for r in manifests)
        # The separate scorer test owner supplies the real worker; this tiny
        # synthetic child is limited to proving this custody/executor seam.
        import subprocess, sys
        helper = Path(__file__).parent/'helpers/selected_validation_scorer_fixture.py'
        request_path = setup['root']/'synthetic-scorer-request.json'
        request_path.write_text(R({'requests': [r.data() for r in requests],
            'keys': {'freeze': {k: v.hex() for k, v in FREEZE_KEYS.items()}, 'custody': {k: v.hex() for k, v in CUSTODY_KEYS.items()},
                     'source': {k: v.hex() for k, v in SOURCE_KEYS.items()}}}).encoded, encoding='utf-8')
        worker = subprocess.run([sys.executable, '-B', str(helper), str(request_path)], capture_output=True, timeout=180)
        (setup['root']/'synthetic-scorer.stdout').write_bytes(worker.stdout)
        (setup['root']/'synthetic-scorer.stderr').write_bytes(worker.stderr)
        assert worker.returncode == 0, worker.stderr.decode(errors='replace')
        output = json.loads(worker.stdout); assert output['pid'] != __import__('os').getpid()
        from research_loop.modular.panel_receipts import ScientificScorerReceipt
        scores = tuple(ScientificScorerReceipt(tuple(v['cell_key']), R(v['receipt'])) for v in output['scores'])
        return PrimaryValidationResult(rows, scores, acceptance(frozen, rows, scores, lease))
    def evaluate(frozen, materials_from_custody, lease):
        assert {v.task for v in materials_from_custody} == set(setup['tasks'].values())
        setup['leased_materials'] = materials_from_custody
        return evaluate_selected_primary_bundles(frozen, materials_from_custody, lease,
            root=setup['root']/'fixed-pair', materials_by_task=setup['materials'], source_verifiers=setup['sources'],
            inputs_by_task={k: {'public_csv': v} for k, v in setup['csvs'].items()},
            broker=DockerExecutionBroker([setup['root']]), model=synthetic_model(seen, fail=fail),
            model_config=R(setup['execution']['model_config']), retrieval_provider=Provider([]),
            audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}), freeze_keys=FREEZE_KEYS, custody_keys=CUSTODY_KEYS,
            score_and_accept=score_and_accept)
    aggregate = custodian.run(panel=panel, lease_id=lease_id, calibration=calibrated,
        source_provider=lambda token: setup['buffers'][token], evaluate=evaluate, verifier=panel_verifier())
    setup.update(results=results, score_requests=requests, aggregate=aggregate, lease_id=lease_id, seen=seen, evaluator=evaluate)
    return setup


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    return execute_fixture(prepare_fixture(tmp_path_factory.mktemp('selected-val')))


def test_fixed_bundles_reach_primary_custody_real_operations_and_independent_child(completed):
    setup = completed
    assert len(setup['results']) == 4 and setup['aggregate'].data()['decision'] == 'inconclusive'
    for result in setup['results']:
        score = replay_validation_score_request(setup['score_requests'][setup['results'].index(result)],
            freeze_keys=FREEZE_KEYS, custody_keys=CUSTODY_KEYS, source_keys=SOURCE_KEYS)
        observed = json.loads(score.data()['submission']['execution_feedback']['stdout'])
        if result.cell.arm_id == 'candidate':
            assert observed | {'mean': 0} == {'mean': 0, 'offset': 1, 'aux_count': 2, 'roots': 1, 'predictions': 3, 'reviews': 2, 'counter': 1}
            assert (result.root/'phase/queue.sqlite').is_file()
        else: assert observed['offset'] == observed['aux_count'] == observed['reviews'] == 0
    assert setup['custodian'].replay(panel=setup['panel'], lease_id=setup['lease_id'], verifier=panel_verifier()) == setup['aggregate']
    assert all(token not in setup['aggregate'].encoded for token in setup['buffers'])
    assert parse_selected_panel(serialize_selected_panel(setup['panel'])).digest == setup['panel'].digest
    assert setup['aggregate'].data()['source_denominator']['benchmarks'] == {
        name: {'original_heldout': 1, 'qualified_heldout': 1, 'unqualified_heldout': 0} for name in ('blade', 'discoverybench')}


def test_fixed_panel_refuses_scope_domain_bundle_and_recipe_changes(completed):
    panel = completed['panel']
    for change in ({'stage': 'TRAIN'}, {'domain': 'train'}, {'scope_ids': ('Q6.3',)}, {'candidate_digest': 'a'*64},
                   {'cells': panel.cells[:-1]}, {'cells': (replace(panel.cells[0], variant='optimize'), *panel.cells[1:])}):
        with pytest.raises(ContractError): replace(panel, **change)
    value = serialize_selected_panel(panel); value['panel']['cells'][0]['identity']['domain'] = 'train'
    with pytest.raises(ContractError): parse_selected_panel(value)


def test_independent_replay_rejects_changed_original_and_reused_primary_lease(completed):
    request = completed['score_requests'][0]; result = completed['results'][0]
    program = result.root/'runtime/analysis-1.py'; original = program.read_bytes()
    try:
        program.write_bytes(original+b'\n# tamper\n')
        with pytest.raises(ContractError):
            replay_validation_score_request(request, freeze_keys=FREEZE_KEYS, custody_keys=CUSTODY_KEYS, source_keys=SOURCE_KEYS)
    finally: program.write_bytes(original)
    with pytest.raises(ContractError):
        completed['custodian'].lease(completed['panel'], calibration(completed['panel'].digest, completed['panel'].required_benchmarks))
    with pytest.raises(FileExistsError):
        completed['evaluator'](completed['panel'], completed['leased_materials'],
            completed['custodian'].store.issued_validation_receipt(completed['lease_id']))


def test_fixed_target_failure_is_replayed_without_score_or_retry(tmp_path):
    setup = prepare_fixture(tmp_path, scope='C4'); panel = setup['panel']; custodian = setup['custodian']
    lease_id = custodian.lease(panel, calibration(panel.digest, panel.required_benchmarks))
    custodian.store.consume_validation(lease_id, panel_digest=panel.digest, arm_schedule=list(panel.arm_schedule))
    lease = custodian.store.issued_validation_receipt(lease_id); cell = panel.cells[0]; args = verification(setup, cell, lease)
    result = run_validation_target(cell=cell, **args, retrieval_provider=Provider([]), model=synthetic_model([], fail=True),
        model_config=R(setup['execution']['model_config']), audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}), root=tmp_path/'failed')
    request = validation_score_request(result, **{k: args[k] for k in ('panel', 'task', 'material', 'source_verifier', 'inputs', 'lease')})
    value = replay_validation_score_request(request, freeze_keys=FREEZE_KEYS, custody_keys=CUSTODY_KEYS, source_keys=SOURCE_KEYS).data()
    assert value['runtime_status'] == 'failed' and value['submission'] is None and value['submission_digest'] is None
