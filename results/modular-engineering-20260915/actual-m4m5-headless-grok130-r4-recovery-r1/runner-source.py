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
import zipfile

WORK = Path(__file__).parent
BASE = WORK.parent
TREE = BASE / 'headless-train-timeout-r1'
PREP = WORK / 'actual-m4m5-headless-grok130-preparation-r4'
RUN = WORK / 'actual-m4m5-headless-grok130-run-r4'
PRIVATE = BASE / 'custody-private/actual-m4m5-headless-grok130-r4'
MAP = WORK / 'actual-m4m5-train-material-map-r1.json'
OLD_SCHEMAS = WORK / 'm4m5-train-process-20260913-01/controller.json'
OLD_EXPORT = WORK / 'primary-prospective-export-live-r1'
OLD_REQUEST = OLD_EXPORT / 'frozen-request-r1.json'
PUBLICATION = WORK / 'primary-prospective-reference-live-r1/reference-publication-r1.json'
STORE = BASE / 'custody-private/primary-prospective-train-reference-20260913-r1'
SEALED = BASE / 'custody-private/primary-process-split-20260913-r2'
EXECUTABLE = WORK / 'grok-cli-1.0.30/grok.exe'
AUTH = Path('C:/Users/Administrator/.grok/auth.json')
ACCOUNT = 'b13ba3f652654cf9907b60161d7cd397e5edd8da74646e642e4105768d511c2e'
IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
EXECUTOR, SCORER = 'actual-m4m5-grok130-executor-r4', 'actual-m4m5-grok130-scorer-r4'
RECOVERY = {'schema': 'headless-account-read-recovery-v1', 'max_attempts': 2}
# This is the reviewed candidate at authoring time.  prepare requires an
# explicit commit so a later reviewed repair can be selected honestly.
RUNTIME_COMMIT = 'd672c274ccb4da45605e2013ec5fcd4b3fcfa9c9'
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


def _closed_prefix(check):
    check = Path(check)
    if not check.name.endswith('-closed.json'):
        raise AssertionError('engineering check must name its immutable -closed.json receipt')
    return Path(str(check).removesuffix('-closed.json'))


def _junit_cases(report):
    return list(ET.parse(report).getroot().iter('testcase'))


def _require_selector_coverage(before, cases, selectors):
    args = before.get('pytest_args')
    assert isinstance(args, list)
    for selector in selectors:
        assert selector in args
        module, *selected_cases = selector.split('::')
        stem = Path(module).stem
        matched = [case for case in cases if stem == str(case.get('classname', '')).split('.')[-1]]
        assert matched
        if selected_cases:
            assert any(case.get('name', '').split('[')[0] == selected_cases[-1] for case in matched)


def _expected_engineering_selectors(check):
    name = Path(check).name
    if 'headless-capture-timeout-frozen-r1' in name:
        return {'tests/test_grok_headless_transport.py', 'tests/test_grok_headless_train_solver.py',
                'tests/test_headless_evaluator_model_port.py', 'tests/test_headless_train_timeout.py'}
    if 'scheduler-headless-seam-frozen-r1' in name:
        return {'tests/test_headless_scheduler_evaluator_stdio.py'}
    if 'headless-capture-scheduler-root-r2' in name:
        return {'tests/test_headless_train_timeout.py',
                'tests/test_grok_headless_transport.py::test_process_tree_keeps_acp_default_stdout_pipe'}
    if 'scheduler-headless-stdio-root-r2' in name:
        return {'tests/test_headless_scheduler_evaluator_stdio.py::test_native_scheduler_closes_eight_evaluator_receipts'}
    raise AssertionError('unrecognized explicit engineering check prefix')


