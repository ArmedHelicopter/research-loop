import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import AcpResult
from research_loop.modular.grok_train_solver import GrokTrainModelPort, replay_grok_train_ledger
from research_loop.ontology import ContractError


SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
REQUEST = FrozenRecord.from_dict({'schema':'public-model-request-v1','task':{},'lock_digest':'a'*64,'objective':{},'slot':'m4_plan','instruction':'public','context':{},'module_context':{},'execution_feedback':[]})

def test_public_train_ledger_preserves_native_identity_and_closes_unknown_usage(tmp_path):
    seen=[]
    def native(**kwargs):
        seen.append(kwargs)
        reservation=Path(kwargs['reservation']); reservation.write_text('{"native":true}', encoding='utf-8')
        receipt=FrozenRecord.from_dict({'accepted':True,'known_usage':{'totalTokens':7},'opportunity_contract':kwargs['opportunity_contract'],
            'prompt_id':'p','session_id':'s','initial_title_usage':None,'total_tokens_all_opportunities':None})
        return AcpResult(receipt, FrozenRecord.from_dict({'ok':True}))
    (tmp_path/'grok.exe').write_bytes(b'fixture')
    port=GrokTrainModelPort(executable=tmp_path/'grok.exe', work_root=tmp_path/'ledger', private_home=tmp_path/'home', private_profile=tmp_path/'profile', public_cwd=tmp_path,
        frozen_files={'x':'0'*64},max_calls=1,schemas={'m4_plan':SCHEMA},slot_output_caps={'m4_plan':2048},slot_input_byte_caps={'m4_plan':262144},observed_main_token_cap=131072,native_invoke=native)
    assert port(REQUEST).data()=={'ok':True}; replay_grok_train_ledger(port)
    assert seen[0]['opportunity_contract']=='public-train-main-and-initial-title-v1'
    assert port.ledger['calls'][0]['possible_initial_title_opportunity']==1
    assert port.ledger['tokens']==7 and port.ledger['usage_incomplete'] is False

    def unknown(**kwargs):
        Path(kwargs['reservation']).write_text('{}', encoding='utf-8')
        return AcpResult(FrozenRecord.from_dict({'accepted':False,'known_usage':None}), None)
    second=GrokTrainModelPort(executable=tmp_path/'grok.exe', work_root=tmp_path/'closed', private_home=tmp_path/'home', private_profile=tmp_path/'profile', public_cwd=tmp_path,
        frozen_files={'x':'0'*64},max_calls=1,schemas={'m4_plan':SCHEMA},slot_output_caps={'m4_plan':2048},slot_input_byte_caps={'m4_plan':262144},observed_main_token_cap=131072,native_invoke=unknown)
    with pytest.raises(ContractError): second(REQUEST)
    assert second.ledger['usage_incomplete'] is True
