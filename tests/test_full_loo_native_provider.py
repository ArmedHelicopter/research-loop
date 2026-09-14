"""Native C4 provider integration: synthetic ACP peer, real C4 engine seams.

The peer replaces only operating-system spawn.  Every one of the 169 model
opportunities crosses ``run_native_train`` and the closed Grok provider; the
restricted builder, Docker broker and independent scorer process are the
ordinary C4 implementations.
"""
from contextlib import ExitStack
from pathlib import Path
import json

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_modules import model_schemas
from research_loop.modular.full_loo_native_provider import (FrozenNativeFullLooRuntimePlan,
    run_native_full_loo_train, verify_native_full_loo_cell)
from research_loop.modular.phase_provider import provider_configuration
from research_loop.modular.train_provider import wrap_train_provider
from research_loop.ontology import ContractError

from test_full_loo_runtime import AUDIT, EXECUTION, SCORER, prepare, service
from test_grok_train_solver import default_port
from test_state_retrieval_combination_driver import Provider


def native_setup(root, patch, *, scenario='train_c4'):
    # The inherited desktop profile can carry unrelated MCP configuration;
    # C4's existing reviewed-Codex fixture must see only its explicit fixture
    # source when assembling the frozen legacy plan.
    appdata=root/'isolated-appdata'; appdata.mkdir(parents=True,exist_ok=True)
    patch.setenv('APPDATA',str(appdata)); patch.setenv('LOCALAPPDATA',str(appdata))
    setup = prepare(root, patch)
    caps = {slot: 8192 if slot == 'analysis_program' else 2048 for slot in model_schemas()}
    backend, logs = default_port(root / 'native', patch, schemas=model_schemas(), caps=caps, max_calls=169, scenario=scenario)
    provider = wrap_train_provider(backend)
    body = {'schema':'c4-full-loo-native-provider-plan-v2', 'legacy_plan_digest':setup['plan'].record.content_hash,
        'provider_configuration':provider_configuration(provider).data(), 'provider_scope_schema':'train-phase-provider-ledger-v2'}
    setup.update(native_plan=FrozenNativeFullLooRuntimePlan(FrozenRecord.from_dict(body), setup['plan']), native_provider=provider,
        native_backend=backend, native_logs=logs)
    return setup


def invoke(setup, patch, *, fault=None):
    with ExitStack() as stack:
        exporter=setup['exporter']
        return run_native_full_loo_train(setup['native_plan'], prospective_exporter=exporter,
            snapshot_root=Path(exporter.config['snapshot_root']), export_root=exporter.output_root, run_root=setup['root']/'native-run',
            provider=setup['native_provider'], audit_verifier=AUDIT, source_verifier=setup['source'], corpus_verifier=setup['corpus'],
            retrieval_provider=Provider(setup['retrieval_calls']), scorer_factory=lambda panel:service(setup, stack, panel, fault),
            execution_authority=EXECUTION, scorer_authority_keys={SCORER.authority_id:SCORER.key})


