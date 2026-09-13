"""Real subprocess scoring and controller wiring on public synthetic tasks."""
import hashlib
import json
import os

import pytest

from evaluation.modular.scorer_process import (CombinationScorerProcessClient, serialize_combination_panel,
    parse_combination_panel, parse_server_config, build_service)
from research_loop.modular.combination_train_controller import FrozenM4M5TrainConfig, compile_m4_m5_train_panel, run_m4_m5_train_panel
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError, canonical
from test_modular_combination_train_controller import _fixture, _model, EXECUTION, SCORER, SCHEMAS
from test_modular_train_controller import model_port
from test_scorer_process import _store, _command


def fixture(root):
    snapshot, custody, packets, original, rubric, _ = _fixture(root)
    store, handles, manifest_sha = _store(root, {'tasks':{p.task.content_hash:p.task for p in packets}})
    body = original.data(); body['scorer_handle_bindings'] = {k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()}
    config = FrozenM4M5TrainConfig(FrozenRecord.from_dict(body))
    compiled = compile_m4_m5_train_panel(config, packets)
    (root/'execution.key').write_bytes(EXECUTION.key); (root/'score.key').write_bytes(SCORER.key)
    server = {'schema':'combination-scorer-process-config-v1','panel':serialize_combination_panel(compiled.panel),
        'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
        'train_reference_store':{'root':str(store.resolve()),'manifest_sha256':manifest_sha,
            'inventory_digest':packets[0].task.identity.dataset_version,'split_digest':compiled.panel.split_digest},
        'task_handles':handles,'execution_authority_key_files':{EXECUTION.authority_id:str((root/'execution.key').resolve())},
        'scorer_authority':{'id':SCORER.authority_id,'key_file':str((root/'score.key').resolve())},'evaluator':{}}
    path=root/'server.json';path.write_text(canonical(server),encoding='utf-8')
    args=dict(panel=compiled.panel,config=rubric,command=_command(path,root/'worker.jsonl'),journal_path=root/'client.jsonl',
        task_handle_bindings=body['scorer_handle_bindings'],execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
        scorer_authority_keys={SCORER.authority_id:SCORER.key},environment={**os.environ,'PYTHONIOENCODING':'gbk'})
    return snapshot,custody,config,compiled,args,server


@pytest.mark.parametrize('flags', [
    {'lineage': True, 'retrieval_review': True},
    {'lineage': 1, 'retrieval_review': False},
    {'lineage': False, 'retrieval_review': 1},
    {'lineage': 'false', 'retrieval_review': False},
])
def test_merged_combination_scopes_cannot_be_mixed_or_coerced(tmp_path, flags):
    _, _, _, compiled, _, _ = fixture(tmp_path)
    envelope = serialize_combination_panel(compiled.panel)
    with pytest.raises(ContractError, match='one strict explicit scope'):
        serialize_combination_panel(compiled.panel, **flags)
    with pytest.raises(ContractError, match='one strict explicit scope'):
        parse_combination_panel(envelope, **flags)
    assert not (tmp_path / 'worker.jsonl').exists()
    assert not (tmp_path / 'client.jsonl').exists()


def test_full_eight_cell_custody_controller_uses_real_separate_scorer_with_utf8(tmp_path,monkeypatch):
    snapshot,custody,config,compiled,args,server=fixture(tmp_path)
    seen=[];ordinary=_model(seen)
    def model(request):
        result=ordinary(request)
        if request.data()['slot']=='final_answer':
            result=FrozenRecord.from_dict({**result.data(),'conclusion':result.data()['conclusion']+' 中文：均值 α。'})
        return result
    port=model_port(tmp_path/'port',monkeypatch,max_calls=40,schemas=SCHEMAS,response_factory=model)
    service=CombinationScorerProcessClient(**args)
    try:
        assert not (tmp_path/'worker.jsonl').exists() # configuration handshake performs no score
        result=run_m4_m5_train_panel(config,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',
            run_root=tmp_path/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),
            execution_authority=EXECUTION,scoring_service=service,scorer_authority_keys={SCORER.authority_id:SCORER.key})
        assert len(result.scores)==8 and len(seen)==40
        assert result.receipt.data()['status']=='estimated'
        assert result.receipt.data()['pruned_cells']==[]
        assert result.receipt.data()['scientific_effectiveness_proven'] is False
        first=result.attempts[0].data()
        assert service.score_combination(panel=compiled.panel,cell=compiled.panel.cells[0],
            score_input=FrozenRecord.from_dict(first['score_input']))==result.scores[0]
        before=(tmp_path/'worker.jsonl').read_bytes()
        changed=first['score_input'];changed['body']['candidate']['answer']='changed after score'
        with pytest.raises(ContractError,match='differs'):
            service.score_combination(panel=compiled.panel,cell=compiled.panel.cells[0],score_input=FrozenRecord.from_dict(changed))
        assert (tmp_path/'worker.jsonl').read_bytes()==before
    finally:service.close()
    for name in ('client.jsonl','worker.jsonl'):
        text=(tmp_path/name).read_text(encoding='utf-8')
        assert 'PRIVATE-REFERENCE-SENTINEL' not in text
        rows=[json.loads(line) for line in text.splitlines()]
        assert len(rows)==16 and [r['status'] for r in rows]==['reserved','succeeded']*8


@pytest.mark.parametrize('fault',['authority','handle','rubric'])
def test_startup_mismatch_fails_before_any_scoring_reservation(tmp_path,fault):
    _,_,_,_,args,_=fixture(tmp_path)
    if fault=='authority':args['scorer_authority_keys']={SCORER.authority_id:b'z'*32}
    elif fault=='handle':args['task_handle_bindings']={k:'f'*64 for k in args['task_handle_bindings']}
    else:
        from evaluation.modular.scoring_service import ScorerConfig
        args['config']=ScorerConfig.create(benchmark='core_pair',evaluator_id='other',version='v1',
            rubric_digest=args['config'].record.data()['rubric_digest'])
    with pytest.raises(ContractError,match='startup binding'):
        CombinationScorerProcessClient(**args)
    assert not (tmp_path/'worker.jsonl').exists() and not (tmp_path/'client.jsonl').exists()


@pytest.mark.parametrize('fault',['panel_digest','cell_extra','validation','obligation','scorer_digest','handles'])
def test_full_panel_and_store_contract_refuses_drift_before_evaluator(tmp_path,fault):
    _,_,_,compiled,_,server=fixture(tmp_path)
    assert parse_combination_panel(serialize_combination_panel(compiled.panel))==compiled.panel
    if fault=='panel_digest':server['panel']['panel_digest']='0'*64
    elif fault=='cell_extra':server['panel']['panel']['cells'][0]['extra']=True
    elif fault=='validation':server['panel']['panel']['domain']='validation'
    elif fault=='obligation':server['panel']['panel']['obligation_id']='pair:M1+M2'
    elif fault=='scorer_digest':server['scorer_config_digest']='0'*64
    else:server['task_handles']={k:'f'*64 for k in server['task_handles']}
    calls=[]
    def forbidden(request):calls.append(request);raise AssertionError('evaluator must not be called')
    with pytest.raises(ContractError):build_service(parse_server_config(server),evaluator=forbidden)
    assert not calls
