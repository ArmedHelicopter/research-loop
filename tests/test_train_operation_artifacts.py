"""Real operation hosts and independent byte/state reads; no model or VAL access."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular import train_operations as ops
from research_loop.ontology import ContractError


def _case(tmp_path, experiment, variant, *, fault=None):
    task = PublicTask.create(DataIdentity('synthetic', 'task', 'family', 'v1', 'split', 'train'), {'question': 'Public fixture'})
    manifest = TrainingManifest.freeze((task.identity,))
    parent = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={'memory': {'lesson': 'parent'}}, search_cost=0)
    candidate = CandidatePackage.create(parent_digest=parent.digest, manifest=manifest, changes={'memory': {'lesson': 'candidate'}}, search_cost=1)
    root = tmp_path/'operation'
    def feedback(request):
        rows = [json.loads(line)['descriptor'] for line in (root/'operation-artifacts.jsonl').read_text().splitlines()]
        assert rows[-1]['kind'] == 'operation_event'
        assert rows[-1]['payload']['canonical']['stage'] == 'feedback_reserved'
        if fault == 'feedback':
            raise OSError('retained feedback failure')
        return FrozenRecord.from_dict({'subject_digest': request.content_hash, 'status': 'ineligible', 'units': 1})
    authority = ops.TrainOperationAuthority('public-fixture', b'train-operation-fixture-secret-32!',
        feedback=feedback if experiment == 'Q6.5' else None)
    plan = SimpleNamespace(record=FrozenRecord.from_dict({'experiment_id': experiment,
        'feedback_rules': {'criterion': 'train fixture only', 'max_units': 2} if experiment == 'Q6.5' else None}),
        targets=(SimpleNamespace(task=task),))
    cell = {'cell_id': hashlib.sha256((experiment+variant).encode()).hexdigest(), 'task_digest': task.content_hash,
        'variant': variant, 'arm': {'enabled': ['M9']}}
    args = (plan, cell, parent, candidate, (), root, authority)
    return args


def _read(root):
    return json.loads((root/'receipt.json').read_bytes())


def _resign(root, authority, envelope=None):
    envelope = envelope or _read(root)
    files = ops._files(root); files.pop('receipt.json')
    envelope['record']['files'] = files
    envelope['signature'] = authority.sign(FrozenRecord.from_dict(envelope['record']))
    (root/'receipt.json').write_bytes((FrozenRecord.from_dict(envelope).encoded+'\n').encode())


@pytest.mark.parametrize('experiment,variant', [(e,v) for e,vs in ops._VARIANTS.items() for v in vs])
def test_actual_operation_outputs_and_readonly_consumer(tmp_path, monkeypatch, experiment, variant):
    args = _case(tmp_path, experiment, variant); root = args[-2]
    result = ops._operation(*args)
    envelope = _read(root); record = envelope['record']
    assert record['schema'] == 'train-operation-receipt-v2'
    rows = [json.loads(line)['descriptor'] for line in (root/'operation-artifacts.jsonl').read_text().splitlines()]
    files = [r for r in rows if r['kind'] == 'operation_file']
    assert files and all(r['optimizer_visible'] is False and r['scientific_validated'] is False for r in rows)
    assert {r['identity']['domain'] for r in rows} == {'train'}
    assert all(r['payload']['canonical']['blob'].startswith('operation-blobs/') for r in files)
    assert rows[0]['producer_source']['path'].endswith('train_operation_artifacts.py')
    for row in rows:
        if row['kind'] == 'operation_event' or row['kind'] == 'operation_file' and row['payload']['canonical']['file'] == 'operations.jsonl':
            assert row['producer_source']['path'].endswith('metaprogram_training.py')
    if variant in {'drift','offline'}:
        assert result is None and record['status'] == 'blocked'
    elif experiment == 'Q6.1':
        assert record['status'] == 'rejected'
    before = ops._files(root)
    def forbidden(*a, **kw):
        pytest.fail('read-only consumer reconstructed a mutating host')
    monkeypatch.setattr(ops, '_StagingRuntime', forbidden)
    monkeypatch.setattr(ops, 'ExecutionRuntime', forbidden)
    monkeypatch.setattr(ops, 'FileDeploymentPort', forbidden)
    assert ops._verify_operation(*args) == result
    assert ops._files(root) == before


def test_feedback_failure_keeps_original_opportunity_and_unknown_usage(tmp_path):
    args = _case(tmp_path, 'Q6.5', 'sealed_calibrated', fault='feedback')
    selected, _ = ops._operation(*args)
    record = _read(args[-2])['record']
    assert selected == args[2]
    assert record['feedback']['usage_unknown'] and record['feedback']['units'] is None
    rows = [json.loads(x)['descriptor'] for x in (args[-2]/'operation-artifacts.jsonl').read_text().splitlines()]
    events = [r['payload']['canonical']['stage'] for r in rows if r['kind'] == 'operation_event']
    assert events.count('feedback_reserved') == 1 and events.count('feedback_result') == 1


def test_committed_activation_then_host_error_retains_actual_failed_state(tmp_path, monkeypatch):
    args = _case(tmp_path, 'Q6.6', 'promote')
    original = ops._StagingRuntime.activate
    def committed_then_error(self, token, package):
        original(self, token, package)
        raise OSError('after actual commit')
    monkeypatch.setattr(ops._StagingRuntime, 'activate', committed_then_error)
    assert ops._operation(*args) is None
    root = args[-2]; record = _read(root)['record']
    assert record['status'] == 'operation_failed' and record['selected_package'] is None
    from research_loop.modular.train_operation_artifacts import _db
    state = _db((root/'state.sqlite').read_bytes(), shadow=False)
    assert state['state'] == [args[3].digest] and len(state['used']) == 1
    assert ops._verify_operation(*args) is None
    from research_loop.modular.train_operation_artifacts import verify_operation_artifacts
    outcome = {k: record[k] for k in ('subject','actions','status','selected_package','public','feedback')}
    audited = verify_operation_artifacts(root, plan=args[0], cell=args[1], parent=args[2], candidate=args[3],
        histories=args[4], authority=args[-1], outcome=outcome, binding=record['artifacts']).data()
    assert audited['storage_verified'] and not audited['engineering_verified'] and not audited['operation_validated']


@pytest.mark.parametrize('fault', ['state', 'omit_catalogue', 'extra_file', 'truncate', 'nested_blob'])
def test_host_signature_cannot_hide_changed_or_omitted_original_outputs(tmp_path, fault):
    args = _case(tmp_path, 'Q6.6', 'rollback'); ops._operation(*args); root = args[-2]
    if fault == 'state':
        (root/'state.sqlite').write_bytes(b'not the original database')
    elif fault == 'omit_catalogue':
        (root/'operation-artifacts.jsonl').unlink()
    elif fault == 'extra_file':
        (root/'undeclared.txt').write_bytes(b'extra')
    elif fault == 'truncate':
        path = root/'operation-artifacts.jsonl'; path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    else:
        (root/'operation-blobs'/'unregistered').mkdir()
        (root/'operation-blobs'/'unregistered'/'extra').write_bytes(b'not an audited blob')
    _resign(root, args[-1])
    with pytest.raises((ContractError, OSError)):
        ops._verify_operation(*args)


def _rebuild(root, authority, transform):
    """Attacker can recompute local hashes/MAC, but cannot change expected inputs."""
    path = root/'operation-artifacts.jsonl'
    rows = [FrozenRecord.from_dict(json.loads(line)['descriptor']) for line in path.read_text().splitlines()]
    first = rows[0].data()
    path.unlink(); path.with_name(path.name+'.seal.json').unlink()
    cat = ArtifactCatalogue(path, identity=DataIdentity.parse(first['identity']), **first['binding'])
    mapping = {}
    for old in rows:
        row = old.data(); value = row['payload']['canonical']; transform(row, value)
        if row['kind'] == 'operation_checkpoint':
            value['files'] = [mapping[x] for x in value['files']]
        spec = {key: row[key] for key in ('kind','module','coverage','status','producer_source','optimizer_visible','config_refs','cost','checks')}
        new = cat.append(**spec, payload=value, parents=[mapping[x] for x in row['parents']])
        mapping[old.content_hash] = new.content_hash
    seal = cat.seal()
    closure_path = root/'operation-artifact-closure.json'
    closure = json.loads(closure_path.read_bytes()); closure['catalogue_seal'] = seal.data()
    closure['outcome_digest'] = FrozenRecord.from_dict(cat.records()[-1].data()['payload']['canonical']).content_hash
    closure_path.write_bytes((FrozenRecord.from_dict(closure).encoded+'\n').encode())
    env = _read(root); env['record']['artifacts']['catalogue_seal'] = seal.data()
    env['record']['artifacts']['sha256'] = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    _resign(root, authority, env)


def test_rehashed_intermediate_state_substitution_is_rejected_semantically(tmp_path):
    args = _case(tmp_path, 'Q6.6', 'rollback'); ops._operation(*args); root = args[-2]
    rows = [json.loads(line)['descriptor'] for line in (root/'operation-artifacts.jsonl').read_text().splitlines()]
    promoted = next(r['payload']['canonical'] for r in rows if r['kind'] == 'operation_file'
        and r['payload']['canonical']['stage'] == 'promote' and r['payload']['canonical']['file'] == 'state.sqlite')
    def substitute(row, value):
        if row['kind'] == 'operation_file' and value['stage'] == 'initialized' and value['file'] == 'state.sqlite':
            value.update({k: promoted[k] for k in ('blob','sha256','bytes')})
    _rebuild(root, args[-1], substitute)
    with pytest.raises(ContractError, match='staging snapshot'):
        ops._verify_operation(*args)


def test_wrong_task_rejected_even_when_same_candidate_and_output_paths(tmp_path):
    args = list(_case(tmp_path, 'Q6.6', 'promote')); ops._operation(*args)
    args[1] = {**args[1], 'cell_id': 'f'*64}
    with pytest.raises(ContractError):
        ops._verify_operation(*args)


@pytest.mark.parametrize('fault', ['ack', 'status', 'allowed_challenge'])
def test_rehashed_false_status_or_ack_cannot_pass_semantic_acceptance(tmp_path, fault):
    experiment, variant = ('Q6.1', 'change_rule') if fault == 'allowed_challenge' else ('Q6.6', 'promote')
    args = _case(tmp_path, experiment, variant); ops._operation(*args); root = args[-2]
    envelope = _read(root); outcome = envelope['record']
    if fault == 'ack':
        outcome['actions'][0]['ack']['online'] = 1  # bool/int look equal in loose dict comparison
    elif fault == 'status':
        outcome['status'] = outcome['public']['status'] = 'invented'
    else:
        outcome['status'] = outcome['public']['status'] = outcome['actions'][0]['status'] = 'accepted'
    journal = root/'operations.jsonl'
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    events[-1]['data'] = {k: outcome[k] for k in ('subject','actions','status','selected_package','public')}
    raw = b''.join((FrozenRecord.from_dict(e).encoded+'\n').encode() for e in events)
    journal.write_bytes(raw)
    key = hashlib.sha256(raw).hexdigest(); (root/'operation-blobs'/key).write_bytes(raw)
    old_terminal = None
    def transform(row, value):
        nonlocal old_terminal
        if row['kind'] == 'operation_event' and value['stage'] == 'operation_result':
            value.update(events[-1])
        elif row['kind'] == 'operation_file' and value['stage'] == 'terminal' and value['file'] == 'operations.jsonl':
            old_terminal = value['sha256']
            value.update(sha256=key, blob='operation-blobs/'+key, bytes=len(raw))
        elif row['kind'] == 'operation_outcome':
            value.update({k: outcome[k] for k in ('subject','actions','status','selected_package','public','feedback')})
            row['status'] = 'produced'
    (root/'receipt.json').write_bytes((FrozenRecord.from_dict(envelope).encoded+'\n').encode())
    _rebuild(root, args[-1], transform)
    (root/'operation-blobs'/old_terminal).unlink(); _resign(root, args[-1])
    with pytest.raises(ContractError, match='status|actions|frozen'):
        ops._verify_operation(*args)


def test_repeated_cell_has_distinct_original_attempts(tmp_path):
    args = list(_case(tmp_path, 'Q6.1', 'change_rule')); ops._operation(*args)
    first = _read(args[-2])['record']['artifacts']['catalogue_seal']['binding']['run_id']
    args[-2] = tmp_path/'second'; ops._operation(*args)
    second = _read(args[-2])['record']['artifacts']['catalogue_seal']['binding']['run_id']
    assert first != second


@pytest.mark.parametrize('experiment,variant', [('Q6.1','self_activate'), ('Q6.5','sealed_calibrated'), ('Q6.6','rollback')])
def test_real_training_cell_consumes_audited_operation_before_docker(tmp_path, monkeypatch, experiment, variant):
    from test_modular_train_operations import operation_fixture
    plan, kwargs, _, _ = operation_fixture(tmp_path, monkeypatch, experiment)
    cell = next(c for c in plan.record.data()['cells'] if c['variant'] == variant and 'M9' in c['arm']['enabled'])
    adapter = ops._attempt(plan, cell, {}, kwargs['authority'])
    target = next(t for t in plan.targets if t.task.content_hash == cell['task_digest'])
    root = kwargs['run_root']; root.mkdir()
    broker = ops.shared.DockerExecutionBroker([root, *{p.parent for t in plan.targets for _,p in t.inputs}])
    result = ops.shared._run_cell(adapter, cell, target, root/'cells'/cell['cell_id'],
        kwargs['model'], broker, kwargs['audit_verifier'])
    assert result.record.data()['status'] == 'succeeded'
    ledger = json.loads(kwargs['model'].ledger_path.read_bytes())
    ops.shared._verify_cell(result, adapter, cell, target, ledger)
    operation = _read(result.root/'host-operation')['record']
    lock = json.loads((result.root/'solver'/'trace.jsonl').read_text().splitlines()[0])['data']
    assert lock['package_digest'] == CandidatePackage(FrozenRecord.from_dict(operation['selected_package'])).digest
    (result.root/'host-operation'/'operation-artifact-closure.json').unlink()
    with pytest.raises((ContractError, OSError)):
        ops.shared._verify_cell(result, adapter, cell, target, ledger)
