"""Actual local builder/invoke seam checks; no model API or acceptance calls."""
import json
from pathlib import Path

import pytest

from research_loop.modular import builder_artifacts as artifacts
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.full_loo_modules import PROPOSAL_INSTRUCTION, REVISION_INSTRUCTION, select_builder
from research_loop.modular.modules.improvement import (
    BuilderRunReceipt, CandidatePackage, FrozenBuilderVersion, RestrictedBuilderPort, TrainingManifest,
)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError


def fixture(root, enabled=True):
    identity = DataIdentity('synthetic', 'builder-task', 'group', 'v1', 'split', 'train')
    manifest = TrainingManifest.freeze([identity])
    parent = CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={'prompt': {'instructions': 'initial public guidance'}}, search_cost=1)
    fixed = FrozenBuilderVersion.freeze({'entrypoint': 'emit_literal_change_v1',
        'surface': 'prompt', 'key': 'instructions', 'value': 'fixed'})
    recipe = {'history_build_levels': {'M9': int(enabled)}}
    response = FrozenRecord.from_dict({'entrypoint': 'emit_literal_change_v1',
        'surface': 'memory', 'key': 'lesson', 'value': 'check public units'} if enabled
        else {'instructions': 'ordinary revision of public units'})
    slot = 'builder_proposal' if enabled else 'ordinary_revision'
    session = RunSession(PublicTask.create(identity, {'question': 'public fixture'}), package_digest=parent.digest,
        arm=default_compatibility('fixture').arm(('M1', 'M2', 'M9') if enabled else ()),
        objective=FrozenRecord.from_dict({'question': 'public fixture'}), slots=(slot,), execution_limit=0,
        sidecar=root / 'runtime', verifier=AuditVerifier({'first': b'a' * 32, 'second': b'b' * 32}),
        required_audit=('measurement',))
    actual = session.invoke(slot, lambda request: response,
        instruction=PROPOSAL_INSTRUCTION if enabled else REVISION_INSTRUCTION)
    kwargs = dict(root=root, builder=select_builder(actual, recipe, fixed), parent=parent,
                  response=actual, recipe=recipe, fixed_builder=fixed)
    return session, kwargs


def rows(session):
    return [r for r in session.artifacts.records() if r.data()['kind'].startswith('m9_')]


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('enabled', [True, False])
def test_actual_invocation_precedes_build_and_each_durable_output_is_registered(tmp_path, monkeypatch, enabled):
    session, kwargs = fixture(tmp_path, enabled)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    assert [r.data()['kind'] for r in rows(session)] == ['m9_builder_selection', 'm9_builder_subjects']
    assert not (tmp_path / 'builder.json').exists()
    original = RestrictedBuilderPort.execute
    calls = []

    def actual(port, *args, **kw):
        calls.append(kw)
        assert [r.data()['kind'] for r in rows(session)][-1] == 'm9_builder_file'
        assert (tmp_path / 'builder.json').is_file()
        assert not (tmp_path / 'candidate.json').exists()
        return original(port, *args, **kw)

    monkeypatch.setattr(RestrictedBuilderPort, 'execute', actual)
    candidate, receipt = bridge.execute()
    assert len(calls) == 1
    assert receipt.output_candidate_digest == candidate.digest
    registered = rows(session)
    assert [r.data()['kind'] for r in registered] == [
        'm9_builder_selection', 'm9_builder_subjects', 'm9_builder_file',
        'm9_builder_return', 'm9_builder_receipt', 'm9_candidate', 'm9_build_terminal']
    assert registered[5].data()['parents'] == [registered[4].content_hash]
    assert all(r.data()['status'] == ('produced' if enabled else 'not_applied') for r in registered)
    assert all(Path(r.data()['producer_source']['path']).suffix == '.py' for r in registered)
    assert not any(r.data()['scientific_validated'] for r in registered)
    monkeypatch.setattr(RestrictedBuilderPort, 'execute', original)
    seal = session.artifacts.seal()
    before = tree_bytes(tmp_path)
    verified = artifacts.verify_builder_artifacts(session.artifacts, **kwargs)
    assert verified.data()['status'] == 'succeeded'
    assert verified.data()['activation'] == ('applied' if enabled else 'not_applied')
    session.artifacts.verify(seal)
    assert tree_bytes(tmp_path) == before
    # A later enclosing-stage failure cannot rewrite a valid build terminal.
    assert bridge.fail(ContractError('later trace failure')) == registered[-1]
    assert tree_bytes(tmp_path) == before