@pytest.fixture(scope='module')
def native_grid(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        setup=native_setup(tmp_path_factory.mktemp('native-c4'), patch); run=invoke(setup, patch)
    return setup, run


def test_complete_native_c4_grid_uses_scoped_grok_main_and_engine_seams(native_grid):
    setup, run = native_grid; receipt=run.receipt.data(); ledger=run.ledger
    assert receipt['status']=='complete_train_engineering'
    assert receipt['actual']=={'model_calls':169,'builder_executions':9,'independent_source_qualification_calls':62,
        'corpus_qualification_calls':58,'retrieval_requests':87,'auxiliary_docker_attempts':58,'solver_docker_attempts':22,
        'docker_attempts':80,'scorer_calls':22}
    assert len(run.builds)==9 and len(run.results)==len(run.scores)==22 and len(receipt['structural'])==2
    assert receipt['native_accounting']['known_usage_scope']=='native_main'
    assert receipt['native_accounting']['provider_calls']==169
    assert receipt['native_accounting']['possible_initial_title_opportunities']==169
    assert receipt['native_accounting']['title_tokens'] is None and receipt['native_accounting']['all_opportunity_tokens'] is None
    scopes=ledger.record.data()['scopes']['scopes']; ids=[number for scope in scopes for number in scope['call_ids']]
    assert len(scopes)==31 and ids==list(range(1,170)) and len(set(ids))==169
    assert all(row['accepted'] and row['main_opportunity']==1 and row['possible_initial_title_opportunity']==1 for row in setup['native_backend'].ledger['calls'])
    assert len(set(row['public_cwd'] for row in setup['native_backend'].ledger['calls']))==169
    assert len(setup['native_logs'])==169 and all(json.loads(log.read_text().splitlines()[1])['method']=='session/new' for log in setup['native_logs'])
    assert run.barrier.package(next(r for r in setup['native_plan'].composition.data()['cells'] if r['id']=='full')) == run.barrier.package(next(r for r in setup['native_plan'].composition.data()['cells'] if r['id']=='without-M8'))
    assert run.barrier.package(next(r for r in setup['native_plan'].composition.data()['cells'] if r['id']=='B0')) == run.barrier.package(next(r for r in setup['native_plan'].composition.data()['cells'] if r['id']=='ordinary-control'))
    for result in run.results: verify_native_full_loo_cell(result, barrier=run.barrier, panel=run.panel, ledger=ledger)


def test_unknown_main_preserves_failed_prefix_and_blocks_full_target_denominator(tmp_path, monkeypatch):
    setup=native_setup(tmp_path, monkeypatch, scenario='train_unknown_main'); run=invoke(setup, monkeypatch)
    receipt=run.receipt.data(); accounting=receipt['native_accounting']
    assert receipt['status']=='inconclusive' and len(receipt['targets'])==22 and len(receipt['structural'])==2
    assert len(setup['native_backend'].ledger['calls'])==1 and setup['native_backend'].ledger['usage_incomplete'] is True
    assert accounting['schema']=='train-phase-terminal-accounting-v2'
    assert accounting['provider_calls_lower_bound']==1 and accounting['known_reported_tokens_lower_bound']==12
    assert accounting['unknown_unobserved_opportunities'] is True and accounting['title_tokens'] is None
    assert all(row['status']=='blocked' for row in receipt['targets']) and not run.scores


def test_target_seal_rejects_original_provenance_substitution(native_grid):
    setup, run=native_grid; result=run.results[-1]
    path=setup['native_backend'].calls_root/'0169-final_answer'/'response.private.json'; original=path.read_bytes()
    try:
        path.write_text('{"objective_digest":"foreign","outcome":"unknown","evidence_ids":[],"conclusion":"foreign","programme_complete":false}',encoding='utf-8')
        with pytest.raises(ContractError):
            verify_native_full_loo_cell(result, barrier=run.barrier, panel=run.panel, ledger=run.ledger)
    finally:
        path.write_bytes(original)


def test_mid_target_provenance_drift_aborts_without_later_calls_or_scores(tmp_path, monkeypatch):
    """A replay fault is terminal accounting, never a synthetic eligible seal."""
    import research_loop.modular.full_loo_native_provider as native
    setup=native_setup(tmp_path, monkeypatch); original=native.run_stage; changed=False
    def drift(**kwargs):
        nonlocal changed
        result=original(**kwargs)
        if kwargs['stage']=='target' and not changed:
            changed=True; number=len(setup['native_backend'].ledger['calls'])
            response=setup['native_backend'].calls_root/f'{number:04d}-final_answer'/'response.private.json'
            response.write_text('{"objective_digest":"foreign","outcome":"unknown","evidence_ids":[],"conclusion":"foreign","programme_complete":false}',encoding='utf-8')
        return result
    monkeypatch.setattr(native,'run_stage',drift)
    run=invoke(setup,monkeypatch); receipt=run.receipt.data(); accounting=receipt['native_accounting']
    assert changed and receipt['status']=='inconclusive' and not run.scores
    assert receipt['target_provider_ledger_kind']=='PhaseProviderAbort' and receipt['final_provider_eligible'] is False
    assert len(receipt['targets'])==22 and all(row['status'] in {'failed','blocked'} for row in receipt['targets'])
    assert accounting['schema']=='train-phase-terminal-accounting-v2'
    assert accounting['provider_calls_lower_bound']==51 and accounting['unknown_unobserved_opportunities'] is True
