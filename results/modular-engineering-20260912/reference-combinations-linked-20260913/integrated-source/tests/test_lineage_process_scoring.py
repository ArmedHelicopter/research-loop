"""Synthetic references only; real child processes and actual protected model port."""
from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
from test_evaluator_model_port import _probe


def test_lineage_mode_has_separate_frozen_schema(tmp_path):
    port = CodexEvaluatorModelPort('codex', tmp_path/'port', evaluator_id='fixture',
        evaluator_version='v2', max_calls=1, max_tokens=20, rubric_mode='lineage_v1',
        process_runner=lambda *a, **k: None, context_probe_runner=_probe, allow_mock_context=True)
    assert 'lineage_endpoints' in port.schemas['frozen-rubric.discoverybench']['properties']


import hashlib
import json
import os
from pathlib import Path
import sys
import pytest
from evaluation.modular.lineage_rubric import FrozenLineageRubricEndpoint, FrozenLineageReferenceResolver, ENDPOINTS
from evaluation.modular.lineage_scorer_process import LineageScorerProcessClient, LineageScorerProcessPool
from evaluation.modular.scorer_process import serialize_combination_panel
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.lineage_combination_controller import FrozenLineageTrainConfig, compile_lineage_train_panels, run_lineage_train_panels
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import canonical, digest, ContractError
from test_lineage_combination_controller import _fixture, _sources, _model, EXECUTION, SCORER, SCHEMAS
from test_modular_train_controller import model_port
from test_scorer_process import _store


def _write(root, name, value):
    raw=canonical(value).encode('utf-8'); (root/name).write_bytes(raw)
    return {'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'byte_count':len(raw)}


def fixture(root):
    root.mkdir(parents=True,exist_ok=True)
    sources=_sources([])
    snapshot,custody,packets,old,_,_= _fixture(root,sources)
    primary,handles,primary_sha=_store(root,{'tasks':{p.task.content_hash:p.task for p in packets}})
    store=root/'lineage-references';store.mkdir()
    rows=[];bindings={};subjects={}
    for p in packets:
        task=p.task;identity=task.identity.data();key=digest(identity);name=task.identity.benchmark
        material_digest=digest(old.data()['materials_by_task'][task.content_hash])
        subjects[key]={'task_digest':task.content_hash,'material_digest':material_digest}
        assertions={n:'独立训练注释哨兵: '+n+' synthetic explicit expected criterion' for n in ENDPOINTS}
        source={'schema':'lineage-train-annotation-source-v1','identity':identity,'task_digest':task.content_hash,
            'material_digest':material_digest,'qualification':'caller_qualified_train_annotation','assertions':assertions}
        desc=_write(store,name+'-source.json',source)
        primary_record=FrozenRecord((primary/(handles[key]+'.json')).read_text(encoding='utf-8'))
        ref={'schema':'qualified-lineage-train-reference-v1','version':'v1','identity':identity,'task_digest':task.content_hash,
            'material_digest':material_digest,'primary_reference_digest':primary_record.content_hash,'sources':{'annotation':desc},
            'endpoints':{n:{'expected':assertions[n],'citations':[{'source':'annotation','assertion':n}]} for n in ENDPOINTS}}
        reference=_write(store,name+'-reference.json',ref);bindings[key]=reference['sha256']
        rows.append({'identity':identity,'task_handle':handles[key],'reference':reference})
    manifest=_write(store,'manifest.json',{'schema':'lineage-train-reference-store-v1','scope':'train_only','version':'v1','rows':rows})
    reference_binding={'manifest_sha256':manifest['sha256'],'references':bindings, 'subjects':subjects,
        'limits':{'model':'gpt-5.6-luna','effort':'low','tokens_per_cell':20,'timeout_seconds':180}}
    rubric=ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-lineage-process',version='v1',
        rubric_digest=FrozenLineageRubricEndpoint.rubric_digest())
    body=old.data();body.update(scorer=rubric.record.data(),scorer_handle_bindings={k:hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        lineage_reference_binding=reference_binding)
    config=FrozenLineageTrainConfig(FrozenRecord.from_dict(body));compiled=compile_lineage_train_panels(config,packets)
    (root/'execute.key').write_bytes(EXECUTION.key);(root/'score.key').write_bytes(SCORER.key)
    specs=[]
    for i,panel in enumerate(compiled.panels):
        worker=root/('worker'+str(i));worker.mkdir()
        base={'scorer_config':rubric.record.data(),'scorer_config_digest':rubric.digest,
            'train_reference_store':{'root':str(primary.resolve()),'manifest_sha256':primary_sha,
                'inventory_digest':packets[0].task.identity.dataset_version,'split_digest':panel.split_digest},
            'task_handles':handles,'execution_authority_key_files':{EXECUTION.authority_id:str((root/'execute.key').resolve())},
            'scorer_authority':{'id':SCORER.authority_id,'key_file':str((root/'score.key').resolve())},
            'evaluator':{'evaluator_id':'synthetic-lineage-process','evaluator_version':'v1','max_tokens':len(panel.cells)*20}}
        server={'schema':'lineage-scorer-process-config-v1','base':base,'panel':serialize_combination_panel(panel,lineage=True),
            'lineage_references':{'root':str(store.resolve()),**reference_binding}}
        path=worker/'server.json';path.write_bytes(canonical(server).encode('utf-8'))
        command=[sys.executable,str(Path(__file__).parent/'helpers'/'lineage_scorer_helper.py'),
            '--config',str(path),'--config-sha256',hashlib.sha256(path.read_bytes()).hexdigest(),'--journal',str(worker/'server.jsonl')]
        specs.append(dict(panel=panel,config=rubric,command=command,journal_path=worker/'client.jsonl',
            task_handle_bindings=body['scorer_handle_bindings'],execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
            scorer_authority_keys={SCORER.authority_id:SCORER.key},reference_binding=reference_binding,
            environment={**os.environ,'PYTHONIOENCODING':'gbk'}))
    return snapshot,custody,config,compiled,sources,specs


def _run(root,monkeypatch,fault=None):
    snapshot,custody,config,compiled,sources,specs=fixture(root)
    if fault:specs[0]['command'] += ['--fault',fault]
    clients=[]
    try:
        for spec in specs:clients.append(LineageScorerProcessClient(**spec))
        pool=LineageScorerProcessPool(clients)
        calls=[]
        port=model_port(root/'solver',monkeypatch,max_calls=136,max_tokens=1000,schemas=SCHEMAS,response_factory=_model(calls))
        result=run_lineage_train_panels(config,custody=custody,snapshot_root=snapshot,export_root=root/'export',
            run_root=root/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),source_verifier=sources,
            execution_authority=EXECUTION,scoring_service=pool,scorer_authority_keys={SCORER.authority_id:SCORER.key})
        return result,calls
    finally:
        for c in clients:c.close()