def verify_frozen_check(check, expected_commit, selectors):
    """Require the original before/closed/start/join/JUnit/ZIP evidence set."""
    check = Path(check); prefix = _closed_prefix(check)
    gate, before = read(check), read(str(prefix) + '-before.json')
    start = read(str(prefix) + '-native-start.json')
    join = read(str(prefix) + '-native-join.json')
    members = read(str(prefix) + '-source-members.json')
    report, archive = Path(str(prefix) + '.xml'), Path(str(prefix) + '-sources.zip')
    assert gate['commit'] == before['commit'] == join['source_commit'] == members['commit'] == expected_commit
    assert gate['source_unchanged'] is True and before['source_before'] == gate['source_after']
    assert gate['exit_code'] == join['result']['exit_code'] == 0
    assert gate['junit']['tests'] > 0 and all(gate['junit'][key] == 0 for key in ('failures', 'errors', 'skipped'))
    assert start['session_id'] == join['native_session_id']
    assert sha(report) == gate['report_sha256'] and sha(archive) == members['archive_sha256']
    cases = _junit_cases(report)
    observed = {key: sum(int(row.get(key, 0)) for row in ET.parse(report).getroot().iter('testsuite')) for key in gate['junit']}
    assert observed == gate['junit'] and len(cases) == gate['junit']['tests']
    _require_selector_coverage(before, cases, selectors)
    expected_members = {row['path']: row['sha256'] for row in members['members']}
    assert expected_members == gate['source_after']
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.namelist() == [row['path'] for row in members['members']]
        for row in members['members']:
            raw = zipped.read(row['path'])
            assert hashlib.sha256(raw).hexdigest() == row['sha256'] and len(raw) == row['bytes']
    return gate


_LABEL_CASES = {
    'test_every_task_has_a_label', 'test_prompts_do_not_contain_label_payloads',
    'test_error_catching_every_task_has_a_label', 'test_error_catching_prompts_do_not_contain_label_payloads',
    'test_iteration_every_task_has_a_label', 'test_iteration_prompts_do_not_contain_label_payloads',
    'test_audit_contrast_every_task_has_a_label', 'test_audit_contrast_prompts_do_not_contain_label_payloads',
    'test_true_lock_every_task_has_a_label', 'test_true_lock_prompts_omit_gold_rule'}


def verify_root_label_parity(check, root_source):
    """Require all ten label tests and retain exact archive bytes before parity checks."""
    gate = verify_frozen_check(check, read(check)['commit'], {'tests/test_label_isolation.py'})
    prefix = _closed_prefix(check); members = read(str(prefix) + '-source-members.json')
    cases = _junit_cases(Path(str(prefix) + '.xml'))
    label_cases = [case for case in cases
                   if case.get('classname', '').split('.')[-1] == 'test_label_isolation']
    assert len(label_cases) == len(_LABEL_CASES)
    assert {case.get('name') for case in label_cases} == _LABEL_CASES
    root_source = Path(root_source)
    assert (root_source / '.git').exists()
    with zipfile.ZipFile(str(prefix) + '-sources.zip') as zipped:
        for row in members['members']:
            name = row['path']
            if not name.endswith(('.py', '.md')):
                continue
            current = root_source / name
            assert current.is_file()
            archived = zipped.read(name); live = current.read_bytes()
            if name.endswith('.md'):
                assert archived.replace(b'\r\n', b'\n') == live.replace(b'\r\n', b'\n')
            else:
                assert archived == live
    return gate


def _normalized(raw):
    return raw.replace(b'\r\n', b'\n')


def verify_runtime_root_production_parity(runtime_tree, root_source, source_after):
    """Explicit cross-tree source rule: production Python compares CRLF/LF-normalized."""
    runtime_tree, root_source = Path(runtime_tree), Path(root_source)
    runtime_names = {name for name in source_after if name.endswith('.py') and name.startswith(('research_loop/', 'evaluation/'))}
    root_names = {str(path.relative_to(root_source)).replace('\\', '/') for base in ('research_loop', 'evaluation')
                  for path in (root_source / base).rglob('*.py')}
    assert runtime_names == root_names
    for name in runtime_names:
        assert _normalized((runtime_tree / name).read_bytes()) == _normalized((root_source / name).read_bytes())