def test_begin_rejects_substituted_response_parent_and_preexisting_outputs(tmp_path):
    session, kwargs = fixture(tmp_path)
    response = FrozenRecord.from_dict({**kwargs['response'].data(), 'value': 'substituted'})
    other = {**kwargs, 'response': response, 'builder': select_builder(response, kwargs['recipe'], kwargs['fixed_builder'])}
    with pytest.raises(ContractError, match='actual builder invocation'):
        artifacts.begin_builder_artifacts(session.artifacts, **other)
    parent = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest(
        FrozenRecord.from_dict(kwargs['parent'].record.data()['training_manifest'])),
        changes={'prompt': {'instructions': 'another parent'}}, search_cost=1)
    with pytest.raises(ContractError, match='actual run lock'):
        artifacts.begin_builder_artifacts(session.artifacts, **{**kwargs, 'parent': parent})
    (tmp_path / 'candidate.json').write_bytes(b'{}\n')
    with pytest.raises(ContractError, match='precede'):
        artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    assert rows(session) == []


@pytest.mark.parametrize('enabled', [True, False])
def test_original_contract_error_escapes_with_durable_failed_terminal(tmp_path, monkeypatch, enabled):
    session, kwargs = fixture(tmp_path, enabled)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    error = ContractError('literal builder failed')

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(RestrictedBuilderPort, 'execute', fail)
    with pytest.raises(ContractError) as caught:
        bridge.execute()
    assert caught.value is error
    assert rows(session)[-1].data()['status'] == 'failed'
    assert (tmp_path / 'builder.json').is_file()
    assert not (tmp_path / 'candidate.json').exists()
    session.artifacts.seal()
    before = tree_bytes(tmp_path)
    verified = artifacts.verify_builder_artifacts(session.artifacts, **kwargs)
    assert verified.data()['status'] == 'failed'
    assert tree_bytes(tmp_path) == before


def test_invalid_returned_candidate_and_receipt_are_retained(tmp_path, monkeypatch):
    session, kwargs = fixture(tmp_path)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    original = RestrictedBuilderPort.execute

    def bad(port, *args, **kw):
        candidate, receipt = original(port, *args, **kw)
        changed = candidate.record.data()
        changed['changes'] = {'memory': {'lesson': 'not the selected DSL result'}}
        candidate = CandidatePackage(FrozenRecord.from_dict(changed))
        receipt = BuilderRunReceipt(FrozenRecord.from_dict({**receipt.record.data(), 'output_candidate_digest': candidate.digest}))
        return candidate, receipt

    monkeypatch.setattr(RestrictedBuilderPort, 'execute', bad)
    with pytest.raises(ContractError, match='does not bind'):
        bridge.execute()
    assert (tmp_path / 'candidate.json').exists() and (tmp_path / 'builder-receipt.json').exists()
    assert json.loads((tmp_path / 'm9-build-terminal.json').read_bytes())['phase'] == 'validate'
    assert artifacts.verify_builder_artifacts(session.artifacts, **kwargs).data()['status'] == 'failed'


def test_partial_durable_write_is_retained_and_readonly(tmp_path, monkeypatch):
    session, kwargs = fixture(tmp_path)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    original = artifacts._exclusive

    def partial(path, record):
        if path.name == 'builder.json':
            path.write_bytes(b'{"partial":')
            raise OSError('interrupted file write')
        return original(path, record)

    monkeypatch.setattr(artifacts, '_exclusive', partial)
    with pytest.raises(OSError, match='interrupted'):
        bridge.execute()
    assert (tmp_path / 'builder.json').read_bytes() == b'{"partial":'
    session.artifacts.seal()
    before = tree_bytes(tmp_path)
    assert artifacts.verify_builder_artifacts(session.artifacts, **kwargs).data()['status'] == 'failed'
    assert before == tree_bytes(tmp_path)