@pytest.fixture(scope='module')
def process_grid(tmp_path_factory):
    root=tmp_path_factory.mktemp('lineage-process-grid')
    mp=pytest.MonkeyPatch()
    try:
        result,calls=_run(root,mp)
        yield root,result,calls
    finally:mp.undo()


def test_full_34_cell_real_process_protected_evaluator_controller(process_grid):
    tmp_path,result,calls=process_grid
    assert len(result.scores)==34, [(r.data().get('phase'),r.data().get('error_type')) for r in result.attempts]
    assert len(calls)==136 and result.receipt.data()['actual_docker_attempts']==34
    for path in tmp_path.glob('worker*/evaluator/ledger.json'):
        ledger=json.loads(path.read_text(encoding='utf-8'))
        assert ledger['tokens']==len(ledger['calls'])*5 and all(c['status']=='succeeded' for c in ledger['calls'])
        assert int((path.parent/'child-pid.txt').read_text()) != os.getpid()
    for path in (tmp_path/'run').rglob('*'):
        if path.is_file():assert '独立训练注释哨兵'.encode('utf-8') not in path.read_bytes()
    for path in (tmp_path/'solver').rglob('prompt.txt'):
        assert 'PRIVATE-REFERENCE-SENTINEL' not in path.read_text(encoding='utf-8')

    assert all(r.data()['independent_scorer_usage']['body']['tokens']>0 for r in result.attempts)


