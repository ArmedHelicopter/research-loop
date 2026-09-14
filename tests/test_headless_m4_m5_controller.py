"""Headless M4/M5 factorial uses synthetic model/account peers and real Docker/RPC."""
from contextlib import ExitStack
from pathlib import Path

import pytest

from research_loop.modular import combination_train_controller as controller
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError
from tests.helpers.headless_train_provider import headless_train_provider
from test_combination_prospective_train_source import prepare,processes
from test_m4_m5_useful_controls import RECIPE


def setup_headless(root,patch):
    setup=prepare(root,'m4');body=setup['config'].data()
    provider={'kind':'grok-headless-public-train-v1','model':'grok-4.6',
        'opportunity_contract':'public-train-main-and-initial-title-v1','included_only':True,
        'api_key_route_permitted':False,'main_calls':40,'possible_initial_title_calls':40,
        'main_output_caps':{'m4_plan':2048,'m5_mechanism':2048,'m5_measurement':2048,'analysis_program':8192,'final_answer':2048},
        'input_byte_cap_per_request':262144,'observed_main_token_cap':131072,'title_requested_output_cap':100,
        'wall_timeout_seconds':60,'max_retries':0,'title_usage_and_all_call_totals':'unknown',
        'account_read_recovery':{'schema':'headless-account-read-recovery-v1','max_attempts':2}}
    body.update(schema='m4-m5-train-controller-config-v5',execution_recipe=RECIPE,provider=provider,
        model='grok-4.6',effort='low',max_tokens=131072*40,timeout_seconds=60)
    setup['config']=controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    setup['compiled']=controller.compile_m4_m5_train_panel(setup['config'],setup['packets'])
    ordinary=setup['module']._model([])
    def response(request):
        b=request.data()
        assert 'PRIVATE-REFERENCE-SENTINEL' not in request.encoded
        if b['slot']=='final_answer':
            assert b['execution_feedback'][0]['status']=='succeeded'
            return {'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
                'evidence_ids':[],'conclusion':'Observed public output: '+b['execution_feedback'][0]['stdout'],
                'programme_complete':False}
        return ordinary(request)
    backend,calls,gets=headless_train_provider(root/'port',patch,schemas=body['schemas'],max_calls=40,response=response,wrapped=False)
    return setup,backend,calls,gets


@pytest.mark.parametrize('drift',[False,True])
def test_complete_headless_factorial_or_retained_final_drift(tmp_path,monkeypatch,drift):
    setup,backend,calls,gets=setup_headless(tmp_path,monkeypatch)
    with ExitStack() as stack:
        service=processes(setup,stack)
        scored=[];original=service.score_combination
        def score(**kwargs):
            result=original(**kwargs);scored.append(result)
            if drift and len(scored)==8:
                (backend.calls_root/'0001-m4_plan/response.private.json').write_bytes(b'{"foreign":true}')
            return result
        monkeypatch.setattr(service,'score_combination',score)
        result=controller.run_m4_m5_train_panel(setup['config'],custody=None,prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']),export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run',model=backend,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            execution_authority=setup['module'].EXECUTION,scoring_service=service,
            scorer_authority_keys={setup['module'].SCORER.authority_id:setup['module'].SCORER.key})
    receipt=result.receipt.data()
    assert len(calls)==40 and len(gets)==240 and len(result.attempts)==len(result.scores)==8
    assert receipt['validation_opened'] is False and receipt['pruned_cells']==[]
    assert receipt['status']==('inconclusive' if drift else 'estimated')
    assert receipt['eligible_scored_cells']==(0 if drift else 8)
    assert receipt['native_final_verification']['score_eligible'] is (not drift)
    assert backend.ledger['known_main_tokens']==400
    assert all(row['known_headless_main_usage']['total_tokens']==10 for row in backend.ledger['calls'])
    if not drift:
        assert all(row.data()['status']=='succeeded' for row in result.attempts)
        controller._replay_native_model(backend)


def test_headless_factorial_rejects_acp_relabel_before_dispatch(tmp_path,monkeypatch):
    setup,backend,calls,gets=setup_headless(tmp_path,monkeypatch)
    body=setup['config'].data();body['schema']='m4-m5-train-controller-config-v4'
    with pytest.raises(ContractError):controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    assert not calls and not gets


def test_existing_acp_subclass_preflight_is_preserved(tmp_path,monkeypatch):
    from test_grok_train_solver import default_port
    from research_loop.modular.grok_train_solver import GrokTrainModelPort
    setup,_,calls,gets=setup_headless(tmp_path,monkeypatch)
    body=setup['config'].data();body.update(schema='m4-m5-train-controller-config-v4',effort='native_acp')
    body['provider']['kind']='grok-acp-public-train-v1';body['provider'].pop('account_read_recovery')
    config=controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body));setup['config']=config
    port,logs=default_port(tmp_path/'acp',monkeypatch,schemas=body['schemas'],caps=body['provider']['main_output_caps'],max_calls=40)
    class ExistingACPSubclass(GrokTrainModelPort):pass
    port.__class__=ExistingACPSubclass
    with ExitStack() as stack:
        service=processes(setup,stack)
        controller._service_preflight(config,port,service,setup['module'].EXECUTION,
            {setup['module'].SCORER.authority_id:setup['module'].SCORER.key})
    assert controller._native_model(port) and not calls and not gets and not logs