def rewrite_catalogue(session, edit):
    """Coherently rewrite payload, parent links, chain and seal, as an attacker."""
    raw = [json.loads(line) for line in session.artifacts.path.read_text().splitlines()]
    replacements, previous = {}, None
    for row in raw:
        old = row['descriptor_digest']
        body = row['descriptor']
        edit(body)
        body['parents'] = [replacements.get(p, p) for p in body['parents']]
        payload = FrozenRecord.from_dict(body['payload']['canonical'])
        body['payload'] = {'canonical': payload.data(), 'digest': payload.content_hash,
                           'bytes': len(payload.encoded.encode()), 'encoding': 'canonical_json'}
        row['descriptor_digest'] = FrozenRecord.from_dict(body).content_hash
        replacements[old] = row['descriptor_digest']
        row['previous'] = previous
        previous = FrozenRecord.from_dict(row).content_hash
    session.artifacts.path.write_text(''.join(FrozenRecord.from_dict(r).encoded + '\n' for r in raw), encoding='utf-8', newline='\n')
    seal = FrozenRecord.from_dict({'schema': 'artifact-catalogue-seal-v1', 'count': len(raw),
                                  'head': previous, 'binding': session.artifacts.binding})
    session.artifacts.seal_path.write_text(seal.encoded + '\n', encoding='utf-8', newline='\n')
    session.artifacts.verify(seal)


def test_coherently_rehashed_candidate_receipt_files_and_terminal_fail_semantic_replay(tmp_path):
    session, kwargs = fixture(tmp_path)
    artifacts.begin_builder_artifacts(session.artifacts, **kwargs).execute()
    session.artifacts.seal()
    candidate = json.loads((tmp_path / 'candidate.json').read_bytes())
    candidate['changes'] = {'memory': {'lesson': 'forged but internally consistent'}}
    changed = FrozenRecord.from_dict(candidate)
    (tmp_path / 'candidate.json').write_text(changed.encoded + '\n', encoding='utf-8', newline='\n')
    receipt = json.loads((tmp_path / 'builder-receipt.json').read_bytes())
    receipt['output_candidate_digest'] = changed.content_hash
    (tmp_path / 'builder-receipt.json').write_text(FrozenRecord.from_dict(receipt).encoded + '\n', encoding='utf-8', newline='\n')
    returned = json.loads((tmp_path / artifacts._RETURNED).read_bytes())
    returned.update(candidate=candidate, receipt=receipt)
    (tmp_path / artifacts._RETURNED).write_text(FrozenRecord.from_dict(returned).encoded + '\n', encoding='utf-8', newline='\n')
    terminal = json.loads((tmp_path / 'm9-build-terminal.json').read_bytes())
    terminal['files'] = {name: artifacts._snapshot(tmp_path, name) for name in artifacts._FILES}
    (tmp_path / 'm9-build-terminal.json').write_text(FrozenRecord.from_dict(terminal).encoded + '\n', encoding='utf-8', newline='\n')

    def edit(body):
        if body['kind'] in {*artifacts._KINDS.values(), 'm9_build_terminal'}:
            name = body['payload']['canonical']['file']
            body['payload']['canonical'] = artifacts._snapshot(tmp_path, name)

    rewrite_catalogue(session, edit)
    before = tree_bytes(tmp_path)
    with pytest.raises(ContractError, match='does not bind'):
        artifacts.verify_builder_artifacts(session.artifacts, **kwargs)
    assert tree_bytes(tmp_path) == before


