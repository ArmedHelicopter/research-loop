import json
import os
from pathlib import Path
import sys

import research_loop.modular.grok_acp_transport as transport

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import AcpResult
from research_loop.modular.grok_acp_transport import SinglePromptACP, TRAIN_OPPORTUNITY_CONTRACT, digest
from research_loop.modular.grok_train_solver import GrokTrainModelPort, replay_grok_train_ledger
from research_loop.ontology import ContractError, canonical


SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
REQUEST = FrozenRecord.from_dict({'schema':'public-model-request-v1','task':{},'lock_digest':'a'*64,'objective':{},'slot':'m4_plan','instruction':'public','context':{},'module_context':{},'execution_feedback':[]})

def test_invented_native_receipt_closes_ledger(tmp_path):
    """A fabricated accepted-shaped mapping can never become a provider peer."""
    def native(**kwargs):
        Path(kwargs['reservation']).write_text('{"native":true}', encoding='utf-8')
        return AcpResult(FrozenRecord.from_dict({'accepted':True,'known_usage':{'totalTokens':7}}), FrozenRecord.from_dict({'ok':True}))
    (tmp_path/'grok.exe').write_bytes(b'fixture')
    (tmp_path/'home').mkdir(); (tmp_path/'home/auth.json').write_text('{}')
    port=GrokTrainModelPort(executable=tmp_path/'grok.exe', work_root=tmp_path/'ledger', private_home=tmp_path/'home', private_profile=tmp_path/'profile', public_cwd=tmp_path,
        frozen_files={str(tmp_path/'grok.exe'):digest((tmp_path/'grok.exe').read_bytes())},max_calls=1,schemas={'m4_plan':SCHEMA},slot_output_caps={'m4_plan':2048},slot_input_byte_caps={'m4_plan':262144},observed_main_token_cap=131072,native_invoke=native)
    with pytest.raises(ContractError): port(REQUEST)
    assert port.ledger['usage_incomplete'] is True


@pytest.mark.parametrize('fault', [None, 'unknown_main', 'provenance'])
def test_v4_full_useful_eight_cell_native_peer_docker_and_independent_scorer(tmp_path, monkeypatch, fault):
    """All 40 public slots use an ACP peer; Docker and rubric stay real seams."""
    from contextlib import ExitStack
    from evaluation.modular.scoring_service import ScorerConfig
    from research_loop.modular import combination_train_controller as controller
    from research_loop.modular.runtime import AuditVerifier
    from test_combination_prospective_train_source import prepare, processes
    from test_m4_m5_useful_controls import RECIPE

    setup = prepare(tmp_path, 'm4')
    body = setup['config'].data()
    provider = {'kind':'grok-acp-public-train-v1','model':'grok-4.6','opportunity_contract':'public-train-main-and-initial-title-v1',
        'included_only':True,'api_key_route_permitted':False,'main_calls':40,'possible_initial_title_calls':40,
        'main_output_caps':{'m4_plan':2048,'m5_mechanism':2048,'m5_measurement':2048,'analysis_program':8192,'final_answer':2048},
        'input_byte_cap_per_request':262144,'observed_main_token_cap':131072,'title_requested_output_cap':100,
        'wall_timeout_seconds':60,'max_retries':0,'title_usage_and_all_call_totals':'unknown'}
    body.update(schema='m4-m5-train-controller-config-v4', execution_recipe=RECIPE, provider=provider,
        model='grok-4.6', effort='native_acp', max_tokens=131072*40, timeout_seconds=60)
    config = controller.FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    setup['config'] = config
    setup['compiled'] = controller.compile_m4_m5_train_panel(config, setup['packets'])
    assert len(setup['compiled'].panel.cells) == 8
    port, logs = default_port(tmp_path, monkeypatch, schemas=body['schemas'],
        caps=provider['main_output_caps'], max_calls=40,
        scenario='train_unknown_main' if fault=='unknown_main' else 'train_panel')
    if fault=='provenance':
        verify=controller.verify_m4_m5_combination_benchmark_cell
        def drift(*args, **kwargs):
            result=verify(*args, **kwargs)
            (port.calls_root/'0001-m4_plan/response.private.json').write_text('{"foreign":true}')
            return result
        monkeypatch.setattr(controller,'verify_m4_m5_combination_benchmark_cell',drift)
    with ExitStack() as stack:
        service=processes(setup, stack)
        result=controller.run_m4_m5_train_panel(config, custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run-v4', model=port, audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            execution_authority=setup['module'].EXECUTION, scoring_service=service,
            scorer_authority_keys={setup['module'].SCORER.authority_id:setup['module'].SCORER.key})
    if fault:
        assert result.receipt.data()['status']=='inconclusive'
        assert len(result.attempts)==8 and len(result.scores)==0
        assert len(logs)==len(port.ledger['calls'])==(1 if fault=='unknown_main' else 5)
        assert port.ledger['tokens']==(12 if fault=='unknown_main' else 60)
        assert port.ledger['usage_incomplete'] is True
        assert all(row.data()['status']=='blocked' and row.data()['reason']=='prior_model_usage_incomplete' for row in result.attempts[1:])
        assert json.loads((tmp_path/'run-v4/controller-attempt.json').read_text())['actual_scorer_calls']==0
        return
    assert result.receipt.data()['status']=='estimated'
    assert len(result.attempts)==len(result.scores)==8
    assert len(logs)==len(port.ledger['calls'])==40
    assert {row['slot'] for row in port.ledger['calls']} == set(provider['main_output_caps'])
    assert all(row['accepted'] and row['possible_initial_title_opportunity']==1 for row in port.ledger['calls'])
    assert all(json.loads(log.read_text().splitlines()[1])['method']=='session/new' for log in logs)
    assert all(row.data()['status']=='succeeded' for row in result.attempts)
    assert len({row['public_cwd'] for row in port.ledger['calls']})==40
    assert {Path(row['config_path']).read_text() for row in port.ledger['calls']}=={transport.diagnostic_config(2048),transport.diagnostic_config(8192)}
    replay_grok_train_ledger(port)