def source(runtime_tree, runtime_commit, engineering_checks, labels_check, root_source):
    runtime_tree = Path(runtime_tree)
    assert runtime_tree.resolve() == TREE.resolve()
    assert isinstance(runtime_commit, str) and len(runtime_commit) == 40
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=runtime_tree, text=True).strip() == runtime_commit
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=runtime_tree, text=True).strip()
    assert not (runtime_tree / 'data/labels').exists()
    assert len(engineering_checks) == 2
    gates = [verify_frozen_check(path, runtime_commit, _expected_engineering_selectors(path)) for path in engineering_checks]
    assert gates[0]['source_after'] == gates[1]['source_after']
    # The source-frozen checks may run in ROOT so its ten label checks stay out
    # of the actor. Preserve each exact ZIP; admit only explicit CRLF/LF parity
    # of the same commit, then pin the actor's actual bytes for every call.
    actor_names = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=runtime_tree).decode().split('\0'))
    actor_names = {name for name in actor_names if name and not name.startswith('results/') and name.endswith(('.py', '.md'))}
    assert actor_names == set(gates[0]['source_after'])
    for check in engineering_checks:
        with zipfile.ZipFile(str(_closed_prefix(check)) + '-sources.zip') as zipped:
            for name in actor_names:
                assert _normalized(zipped.read(name)) == _normalized((runtime_tree / name).read_bytes())
    required = {'research_loop/modular/grok_headless_transport.py',
                'research_loop/modular/grok_headless_train_solver.py',
                'evaluation/modular/headless_evaluator_model_port.py',
                'evaluation/modular/scorer_process.py',
                'tests/test_grok_headless_transport.py',
                'tests/test_headless_train_timeout.py',
                'tests/test_headless_scheduler_evaluator_stdio.py'}
    assert required <= set(gates[0]['source_after'])
    labels = verify_root_label_parity(labels_check, root_source)
    verify_runtime_root_production_parity(runtime_tree, root_source, gates[0]['source_after'])
    return gates[0], {str((runtime_tree / name).resolve()): sha(runtime_tree / name) for name in actor_names}, labels


def validate_gates(checks, labels_check, root_source, runtime_commit):
    """Read-only preflight for operator evidence; it does not read auth or create run roots."""
    gate, pins, labels = source(TREE, runtime_commit, checks, labels_check, root_source)
    print(json.dumps({'stage': 'gates_validated', 'source_commit': gate['commit'],
        'runtime_source_pins': len(pins), 'labels_source_commit': labels['commit'],
        'actual_model_calls': 0, 'validation_opened': False}), flush=True)

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


