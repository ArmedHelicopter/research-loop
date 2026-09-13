import json
import os
from pathlib import Path
import sys

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import AcpResult
from research_loop.modular.grok_acp_transport import SinglePromptACP, TRAIN_OPPORTUNITY_CONTRACT, digest
from research_loop.modular.grok_train_solver import GrokTrainModelPort, replay_grok_train_ledger
from research_loop.ontology import ContractError


SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
REQUEST = FrozenRecord.from_dict({'schema':'public-model-request-v1','task':{},'lock_digest':'a'*64,'objective':{},'slot':'m4_plan','instruction':'public','context':{},'module_context':{},'execution_feedback':[]})

def test_invented_native_receipt_closes_ledger(tmp_path):
    """A fabricated accepted-shaped mapping can never become a provider peer."""
    def native(**kwargs):
        Path(kwargs['reservation']).write_text('{"native":true}', encoding='utf-8')
        return AcpResult(FrozenRecord.from_dict({'accepted':True,'known_usage':{'totalTokens':7}}), FrozenRecord.from_dict({'ok':True}))
    (tmp_path/'grok.exe').write_bytes(b'fixture')
    port=GrokTrainModelPort(executable=tmp_path/'grok.exe', work_root=tmp_path/'ledger', private_home=tmp_path/'home', private_profile=tmp_path/'profile', public_cwd=tmp_path,
        frozen_files={'x':'0'*64},max_calls=1,schemas={'m4_plan':SCHEMA},slot_output_caps={'m4_plan':2048},slot_input_byte_caps={'m4_plan':262144},observed_main_token_cap=131072,native_invoke=native)
    with pytest.raises(ContractError): port(REQUEST)
    assert port.ledger['usage_incomplete'] is True


def test_v4_full_useful_eight_cell_native_peer_docker_and_independent_scorer(tmp_path):
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
    peer = Path(__file__).parent/'fixtures'/'grok_acp_peer.py'; logs=[]
    def native(**kwargs):
        log = Path(kwargs['private_dir']).parent/'peer.jsonl'; logs.append(log)
        client = SinglePromptACP([sys.executable, str(peer), 'train_panel', str(log)], cwd=tmp_path,
            env=dict(os.environ), private_dir=kwargs['private_dir'], reservation=kwargs['reservation'],
            frozen_files=kwargs['frozen_files'], timeout=60, main_output_cap=kwargs['main_output_cap'],
            max_total_tokens=kwargs['observed_main_token_cap'], opportunity_contract=TRAIN_OPPORTUNITY_CONTRACT,
            input_byte_cap=kwargs['input_byte_cap'])
        return client.invoke(kwargs['prompt'], kwargs['schema'])
    exe=tmp_path/'synthetic-grok.exe'; exe.write_bytes(b'fixture')
    port=GrokTrainModelPort(executable=exe, work_root=tmp_path/'native-ledger', private_home=tmp_path/'home',
        private_profile=tmp_path/'profile', public_cwd=tmp_path, frozen_files={str(peer):digest(peer.read_bytes())},
        max_calls=40, schemas=body['schemas'], slot_output_caps=provider['main_output_caps'],
        slot_input_byte_caps={slot:262144 for slot in provider['main_output_caps']}, observed_main_token_cap=131072,
        native_invoke=native)
    with ExitStack() as stack:
        service=processes(setup, stack)
        result=controller.run_m4_m5_train_panel(config, custody=None, prospective_exporter=setup['exporter'],
            snapshot_root=Path(setup['exporter'].config['snapshot_root']), export_root=setup['exporter'].output_root,
            run_root=tmp_path/'run-v4', model=port, audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            execution_authority=setup['module'].EXECUTION, scoring_service=service,
            scorer_authority_keys={setup['module'].SCORER.authority_id:setup['module'].SCORER.key})
    assert result.receipt.data()['status']=='estimated'
    assert len(result.attempts)==len(result.scores)==8
    assert len(logs)==len(port.ledger['calls'])==40
    assert {row['slot'] for row in port.ledger['calls']} == set(provider['main_output_caps'])
    assert all(row['accepted'] and row['possible_initial_title_opportunity']==1 for row in port.ledger['calls'])
    assert all(json.loads(log.read_text().splitlines()[1])['method']=='session/new' for log in logs)
    assert all(row.data()['status']=='succeeded' for row in result.attempts)
    replay_grok_train_ledger(port)