def default_port(root, monkeypatch, *, schemas=None, caps=None, max_calls=3, scenario='ok'):
    """Patch only executable identity and OS spawn; exercise default native entry."""
    root.mkdir(parents=True,exist_ok=True)
    exe=root/'synthetic-grok.exe';exe.write_bytes(b'fixture executable; never launched')
    home=root/'approved-login';home.mkdir();(home/'auth.json').write_text('{}')
    peer=(Path(__file__).parent/'fixtures/grok_acp_peer.py').resolve();logs=[]
    original=transport.ProcessTree
    def process_tree(command,cwd,env,stderr):
        assert list(command)==[str(exe.resolve()),'--no-auto-update','--cwd',str(cwd),'agent','stdio']
        assert set(Path(env['GROK_HOME']).iterdir())=={Path(env['GROK_HOME'])/'auth.json',Path(env['GROK_HOME'])/'config.toml'}
        assert not any(Path(cwd).iterdir())
        assert 'XAI_API_KEY' not in env and 'GROK_API_KEY' not in env
        log=Path(env['GROK_HOME']).parent/'peer.jsonl';logs.append(log)
        return original([sys.executable,str(peer),scenario,str(log)],cwd,env,stderr)
    monkeypatch.setattr(transport,'EXECUTABLE_SHA256',digest(exe.read_bytes()))
    monkeypatch.setattr(transport,'ProcessTree',process_tree)
    sources={str(peer):digest(peer.read_bytes())}
    return GrokTrainModelPort(executable=exe,work_root=root/'native-ledger',private_home=home,
        private_profile=root/'profiles',public_cwd=root/'public-contexts',frozen_files=sources,
        max_calls=max_calls,schemas=schemas or {'m4_plan':SCHEMA},slot_output_caps=caps or {'m4_plan':2048},
        slot_input_byte_caps={slot:262144 for slot in (schemas or {'m4_plan':SCHEMA})},observed_main_token_cap=131072),logs


@pytest.mark.parametrize('substitution',['wire','coherent_wire','reservation','response','config','observer_billing'])
def test_native_original_substitution_closes_before_later_io(tmp_path,monkeypatch,substitution):
    port,logs=default_port(tmp_path,monkeypatch);port(REQUEST)
    row=port.ledger['calls'][0];call=port.calls_root/'0001-m4_plan';native=call/'native-private'
    if substitution in ('wire','coherent_wire'):
        wire=native/'requests.private.jsonl'; rows=[json.loads(x) for x in wire.read_text().splitlines()]
        rows[4]['params']['prompt'][0]['text']='valid but foreign prompt'
        wire.write_text('\n'.join(canonical(r) for r in rows)+'\n')
        if substitution=='coherent_wire':
            rec=json.loads((call/'observer-receipt.private.json').read_text())
            rec['public_train_binding']['request_stream_sha256']=digest(wire.read_bytes())
            for path in (call/'observer-receipt.private.json',native/'observer-receipt.json'):path.write_text(canonical(rec))
            row['native_receipt_sha256']=digest((call/'observer-receipt.private.json').read_bytes())
    elif substitution=='reservation':
        path=Path(row['reservation_path']);r=json.loads(path.read_text());r['prompt_sha256']='0'*64
        path.write_text(canonical(r));row['reservation_sha256']=digest(path.read_bytes())
    elif substitution=='response':
        (call/'response.private.json').write_text('{"ok":false}')
    elif substitution=='config':
        Path(row['config_path']).write_text(transport.diagnostic_config(8192))
    else:
        rec=json.loads((call/'observer-receipt.private.json').read_text());rec['billing_after']['prepaid_balance']=1
        for path in (call/'observer-receipt.private.json',native/'observer-receipt.json'):path.write_text(canonical(rec))
        row['native_receipt_sha256']=digest((call/'observer-receipt.private.json').read_bytes())
    port.ledger_path.write_text(canonical(port.ledger))
    with pytest.raises(ContractError):port(REQUEST)
    assert len(logs)==1 and port.ledger['tokens']==12 and port.ledger['usage_incomplete'] is True
    assert json.loads(port.ledger_path.read_text())['usage_incomplete'] is True


def test_unknown_reserved_opportunity_stays_closed_after_restart(tmp_path,monkeypatch):
    port,logs=default_port(tmp_path,monkeypatch);port(REQUEST)
    port.ledger['calls'][0]['status']='reserved';port.ledger_path.write_text(canonical(port.ledger))
    with pytest.raises(ContractError):replay_grok_train_ledger(port)
    with pytest.raises(ContractError):port(REQUEST)
    assert len(logs)==1 and port.ledger['tokens']==12