def prepare(checks, labels_check, root_source, runtime_commit):
    from evaluation.modular.scorer_process import headless_evaluator_descriptor, serialize_combination_panel
    from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
    from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel, SLOTS, _ANALYSIS
    from research_loop.modular.combinations import default_compatibility
    from research_loop.modular.contracts import FrozenRecord
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    from research_loop.modular.m4_m5_useful_controls import RECIPE
    from research_loop.modular.grok_native_deployment import GROK_130_SHA256 as EXECUTABLE_SHA256, FrozenHeadlessTrainDeployment
    from research_loop.ontology import digest

    gate, pins, labels_gate = source(TREE, runtime_commit, checks, labels_check, root_source)
    check = Path(checks[0])
    assert not PREP.exists() and not PRIVATE.exists() and not RUN.exists()
    assert MAP.is_file() and sha(EXECUTABLE) == EXECUTABLE_SHA256
    deployment = FrozenHeadlessTrainDeployment.create(EXECUTABLE)
    deployment.verify_executable(EXECUTABLE)
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
    external = [Path(__file__), MAP, OLD_REQUEST, OLD_SCHEMAS, PUBLICATION,
                Path(read(OLD_REQUEST)['config_path']), OLD_EXPORT / 'primary-eligibility-r1.json',
                SEALED / 'prospective-split.json', SEALED / 'process-audit.json']
    for evidence in [*checks, labels_check]:
        prefix = _closed_prefix(evidence)
        external.extend(Path(str(prefix) + suffix) for suffix in
                    ('-closed.json','-before.json','-native-start.json','-native-join.json',
                     '.xml','-source-members.json','-sources.zip'))
    pins.update({str(p.resolve()): sha(p) for p in external})
    pins[str(EXECUTABLE.resolve())] = EXECUTABLE_SHA256
    rubric = ScorerConfig.create(benchmark='core_pair', evaluator_id='frozen-rubric-grok-headless-train-r1',
                                rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version='1')
    spec = {'provider_kind': 'grok-headless-frozen-evaluator-v1', 'executable': str(EXECUTABLE),
        'work_root': str(PRIVATE / 'evaluator-model'), 'private_home': str(PRIVATE / 'evaluator-home'),
        'private_profile': str(PRIVATE / 'evaluator-profile'), 'public_cwd': str(PRIVATE / 'evaluator-cwd'),
        'frozen_files': pins, 'evaluator_id': rubric.record.data()['evaluator_id'], 'evaluator_version': '1',
        'model': 'grok-4.6', 'effort': 'low', 'max_calls': 8, 'max_tokens': 8 * 131072,
        'timeout_seconds': 240, 'account_read_recovery': RECOVERY,
        'native_deployment': deployment.record.data()}
    provider = headless_evaluator_descriptor(spec)
    assert not (PRIVATE / 'evaluator-model').exists()
    baseline = digest({'stage': 'actual-m4m5-headless-grok130-r4', 'source_commit': gate['commit'], 'items': tokens})
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
        'title_requested_output_cap': 100, 'wall_timeout_seconds': 240, 'max_retries': 0,
        'title_usage_and_all_call_totals': 'unknown', 'account_read_recovery': RECOVERY}
    body = {'schema': 'm4-m5-train-controller-config-v6', 'export_mode': 'primary_prospective',
        'execution_recipe': RECIPE.data(), 'provider': declaration, 'evaluator_provider': provider,
        'domain': 'train', 'stage': 'actual-m4m5-headless-grok130-r4', 'item_ids': tokens,
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
        'private_profile': str(PRIVATE / 'solver-profile'), 'public_cwd': str(PRIVATE / 'solver-cwd'),
        'timeout_seconds': 240, 'native_deployment': deployment.record.data()})
    inputs = {str(p): sha(p) for p in [PREP / 'controller.json', PRIVATE / 'server-config.json', PREP / 'solver-spec.json']}
    inputs.update({str(p): sha(p) for p in (PREP / 'public-for-compile').rglob('*') if p.is_file()})
    for evidence in [*checks, labels_check]:
        prefix = _closed_prefix(evidence)
        for suffix in ('-closed.json','-before.json','-native-start.json','-native-join.json',
                       '-source-members.json','-sources.zip','.xml'):
            path = Path(str(prefix) + suffix)
            inputs[str(path)] = sha(path)
    write(PREP / 'preparation.json', {'schema': 'actual-m4m5-headless-preparation-v2',
        'source_commit': gate['commit'], 'engineering_gates': [desc(path) for path in checks], 'labels_parity_gate': desc(labels_check),
        'labels_source_commit': labels_gate['commit'], 'root_source': str(Path(root_source).resolve()),
        'tested_source_relation': 'same commit and complete tracked py/md membership; exact per-check archives retained; CRLF/LF-normalized equality; exact actor bytes separately pinned',
        'runner': desc(Path(__file__)),
        'material_map': desc(MAP), 'input_pins': inputs, 'source_pins': pins, 'panel_digest': compiled.panel.digest,
        'task_selection': 'first_token_per_benchmark_from_existing_frozen_TRAIN_roster',
        'cells': 8, 'solver_main_limit': 40, 'evaluator_main_limit': 8, 'docker_limit': 8,
        'solver_timeout_seconds': 240, 'evaluator_timeout_seconds': 240,
        'docker_timeout_seconds': 60, 'parent_timeout_seconds': 18000,
        'parent_timeout_basis': '40 solver*240 + 8 evaluator*240 + 8 Docker*60 + bounded overhead',
        'additional_paid_api_budget': 0, 'settled_additional_charge_usd': None,
        'title_and_all_opportunity_settlement': 'unknown', 'validation_opened': False,
        'scientific_effectiveness_proven': False, 'official_or_calibrated_scoring': False,
        'allocation_scope': 'M4/M5 factorial, distinct from closed 180-opportunity diagnostic review allocation',
        'authorized_account_binding': ACCOUNT, 'prepared_at': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'stage': 'prepared', 'cells': 8, 'solver_main_limit': 40, 'evaluator_main_limit': 8,
                      'actual_model_calls': 0, 'validation_opened': False}), flush=True)