@pytest.mark.parametrize('fault',['schema','refusal','timeout','exception'])
def test_worker_failure_no_retry_actual_usage_and_all_panel_cells_retained(tmp_path,process_grid,fault):
    _,grid,_=process_grid
    _,_,_,compiled,_,specs=fixture(tmp_path)
    spec=specs[0];spec['command'] += ['--fault',fault]
    by_key={result.cell.key:row.data()['score_input'] for result,row in zip(grid.results,grid.attempts)}
    client=LineageScorerProcessClient(**spec)
    try:
        failures=[]
        for cell in compiled.panels[0].cells:
            with pytest.raises(ContractError): client.score_lineage(panel=compiled.panels[0],cell=cell,score_input=FrozenRecord.from_dict(by_key[cell.key]))
            failures.append(cell.key)
        assert len(failures)==6
        usage=client.usage()['body']
        assert len(usage['calls'])==1 and usage['usage_incomplete'] is True
        assert usage['tokens']==(5 if fault in ('schema','refusal') else 0)
        assert usage['calls'][0]['usage'] is None if fault in ('timeout','exception') else usage['calls'][0]['usage']['total_tokens']==5
        if fault in ('schema','refusal'):
            output=json.loads(next((tmp_path/'worker0'/'evaluator'/'calls').glob('*/output.json')).read_text(encoding='utf-8'))
            assert output['lineage_endpoints']['root_attribution'] is True if fault=='schema' else output=={'refusal':'synthetic refusal'}
        with pytest.raises(ContractError,match='unresolved'):client.score_lineage(panel=compiled.panels[0],cell=compiled.panels[0].cells[0],score_input=FrozenRecord.from_dict(by_key[compiled.panels[0].cells[0].key]))
    finally:client.close()
    rows=[json.loads(line) for line in (tmp_path/'worker0'/'server.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows)==12 and [r['status'] for r in rows]==['reserved','unknown']*6


@pytest.mark.parametrize('fault',['bytes','version','identity','citation','material','manifest','limits','key'])
def test_reference_or_startup_drift_rejected_before_provider(tmp_path,fault):
    _,_,_,_,_,specs=fixture(tmp_path)
    spec=specs[0];server_path=tmp_path/'worker0'/'server.json'
    b=json.loads(server_path.read_text(encoding='utf-8'))
    store=tmp_path/'lineage-references';manifest=json.loads((store/'manifest.json').read_text(encoding='utf-8'))
    row=manifest['rows'][0];p=store/row['reference']['file'];ref=json.loads(p.read_text(encoding='utf-8'))
    if fault=='bytes':(store/'discoverybench-source.json').write_bytes(b'changed')
    elif fault=='manifest':(store/'manifest.json').write_bytes(b'changed')
    elif fault=='limits':spec['reference_binding']={**spec['reference_binding'],'limits':{**spec['reference_binding']['limits'],'tokens_per_cell':40}}
    elif fault=='key':spec['scorer_authority_keys']={SCORER.authority_id:b'z'*32}
    else:
        if fault=='version':ref['version']='v9'
        elif fault=='identity':ref['identity']['task_id']='foreign'
        elif fault=='citation':ref['endpoints']['root_attribution']['citations'][0]['assertion']='missing'
        elif fault=='material':ref['material_digest']='0'*64
        row['reference']=_write(store,p.name,ref)
        pin=_write(store,'manifest.json',manifest)['sha256'];key=digest(row['identity'])
        b['lineage_references']['manifest_sha256']=pin;b['lineage_references']['references'][key]=row['reference']['sha256']
        spec['reference_binding']={k:v for k,v in b['lineage_references'].items() if k!='root'}
        server_path.write_bytes(canonical(b).encode('utf-8'))
        spec['command'][spec['command'].index('--config-sha256')+1]=hashlib.sha256(server_path.read_bytes()).hexdigest()
    with pytest.raises(ContractError):LineageScorerProcessClient(**spec)
    ledger=json.loads((tmp_path/'worker0'/'evaluator'/'ledger.json').read_text(encoding='utf-8'))
    assert ledger['calls']==[]
    assert not (tmp_path/'worker0'/'server.jsonl').exists()


@pytest.mark.parametrize('fault',['cross_cell','context_label','foreign_material'])
def test_signed_foreign_or_label_input_rejected_before_evaluator(tmp_path,process_grid,fault):
    _,grid,_=process_grid
    _,_,_,compiled,_,specs=fixture(tmp_path)
    cell=compiled.panels[0].cells[0]
    value=grid.attempts[0].data()['score_input']
    if fault=='cross_cell':value=grid.attempts[1].data()['score_input']
    else:
        outer=value['body']
        if fault=='foreign_material':outer['material_digest']='0'*64
        else:
            outer['public_context']['arm_id']='private-controller-label'
            outer['public_context_digest']=digest(outer['public_context'])
            primary=outer['primary']['body'];primary['joint_mechanism_digest']=outer['public_context_digest']
            outer['primary']=EXECUTION.issue(primary).data()
        value=EXECUTION.issue(outer).data()
    client=LineageScorerProcessClient(**specs[0])
    try:
        with pytest.raises(ContractError):client.score_lineage(panel=compiled.panels[0],cell=cell,score_input=FrozenRecord.from_dict(value))
        assert client.usage()['body']['calls']==[]
    finally:client.close()


def test_full_controller_keeps_failed_scorer_denominator(tmp_path,monkeypatch):
    result,calls=_run(tmp_path,monkeypatch,'schema')
    assert len(result.attempts)==34 and len(result.results)==34 and len(calls)==136
    assert len(result.scores)==28 and result.receipt.data()['status']=='inconclusive'
    assert result.receipt.data()['actual_docker_attempts']==34 and result.receipt.data()['actual_scorer_calls']==34
    assert sum(r.data()['status']=='failed' for r in result.attempts)==6


def test_real_hung_child_is_terminated_with_reserved_unknown_cost(tmp_path,process_grid):
    _,grid,_=process_grid
    _,_,_,compiled,_,specs=fixture(tmp_path)
    spec=specs[0];spec['command'] += ['--fault','hang']
    client=LineageScorerProcessClient(**spec)
    client.response_timeout_seconds=2
    cell=compiled.panels[0].cells[0]
    try:
        with pytest.raises(ContractError,match='timed out'):
            client.score_lineage(panel=compiled.panels[0],cell=cell,
                score_input=FrozenRecord.from_dict(grid.attempts[0].data()['score_input']))
        assert client.process.poll() is not None
        assert client.usage()=={'status':'unknown','cost_unknown':True}
        ledger=json.loads((tmp_path/'worker0'/'evaluator'/'ledger.json').read_text(encoding='utf-8'))
        assert len(ledger['calls'])==1 and ledger['calls'][0]['status']=='reserved'
        rows=[json.loads(line) for line in (tmp_path/'worker0'/'server.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [r['status'] for r in rows]==['reserved']
    finally:client.close()


@pytest.mark.parametrize('fault',['off_grid','schema'])
def test_independent_receipt_verifier_rejects_resigned_rubric_contract_drift(process_grid,fault):
    from evaluation.modular.lineage_combination_scoring import verify_lineage_score
    from research_loop.modular.panel_receipts import ScientificScorerReceipt
    root,grid,_=process_grid
    server=json.loads((root/'worker0'/'server.json').read_text(encoding='utf-8'))
    panel=grid.compiled.panels[0];cell=panel.cells[0]
    row=grid.attempts[0].data();body=row['scorer_receipt']['body']
    if fault=='off_grid':
        body['endpoints']['root_attribution']=.25
        body['rubric_response']['lineage_endpoints']['root_attribution']=.25
    else:
        body['rubric_response']['evidence']['schema_digest']='0'*64
        primary=body['primary']['body'];primary['evaluator_evidence']['schema_digest']='0'*64
        body['primary']=SCORER.issue(primary).data()
    body['rubric_response_digest']=digest(body['rubric_response'])
    forged=ScientificScorerReceipt(cell.key,SCORER.issue(body))
    with pytest.raises(ContractError):
        verify_lineage_score(forged,authority_keys={SCORER.authority_id:SCORER.key},
            config=ScorerConfig(FrozenRecord.from_dict(server['base']['scorer_config'])),panel=panel,cell=cell,
            score_input=FrozenRecord.from_dict(row['score_input']),execution_authority_keys={EXECUTION.authority_id:EXECUTION.key},
            expected_reference_digest=server['lineage_references']['references'][digest(cell.identity.data())])
