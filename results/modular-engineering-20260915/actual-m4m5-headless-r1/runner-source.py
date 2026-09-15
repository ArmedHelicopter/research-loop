"""Freeze and execute one actual TRAIN factorial with protected native scoring.

This operator helper never reads reference payloads.  A separate scorer worker
owns reference resolution; the solver receives only exported TRAIN material.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

WORK = Path(__file__).parent
BASE = WORK.parent
TREE = BASE / 'actual-m4m5-headless-runtime-r1'
PREP = WORK / 'actual-m4m5-headless-preparation-r1'
RUN = WORK / 'actual-m4m5-headless-run-r1'
PRIVATE = BASE / 'custody-private/actual-m4m5-headless-r1'
MAP = WORK / 'actual-m4m5-train-material-map-r1.json'
OLD_SCHEMAS = WORK / 'm4m5-train-process-20260913-01/controller.json'
OLD_EXPORT = WORK / 'primary-prospective-export-live-r1'
OLD_REQUEST = OLD_EXPORT / 'frozen-request-r1.json'
PUBLICATION = WORK / 'primary-prospective-reference-live-r1/reference-publication-r1.json'
STORE = BASE / 'custody-private/primary-prospective-train-reference-20260913-r1'
SEALED = BASE / 'custody-private/primary-process-split-20260913-r2'
EXECUTABLE = Path('C:/Users/Administrator/.grok/bin/grok.exe')
AUTH = Path('C:/Users/Administrator/.grok/auth.json')
ACCOUNT = 'b13ba3f652654cf9907b60161d7cd397e5edd8da74646e642e4105768d511c2e'
IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
EXECUTOR, SCORER = 'actual-m4m5-executor-r1', 'actual-m4m5-scorer-r1'
RECOVERY = {'schema': 'headless-account-read-recovery-v1', 'max_attempts': 2}
sys.path.insert(0, str(TREE))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, body):
    from research_loop.ontology import canonical
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical(body) + '\n')


def desc(path):
    return {'path': str(path), 'sha256': sha(path)}


def account(path):
    rows = [v for v in read(path).values() if type(v) is dict and v.get('auth_mode') == 'oidc'
            and v.get('oidc_issuer') == 'https://auth.x.ai'
            and v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    assert len(rows) == 1 and hashlib.sha256(rows[0]['user_id'].encode()).hexdigest() == ACCOUNT


def source(check):
    gate = read(check)
    prefix = str(check).removesuffix('-closed.json')
    before = read(prefix + '-before.json')
    assert before['pytest_args'] == ['tests/test_headless_evaluator_factory.py',
        'tests/test_headless_evaluator_controller.py::test_full_v6_factorial_closes_private_evaluator_or_retains_failed_history[False]',
        'tests/test_label_isolation.py']
    assert before['commit'] == gate['commit'] and before['source_before'] == gate['source_after']
    assert gate['exit_code'] == 0 and gate['source_unchanged']
    assert gate['junit'] == {'tests':20, 'failures':0, 'errors':0, 'skipped':0}
    report = Path(prefix + '.xml')
    assert sha(report) == gate['report_sha256']
    suites = list(ET.parse(report).getroot().iter('testsuite'))
    assert {k:sum(int(s.get(k,0)) for s in suites) for k in gate['junit']} == gate['junit']
    archive = read(prefix + '-source-members.json')
    assert archive['commit'] == gate['commit'] and sha(prefix + '-sources.zip') == archive['archive_sha256']
    assert {r['path']:r['sha256'] for r in archive['members']} == gate['source_after']
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip()
    assert head == gate['commit']
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=TREE).strip()
    assert not (TREE / 'data').exists()
    assert all(sha(TREE / name) == value for name, value in gate['source_after'].items())
    return gate, {str((TREE / name).resolve()): value for name, value in gate['source_after'].items()}


def exporter(output, audit):
    from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter
    request = read(OLD_REQUEST)
    mapping = read(MAP)['exporter_constructor']
    assert sha(OLD_REQUEST) == '8713df0bccbd7dfd499e4461790bb5c983fe0b89b37d3eac98867df250cb6685'
    assert sha(request['config_path']) == request['config_raw_sha256']
    assert Path(mapping['config_path']).resolve() == Path(request['config_path']).resolve()
    assert mapping['config_sha256'] == request['config_raw_sha256']
    assert Path(mapping['sealed_root']).resolve() == SEALED.resolve()
    assert mapping['expected_split_digest'] == request['split_digest']
    assert mapping['expected_audit_digest'] == request['audit_digest']
    assert mapping['expected_split_sha256'] == request['split_raw_sha256']
    assert mapping['expected_audit_sha256'] == request['audit_raw_sha256']
    assert Path(mapping['eligibility_path']).resolve() == (OLD_EXPORT / 'primary-eligibility-r1.json').resolve()
    assert mapping['eligibility_sha256'] == sha(mapping['eligibility_path'])
    return PrimaryProspectiveTrainExporter(read(request['config_path']), SEALED,
        expected_split_digest=request['split_digest'], expected_audit_digest=request['audit_digest'],
        expected_split_sha256=request['split_raw_sha256'], expected_audit_sha256=request['audit_raw_sha256'],
        eligibility_path=OLD_EXPORT / 'primary-eligibility-r1.json',
        eligibility_sha256='1963e2684ea024af19a798b89cf8d1665f25008cc6fb5200310de41fa0dd3917',
        output_root=output, audit_root=audit)


def selected():
    rows = read(OLD_REQUEST)['items']
    result = [min((r for r in rows if r['source'] == benchmark), key=lambda r: r['token'])
              for benchmark in ('discoverybench', 'blade')]
    mapping = read(MAP)
    assert [r['token'] for r in result] == mapping['selected_token_allowlist']
    assert result == [{k:r[k] for k in ('source','token','group_sha256','input_bindings_digest')}
                      for r in mapping['selected_public_train_items']]
    return result


def packets():
    from evaluation.modular.train_io import PublicTrainPacket
    from research_loop.modular.contracts import PublicTask, DataIdentity, FrozenRecord
    result = []
    for item in selected():
        path = PREP / 'public-for-compile' / item['token'] / 'public.json'
        obj = read(path)
        task = PublicTask(DataIdentity.parse(obj['task']['identity']), FrozenRecord.from_dict(obj['task']['payload']))
        task.identity.require_train()
        result.append(PublicTrainPacket(task, path, path.parent / 'data.csv', FrozenRecord.from_dict(obj['receipt'])))
    return tuple(result)


def environment():
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}}
    env.update(PYTHONPATH=str(TREE), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
               TEMP=str(WORK), TMP=str(WORK))
    return env


def prepare(check):
    from evaluation.modular.scorer_process import headless_evaluator_descriptor, serialize_combination_panel
    from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
    from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel, SLOTS, _ANALYSIS
    from research_loop.modular.combinations import default_compatibility
    from research_loop.modular.contracts import FrozenRecord
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    from research_loop.modular.m4_m5_useful_controls import RECIPE
    from research_loop.modular.grok_acp_transport import EXECUTABLE_SHA256
    from research_loop.ontology import digest

    gate, pins = source(check)
    assert not PREP.exists() and not PRIVATE.exists() and not RUN.exists()
    assert MAP.is_file() and sha(EXECUTABLE) == EXECUTABLE_SHA256
    assert sha(MAP) == '9f039bbc822a578be9d15daf62182dc38dc08b00fc17929cc39cd2a48f02a26f'
    account(AUTH)
    PREP.mkdir(); PRIVATE.mkdir(parents=True)
    tokens = [item['token'] for item in selected()]
    material = exporter(PREP / 'public-for-compile', PREP / 'compile-export-audit').export_controller_packets(tokens)
    assert len(material) == 2 and all(p.task.identity.domain == 'train' for p in material)
    publication = read(PUBLICATION)
    binding = read(MAP)['private_reference_store']
    assert Path(binding['store_root']).resolve() == STORE.resolve()
    assert Path(binding['manifest_path']).resolve() == (STORE / 'manifest.json').resolve()
    assert Path(binding['publication_path']).resolve() == PUBLICATION.resolve()
    assert sha(PUBLICATION) == binding['publication_sha256'] and digest(publication) == binding['publication_canonical_sha256']
    assert publication['manifest_sha256'] == sha(STORE / 'manifest.json') == binding['manifest_sha256']
    assert publication['inventory_digest'] == binding['inventory_digest']
    assert publication['split_digest'] == binding['split_digest']
    handles = {digest(p.task.identity.data()): publication['task_handles'][digest(p.task.identity.data())] for p in material}
    assert handles == binding['selected_task_handles']
    for p, mapped in zip(material, read(MAP)['selected_public_train_items'], strict=True):
        assert p.task.content_hash == mapped['task_sha256']
        assert digest(p.task.identity.data()) == mapped['identity_digest']
        assert sha(p.csv_path) == mapped['csv_sha256'] and p.csv_path.stat().st_size == mapped['csv_byte_count']
        assert p.task.identity.split_id == publication['split_digest']
        assert p.task.identity.dataset_version == publication['inventory_digest']
    for role in ('solver', 'evaluator'):
        home = PRIVATE / (role + '-home'); home.mkdir()
        shutil.copyfile(AUTH, home / 'auth.json'); account(home / 'auth.json')
        (PRIVATE / (role + '-profile')).mkdir(); (PRIVATE / (role + '-cwd')).mkdir()
    for name in (EXECUTOR, SCORER, 'unused-a', 'unused-b'):
        (PRIVATE / (name + '.key')).write_bytes(secrets.token_bytes(32))
    external = [Path(__file__), MAP, OLD_REQUEST, OLD_SCHEMAS, PUBLICATION, Path(check),
                Path(read(OLD_REQUEST)['config_path']), OLD_EXPORT / 'primary-eligibility-r1.json',
                SEALED / 'prospective-split.json', SEALED / 'process-audit.json']
    gate_prefix = str(check).removesuffix('-closed.json')
    external.extend(Path(gate_prefix + suffix) for suffix in
                    ('-before.json','.xml','-source-members.json','-sources.zip'))
    pins.update({str(p.resolve()): sha(p) for p in external})
    pins[str(EXECUTABLE.resolve())] = EXECUTABLE_SHA256
    rubric = ScorerConfig.create(benchmark='core_pair', evaluator_id='frozen-rubric-grok-headless-train-r1',
                                rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version='1')
    spec = {'provider_kind': 'grok-headless-frozen-evaluator-v1', 'executable': str(EXECUTABLE),
        'work_root': str(PRIVATE / 'evaluator-model'), 'private_home': str(PRIVATE / 'evaluator-home'),
        'private_profile': str(PRIVATE / 'evaluator-profile'), 'public_cwd': str(PRIVATE / 'evaluator-cwd'),
        'frozen_files': pins, 'evaluator_id': rubric.record.data()['evaluator_id'], 'evaluator_version': '1',
        'model': 'grok-4.6', 'effort': 'low', 'max_calls': 8, 'max_tokens': 8 * 131072,
        'timeout_seconds': 60, 'account_read_recovery': RECOVERY}
    provider = headless_evaluator_descriptor(spec)
    assert not (PRIVATE / 'evaluator-model').exists()
    baseline = digest({'stage': 'actual-m4m5-headless-r1', 'source_commit': gate['commit'], 'items': tokens})
    design = default_compatibility(baseline).conditional_factorial(('M4', 'M5'))
    package = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze([p.task.identity for p in material]), search_cost=0,
        changes={'prompt': {'instructions': 'Use only the supplied public TRAIN question and observations. '
            'Retain uncertainty, unavailable information, and computation failures. '
            'Use the actual printed analysis output when forming the conclusion.'}})
    declaration = {'kind': 'grok-headless-public-train-v1', 'model': 'grok-4.6',
        'opportunity_contract': 'public-train-main-and-initial-title-v1', 'included_only': True,
        'api_key_route_permitted': False, 'main_calls': 40, 'possible_initial_title_calls': 40,
        'main_output_caps': {'m4_plan': 2048, 'm5_mechanism': 2048, 'm5_measurement': 2048,
                             'analysis_program': 8192, 'final_answer': 2048},
        'input_byte_cap_per_request': 262144, 'observed_main_token_cap': 131072,
        'title_requested_output_cap': 100, 'wall_timeout_seconds': 60, 'max_retries': 0,
        'title_usage_and_all_call_totals': 'unknown', 'account_read_recovery': RECOVERY}
    body = {'schema': 'm4-m5-train-controller-config-v6', 'export_mode': 'primary_prospective',
        'execution_recipe': RECIPE.data(), 'provider': declaration, 'evaluator_provider': provider,
        'domain': 'train', 'stage': 'actual-m4m5-headless-r1', 'item_ids': tokens,
        'task_bindings': {token: {'identity': p.task.identity.data(), 'task_digest': p.task.content_hash,
                                'csv_sha256': sha(p.csv_path)} for token, p in zip(tokens, material, strict=True)},
        'baseline_digest': baseline, 'packages_by_arm': {row['arm_digest']: package.record.data() for row in design.data()['cells']},
        'scorer': rubric.record.data(), 'scorer_handle_bindings': {k: hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria': {'scope': 'train_adapted_only', 'contrast_analysis': _ANALYSIS, 'allowed_failures': 0,
            'scientific_promotion': False, 'matched_tokens': 'not_claimed'}, 'replicates': ['r1'],
        'model': 'grok-4.6', 'effort': 'low', 'max_calls': 40, 'max_tokens': 40 * 131072,
        'schemas': read(OLD_SCHEMAS)['schemas'], 'allocation': {'model_slots_per_cell': list(SLOTS),
            'docker_attempts_per_cell': 1, 'scorer_calls_per_cell': 1, 'scorer_call_limit': 8,
            'scorer_token_accounting': 'signed_headless_main_unknown_title'}, 'image': IMAGE, 'timeout_seconds': 60}
    config = FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    compiled = compile_m4_m5_train_panel(config, material)
    assert len(compiled.panel.cells) == 8
    server = {'schema': 'combination-scorer-process-config-v1', 'panel': serialize_combination_panel(compiled.panel),
        'scorer_config': rubric.record.data(), 'scorer_config_digest': rubric.digest,
        'train_reference_store': {'root': str(STORE), **{k: publication[k] for k in ('manifest_sha256', 'inventory_digest', 'split_digest')}},
        'task_handles': handles, 'execution_authority_key_files': {EXECUTOR: str(PRIVATE / (EXECUTOR + '.key'))},
        'scorer_authority': {'id': SCORER, 'key_file': str(PRIVATE / (SCORER + '.key'))}, 'evaluator': spec}
    write(PREP / 'controller.json', body); write(PRIVATE / 'server-config.json', server)
    write(PREP / 'solver-spec.json', {'frozen_files': pins, 'private_home': str(PRIVATE / 'solver-home'),
        'private_profile': str(PRIVATE / 'solver-profile'), 'public_cwd': str(PRIVATE / 'solver-cwd')})
    inputs = {str(p): sha(p) for p in [PREP / 'controller.json', PRIVATE / 'server-config.json', PREP / 'solver-spec.json']}
    inputs.update({str(p): sha(p) for p in (PREP / 'public-for-compile').rglob('*') if p.is_file()})
    write(PREP / 'preparation.json', {'schema': 'actual-m4m5-headless-preparation-v1',
        'source_commit': gate['commit'], 'engineering_gate': desc(check), 'runner': desc(Path(__file__)),
        'material_map': desc(MAP), 'input_pins': inputs, 'source_pins': pins, 'panel_digest': compiled.panel.digest,
        'task_selection': 'first_token_per_benchmark_from_existing_frozen_TRAIN_roster',
        'cells': 8, 'solver_main_limit': 40, 'evaluator_main_limit': 8, 'docker_limit': 8,
        'parent_timeout_seconds': 5400, 'additional_paid_api_budget': 0, 'settled_additional_charge_usd': None,
        'title_and_all_opportunity_settlement': 'unknown', 'validation_opened': False,
        'scientific_effectiveness_proven': False, 'official_or_calibrated_scoring': False,
        'allocation_scope': 'M4/M5 factorial, distinct from closed 180-opportunity diagnostic review allocation',
        'authorized_account_binding': ACCOUNT, 'prepared_at': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'stage': 'prepared', 'cells': 8, 'solver_main_limit': 40, 'evaluator_main_limit': 8,
                      'actual_model_calls': 0, 'validation_opened': False}), flush=True)


def checked():
    p = read(PREP / 'preparation.json')
    assert sha(p['engineering_gate']['path']) == p['engineering_gate']['sha256']
    source(p['engineering_gate']['path'])
    assert sha(__file__) == p['runner']['sha256']
    assert all(sha(path) == value for path, value in {**p['source_pins'], **p['input_pins']}.items())
    for role in ('solver', 'evaluator'): account(PRIVATE / (role + '-home') / 'auth.json')
    return p


def worker():
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority
    from evaluation.modular.scorer_process import CombinationScorerProcessClient
    from evaluation.modular.scoring_service import ScorerConfig
    from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel, run_m4_m5_train_panel
    from research_loop.modular.contracts import FrozenRecord
    from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort
    from research_loop.modular.runtime import AuditVerifier
    p = checked(); body = read(PREP / 'controller.json')
    config = FrozenM4M5TrainConfig(FrozenRecord.from_dict(body)); compiled = compile_m4_m5_train_panel(config, packets())
    assert compiled.panel.digest == p['panel_digest']
    spec = read(PREP / 'solver-spec.json'); provider = body['provider']
    port = GrokHeadlessTrainModelPort(executable=EXECUTABLE, work_root=RUN / 'solver-model',
        private_home=Path(spec['private_home']), private_profile=Path(spec['private_profile']),
        public_cwd=Path(spec['public_cwd']), frozen_files=spec['frozen_files'], max_calls=40, schemas=body['schemas'],
        slot_output_caps=provider['main_output_caps'], slot_input_byte_caps={s:262144 for s in body['schemas']},
        observed_main_token_cap=131072, account_read_recovery=RECOVERY)
    server_path = PRIVATE / 'server-config.json'
    service = CombinationScorerProcessClient(panel=compiled.panel, config=ScorerConfig(FrozenRecord.from_dict(body['scorer'])),
        command=[sys.executable, '-m', 'evaluation.modular.scorer_process', '--config', str(server_path),
                 '--config-sha256', sha(server_path), '--journal', str(PRIVATE / 'scorer-worker.jsonl')],
        journal_path=RUN / 'scorer-client.jsonl', environment=environment(), response_timeout_seconds=360,
        task_handle_bindings=body['scorer_handle_bindings'], evaluator_provider=body['evaluator_provider'],
        execution_authority_keys={EXECUTOR: (PRIVATE / (EXECUTOR + '.key')).read_bytes()},
        scorer_authority_keys={SCORER: (PRIVATE / (SCORER + '.key')).read_bytes()})
    try:
        exp = exporter(RUN / 'public-export', RUN / 'export-audit')
        result = run_m4_m5_train_panel(config, custody=None, prospective_exporter=exp,
            snapshot_root=Path(exp.config['snapshot_root']), export_root=exp.output_root, run_root=RUN / 'controller',
            model=port, audit_verifier=AuditVerifier({n:(PRIVATE/(n+'.key')).read_bytes() for n in ('unused-a','unused-b')}),
            execution_authority=LinkedExecutionAuthority(EXECUTOR, (PRIVATE / (EXECUTOR + '.key')).read_bytes()),
            scoring_service=service, scorer_authority_keys={SCORER:(PRIVATE / (SCORER + '.key')).read_bytes()})
    finally:
        service.close()
    r = result.receipt.data(); evaluator = read(PRIVATE / 'evaluator-model/ledger.json')
    write(RUN / 'summary.json', {'schema':'actual-m4m5-headless-summary-v1', 'source_commit':p['source_commit'],
        'controller_receipt':desc(RUN/'controller/controller-receipt.json'), 'status':r['status'],
        'cells':8, 'scored_cells':r['scored_cells'], 'eligible_scored_cells':r['eligible_scored_cells'],
        'solver_reservations':len(port.ledger['calls']), 'known_solver_main_tokens':port.ledger['known_main_tokens'],
        'evaluator_reservations':len(evaluator['calls']), 'known_evaluator_main_tokens':evaluator['known_main_tokens'],
        'solver_usage_incomplete':port.ledger['usage_incomplete'], 'evaluator_usage_incomplete':evaluator['usage_incomplete'],
        'title_and_all_opportunity_settlement':'unknown', 'settled_additional_charge_usd':None,
        'validation_opened':False, 'pruned_combinations':[], 'scientific_effectiveness_proven':False})
    print(json.dumps(read(RUN / 'summary.json')), flush=True)


def run():
    from research_loop.modular.grok_headless_transport import _child
    p = checked(); assert not RUN.exists(); RUN.mkdir()
    command = [sys.executable, str(Path(__file__)), 'worker']
    reservation = {'schema':'actual-m4m5-headless-parent-v1', 'preparation':desc(PREP/'preparation.json'),
        'source_commit':p['source_commit'], 'command':command, 'timeout_seconds':p['parent_timeout_seconds'],
        'solver_main_limit':40, 'evaluator_main_limit':8, 'docker_limit':8, 'additional_paid_api_budget':0,
        'validation_opened':False, 'main_retry':False, 'created_at':datetime.now(timezone.utc).isoformat()}
    write(RUN / 'parent-reservation.json', reservation)
    _, process = _child(command, {'cwd':str(TREE)}, environment(), RUN/'parent-process', p['parent_timeout_seconds'])
    unchanged = all(sha(path) == value for path, value in {**p['source_pins'], **p['input_pins']}.items())
    write(RUN/'parent-closure.json', {'schema':'actual-m4m5-headless-parent-closure-v1', 'process':process,
        'preparation':desc(PREP/'preparation.json'), 'source_and_inputs_unchanged':unchanged,
        'summary':desc(RUN/'summary.json') if (RUN/'summary.json').exists() else None, 'validation_opened':False})
    print(json.dumps({'stage':'closed','exit_code':process['process_exit_code'], 'timed_out':process['timed_out'],
        'source_and_inputs_unchanged':unchanged, 'summary_present':(RUN/'summary.json').exists()}), flush=True)
    raise SystemExit(int(not unchanged or process['process_exit_code'] != 0 or process['timed_out']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare','run','worker'])
    parser.add_argument('--engineering-check')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            assert args.engineering_check
            prepare(Path(args.engineering_check))
        elif args.action == 'run': run()
        else: worker()
    except Exception as exc:
        root = RUN if RUN.exists() else PREP if PREP.exists() else WORK
        failure = root / ('actual-m4m5-' + args.action + '-failure.json')
        if not failure.exists(): write(failure, {'action':args.action,'error_type':type(exc).__name__,
            'message':str(exc)[:180], 'validation_opened':False, 'status':'inconclusive'})
        print(json.dumps({'stage':'failed','action':args.action,'error_type':type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