def checked():
    p = read(PREP / 'preparation.json')
    assert (p['schema'] == 'actual-m4m5-headless-preparation-v2'
            and p['solver_timeout_seconds'] == p['evaluator_timeout_seconds'] == 240
            and p['docker_timeout_seconds'] == 60 and p['parent_timeout_seconds'] == 18000)
    assert len(p['engineering_gates']) == 2
    assert all(sha(row['path']) == row['sha256'] for row in p['engineering_gates'])
    assert sha(p['labels_parity_gate']['path']) == p['labels_parity_gate']['sha256']
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
    from research_loop.modular.grok_native_deployment import FrozenHeadlessTrainDeployment
    from research_loop.modular.runtime import AuditVerifier
    p = checked(); body = read(PREP / 'controller.json')
    config = FrozenM4M5TrainConfig(FrozenRecord.from_dict(body)); compiled = compile_m4_m5_train_panel(config, packets())
    assert compiled.panel.digest == p['panel_digest']
    spec = read(PREP / 'solver-spec.json'); provider = body['provider']
    assert provider['wall_timeout_seconds'] == spec['timeout_seconds'] == 240
    port = GrokHeadlessTrainModelPort(executable=EXECUTABLE, work_root=RUN / 'solver-model',
        private_home=Path(spec['private_home']), private_profile=Path(spec['private_profile']),
        public_cwd=Path(spec['public_cwd']), frozen_files=spec['frozen_files'], max_calls=40, schemas=body['schemas'],
        slot_output_caps=provider['main_output_caps'], slot_input_byte_caps={s:262144 for s in body['schemas']},
        observed_main_token_cap=131072, account_read_recovery=RECOVERY, timeout_seconds=spec['timeout_seconds'],
        deployment=FrozenHeadlessTrainDeployment(FrozenRecord.from_dict(spec['native_deployment'])))
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
    parser.add_argument('action', choices=['validate-gates','prepare','run','worker'])
    parser.add_argument('--engineering-check', action='append')
    parser.add_argument('--labels-check')
    parser.add_argument('--root-source')
    parser.add_argument('--runtime-commit')
    args = parser.parse_args()
    try:
        if args.action in {'validate-gates', 'prepare'}:
            assert args.engineering_check and len(args.engineering_check) == 2
            assert args.labels_check and args.root_source and args.runtime_commit
            values = ([Path(value) for value in args.engineering_check], Path(args.labels_check),
                      Path(args.root_source), args.runtime_commit)
            if args.action == 'validate-gates':
                validate_gates(*values)
            else:
                prepare(*values)
        elif args.action == 'run': run()
        else: worker()
    except Exception as exc:
        root = RUN if RUN.exists() else PREP if PREP.exists() else WORK
        failure = root / ('actual-m4m5-' + args.action + '-failure.json')
        if not failure.exists(): write(failure, {'action':args.action,'error_type':type(exc).__name__,
            'message':str(exc)[:180], 'validation_opened':False, 'status':'inconclusive'})
        print(json.dumps({'stage':'failed','action':args.action,'error_type':type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