def test_missing_terminal_is_not_recreated_by_reader(tmp_path):
    session, kwargs = fixture(tmp_path)
    artifacts.begin_builder_artifacts(session.artifacts, **kwargs).execute()
    session.artifacts.seal()
    (tmp_path / 'm9-build-terminal.json').unlink()
    before = tree_bytes(tmp_path)
    with pytest.raises(ContractError, match='missing'):
        artifacts.verify_builder_artifacts(session.artifacts, **kwargs)
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize('missing', ['candidate', 'receipt'])
def test_mixed_valid_invalid_returns_keep_each_original_record(tmp_path, monkeypatch, missing):
    session, kwargs = fixture(tmp_path)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    original = RestrictedBuilderPort.execute
    actual = {}

    def mixed(port, *args, **kw):
        candidate, receipt = original(port, *args, **kw)
        actual.update(candidate=candidate.record.data(), receipt=receipt.record.data())
        return (None, receipt) if missing == 'candidate' else (candidate, None)

    monkeypatch.setattr(RestrictedBuilderPort, 'execute', mixed)
    with pytest.raises(ContractError, match='unrecordable'):
        bridge.execute()
    returned = json.loads((tmp_path / artifacts._RETURNED).read_bytes())
    retained = 'receipt' if missing == 'candidate' else 'candidate'
    assert returned[retained] == actual[retained] and returned[missing] is None
    assert returned[missing + '_type'] == 'NoneType'
    session.artifacts.seal()
    before = tree_bytes(tmp_path)
    assert artifacts.verify_builder_artifacts(session.artifacts, **kwargs).data()['status'] == 'failed'
    assert tree_bytes(tmp_path) == before


def test_failure_before_execute_preserves_allocation_without_charging_execution(tmp_path):
    session, kwargs = fixture(tmp_path)
    bridge = artifacts.begin_builder_artifacts(session.artifacts, **kwargs)
    bridge.fail(ContractError('intervening caller failure'))
    terminal = json.loads((tmp_path / 'm9-build-terminal.json').read_bytes())
    assert terminal['search_cost'] == 1 and terminal['builder_attempted'] is False
    assert rows(session)[-1].data()['cost'] == {'known': True, 'units': 0}
    assert artifacts.verify_builder_artifacts(session.artifacts, **kwargs).data()['status'] == 'failed'


def test_rehashed_impossible_failed_phase_is_rejected(tmp_path):
    session, kwargs = fixture(tmp_path)
    artifacts.begin_builder_artifacts(session.artifacts, **kwargs).execute()
    session.artifacts.seal()
    terminal = json.loads((tmp_path / 'm9-build-terminal.json').read_bytes())
    terminal.update(status='failed', phase='before_execute', error_type='OSError', error='forged', builder_attempted=False)
    (tmp_path / 'm9-build-terminal.json').write_text(FrozenRecord.from_dict(terminal).encoded + '\n', encoding='utf-8', newline='\n')

    def edit(body):
        if body['kind'] == 'm9_build_terminal':
            body['payload']['canonical'] = artifacts._snapshot(tmp_path, 'm9-build-terminal.json')
            body.update(status='failed', cost={'known': True, 'units': 0})

    rewrite_catalogue(session, edit)
    with pytest.raises(ContractError, match='phase cannot produce'):
        artifacts.verify_builder_artifacts(session.artifacts, **kwargs)


def test_original_trace_blocks_rehashed_substitute_response_before_begin(tmp_path):
    session, kwargs = fixture(tmp_path)
    response = FrozenRecord.from_dict({**kwargs['response'].data(), 'value': 'forged invocation'})

    def edit(body):
        if body['kind'] == 'trace_event' and body['payload']['canonical']['stage'] == 'model_response':
            body['payload']['canonical']['data']['response'] = response.data()

    rewrite_catalogue(session, edit)
    other = {**kwargs, 'response': response, 'builder': select_builder(response, kwargs['recipe'], kwargs['fixed_builder'])}
    with pytest.raises(ContractError, match='original trace'):
        artifacts.begin_builder_artifacts(session.artifacts, **other)
    assert not (tmp_path / 'builder.json').exists()
