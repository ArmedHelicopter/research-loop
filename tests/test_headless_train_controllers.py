"""Headless Grok TRAIN reaches the actual singleton controller through its typed provider."""

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.modular.train_provider_preflight import LEGACY_TRANSPORT_FIELDS, native_provider_preflight
from research_loop.ontology import ContractError

from helpers.headless_train_provider import headless_train_provider
from helpers.native_ordinary_provider import native_ordinary_provider
from test_modular_linked_train_controller import AUDIT, _linked_config
from test_modular_train_controller import snapshot_and_custody


def _response(request):
    body = request.data()
    if body['slot'] == 'scenario':
        directions = ['increase', 'decrease', 'increase']
        return {'question': 'public', 'budget_units': 3, 'branches': [
            {'hypothesis_id': f'h{index}', 'mechanism_key': f'm{index}', 'mechanism': 'public mechanism',
             'intervention': 'public intervention', 'elimination_condition': 'public disagreement',
             'predictions': [{'prediction_id': f'p{index}', 'discriminator_id': 'shared',
                              'observable': 'public observable', 'direction': direction, 'value_range': None,
                              'failure_condition': 'does not ' + direction}]}
            for index, direction in enumerate(directions)]}
    return {'objective_digest': body['module_context']['required_objective_digest'], 'outcome': 'unknown',
            'evidence_ids': [], 'conclusion': 'synthetic engineering only', 'programme_complete': False}


def _native_body(old, provider):
    body = {key: value for key, value in old.items() if key not in LEGACY_TRANSPORT_FIELDS}
    body.update(schema='train-panel-controller-v2', provider=provider.configuration().data())
    return body


def test_headless_synthetic_os_http_provider_reaches_singleton_controller(tmp_path, monkeypatch):
    snapshot, custody = snapshot_and_custody(tmp_path)
    old = _linked_config(custody, snapshot, tmp_path, linked=False).data()
    provider, calls, gets = headless_train_provider(tmp_path / 'headless', monkeypatch,
        schemas=old['schemas'], max_calls=old['max_calls'], response=_response)
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict(_native_body(old, provider)))

    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / 'export', run_root=tmp_path / 'run', model=provider,
        audit_verifier=AuditVerifier(AUDIT))

    receipt = result.receipt.data()
    assert receipt['execution_status'] == 'engineering_complete'
    assert receipt['provider']['provider_kind'] == 'grok-headless-public-train-v1'
    assert len(calls) == old['max_calls'] == 24
    assert len(gets) == 6 * len(calls)
    assert len(result.runtimes) == receipt['expected_cells'] == 12
    assert receipt['provider_final_gate']['provider_evidence_eligible'] is True
    assert all(row.data()['status'] == 'succeeded' for row in result.attempts)


def test_frozen_singleton_provider_kind_rejects_acp_and_retains_acp_preflight(tmp_path, monkeypatch):
    snapshot, custody = snapshot_and_custody(tmp_path)
    old = _linked_config(custody, snapshot, tmp_path, linked=False).data()
    headless, headless_calls, _ = headless_train_provider(tmp_path / 'headless', monkeypatch,
        schemas=old['schemas'], max_calls=old['max_calls'], response=_response)
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict(_native_body(old, headless)))
    acp, acp_calls = native_ordinary_provider(tmp_path / 'acp', monkeypatch, schemas=old['schemas'],
        max_calls=old['max_calls'], response=_response)

    with pytest.raises(ContractError, match='real model port'):
        run_train_panel(frozen, custody=custody, snapshot_root=snapshot,
            export_root=tmp_path / 'wrong-export', run_root=tmp_path / 'wrong-run', model=acp,
            audit_verifier=AuditVerifier(AUDIT))
    assert not headless_calls and not acp_calls

    acp_body = _native_body(old, acp)
    assert native_provider_preflight(acp_body, acp, family='singleton', schemas=old['schemas'],
        main_opportunities=old['max_calls']) == acp.configuration()


def test_q32_and_c4_factory_gates_select_the_frozen_provider_kind(tmp_path, monkeypatch):
    from research_loop.modular import q32_native_provider as q32
    from research_loop.modular.full_loo_native_provider import FrozenNativeFullLooRuntimePlan, run_native_full_loo_train

    snapshot, custody = snapshot_and_custody(tmp_path)
    old = _linked_config(custody, snapshot, tmp_path, linked=False).data()
    headless, _, _ = headless_train_provider(tmp_path / 'headless', monkeypatch,
        schemas=old['schemas'], max_calls=old['max_calls'], response=_response)
    acp, acp_calls = native_ordinary_provider(tmp_path / 'acp', monkeypatch, schemas=old['schemas'],
        max_calls=old['max_calls'], response=_response)
    headless_config = headless.configuration().data()

    class Compiled:
        def data(self):
            return {'providers_by_cell': {'cell': headless_config}, 'tasks': [], 'budget': {},
                    'cells': [{'cell_id': 'cell'}]}

    monkeypatch.setattr(q32, 'validate_provider_map', lambda *_: None)
    with pytest.raises(ContractError, match='factory requires'):
        q32.run_native((), Compiled(), tmp_path / 'export', tmp_path / 'q32-run', lambda _: acp, None)

    monkeypatch.setattr(FrozenNativeFullLooRuntimePlan, '__post_init__', lambda self: None)
    monkeypatch.setattr(FrozenNativeFullLooRuntimePlan, 'native_data',
        lambda self: {'provider_configuration': headless_config})
    plan = object.__new__(FrozenNativeFullLooRuntimePlan)
    with pytest.raises(ContractError, match='frozen closed Grok provider kind'):
        run_native_full_loo_train(plan, prospective_exporter=None, snapshot_root=tmp_path / 'snapshot',
            export_root=tmp_path / 'c4-export', run_root=tmp_path / 'c4-run', provider=acp,
            audit_verifier=None, source_verifier=None, corpus_verifier=None, retrieval_provider=None,
            scorer_factory=None, execution_authority=None, scorer_authority_keys={})
    assert not acp_calls
