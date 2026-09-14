"""One build replay reuses its already bound accounting observation."""
import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession
from research_loop.modular.state_improvement_build import run_build, verify_build
from research_loop.modular.state_improvement_combination_controller import recipes
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import ContractError
from research_loop.modular.metaprogram_training import metaprogram_schemas
from helpers.native_phase_provider import native_phase_provider
import test_state_improvement_train_controller as state_fixture


def test_build_replay_does_not_reinspect_its_bound_accounting(tmp_path, monkeypatch):
    setup = state_fixture.prepare(tmp_path, monkeypatch)
    plan = setup['plan']
    provider, logs = native_phase_provider(tmp_path/'native-provider', monkeypatch,
        schemas=metaprogram_schemas(), max_calls=3, response=lambda request: {
            'entrypoint':'emit_literal_change_v1','surface':'prompt',
            'key':'instructions','value':'Use public history observations'})
    recipe = recipes(plan.data()['baseline_digest'])[0]
    pair = recipe['pair']
    broker = DockerExecutionBroker([tmp_path, plan.history_inputs[0][1].parent])
    args = dict(recipe=recipe, plan_digest=plan.record.content_hash, history=plan.history,
        material=plan.history_material(pair), qualifier=setup['verifiers'][pair],
        parent=plan.parent, fixed_builder=plan.fixed_builder, broker=broker,
        inputs=dict(plan.history_inputs))
    session = PhaseProviderSession(provider, tmp_path/'scopes.json')
    with session.scope('build:'+FrozenRecord.from_dict(recipe).content_hash) as scoped:
        built = run_build(**args, model=scoped, audit_verifier=state_fixture.AUDIT, root=tmp_path/'build')
    assert built.record.data()['status'] == 'succeeded'
    ledger = session.seal(tmp_path/'ledger.json')
    original = provider.inspect; inspections = []
    def inspect():
        inspections.append(True)
        return original()
    monkeypatch.setattr(provider, 'inspect', inspect)
    for _ in range(2):
        inspections.clear()
        candidate = verify_build(built, **args, ledger=ledger)
        assert candidate.digest == built.record.data()['candidate_digest']
        assert len(inspections) == 3, 'duplicate full provider replay for already bound build accounting'
    assert len(logs) == 1
    # A new verification boundary must read current original response bytes.
    response = provider.backend.calls_root/'0001-builder_proposal'/'response.private.json'
    response.write_bytes(response.read_bytes()+b' ')
    with pytest.raises(ContractError):
        verify_build(built, **args, ledger=ledger)
    assert len(logs) == 1
