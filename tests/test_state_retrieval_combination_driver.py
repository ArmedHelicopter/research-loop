"""Synthetic public TRAIN packets, signed source observations and actual Docker.

No benchmark reference store, validation data, scorer or paid model is opened.
"""
import hashlib
import json
from dataclasses import replace

import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, MaterialAuthority
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.state_retrieval_combination_driver import (
    DESIGNS, SLOTS, registered_design, FrozenStateRetrievalMaterial, freeze_material,
    run_state_retrieval_cell, verify_state_retrieval_cell)
from research_loop.ontology import ContractError
from test_admission_combination import sources as admission_sources
from test_modular_combination_benchmark_driver import _rewrite_trace

IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'


def provenance(calls, fault=None):
    authorities = []
    for i in range(2):
        signer = LinkedExecutionAuthority('public-origin-'+str(i), bytes([80+i])*32)
        group = 'public-observation-'+str(i)
        def verify(request, signer=signer, group=group):
            calls.append(request)
            b = request.data(); assert b['material']['identity']['domain'] == 'train'
            return signer.issue({'schema': 'lineage-material-provenance-response-v1',
                'request_digest': request.content_hash, 'material_digest': b['material_digest'],
                'identity': b['material']['identity'], 'source_group': group,
                'verdict': 'unknown' if fault else 'verified', 'cost_units': 1})
        authorities.append(MaterialAuthority(signer, group, verify))
    return DualMaterialVerifier(tuple(authorities))


def state_material(task, path, admission):
    bindings = {'task': task.identity.task_id, 'variable': 'x'}
    b = {'schema': 'lineage-combination-material-v1', 'identity': task.identity.data(), 'task_digest': task.content_hash,
        'public_artifacts': [{'artifact': {'artifact_id': 'public_csv', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'byte_count': len(path.read_bytes())}, 'container_path': '/input/public_csv'}],
        'question': 'Which current observations support the value of x?', 'context_budget_bytes': 24000,
        'ordinary_summary': 'The old interpretation that x is high remains in this ordinary summary.',
        'originals': [{'key': key, 'root_material': {'observation': key+'-measurement'}, 'content': {'x': value},
            'subject_bindings': bindings} for key,value in [('old',8),('current',1),('uncalibrated',99)]],
        'representations': [{'key': 'old-report', 'root': 'old', 'representation': 'report', 'content': {'reported_x':8}},
            {'key':'old-summary','root':'old','representation':'summary','content':{'summary_x':8}}],
        'claims': [{'key':'upstream','statement':'The older x is high.','subject_bindings':bindings,'supports':['old'],'refutes':[],'depends_on':[]},
            {'key':'downstream','statement':'Interpretation depends on the old observation.','subject_bindings':bindings,
                'supports':['current'],'refutes':[],'depends_on':['upstream']}],
        'withdrawals': [{'root':'old','reason':'Original public source withdrew its old observation.'}]}
    if admission:
        b.update(schema='admission-combination-material-v1', withdrawals=[], qualification_observations={
            'before': {'old':{'effect':1,'calibration_error':0},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}},
            'after': {'old':{'effect':1,'calibration_error':2},'current':{'effect':-1,'calibration_error':0},'uncalibrated':{'effect':1,'calibration_error':2}}})
    return (FrozenAdmissionMaterial if admission else FrozenLineageMaterial)(FrozenRecord.from_dict(b))


class Provider:
    def __init__(self, calls, fail=False): self.calls, self.fail = calls, fail
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        assert call_limit == source_limit == 1
        self.calls.append((lane, query.data()))
        rows = [d for d in source_bundle.documents if d.lane == lane]
        if self.fail:
            yield rows[0]
            raise RuntimeError('original partial provider failure')
        if lane != 'counter' or query.data()['intent'].startswith('Seek support,'):
            yield rows[0]


def model(seen, fault=None):
    def respond(request):
        b = request.data(); seen.append(b); joint = b['module_context']['joint_mechanism']
        assert all(marker not in request.encoded for marker in ('"enabled"','"arm_id"','"policy_digest"','"source_bundle_digest"',
            'private-origin-', 'public-origin-', 'qualification_observations', 'pair:M1', 'pair:M2', 'pair:M3'))
        if b['slot'] == 'analysis_program':
            if fault == 'model': raise RuntimeError('original model transport failure')
            if fault == 'analysis': return FrozenRecord.from_dict({'analysis':'','program':'print(1)'})
            # Both actual mechanisms alter the executable computation, not just metadata hashes.
            observations = [next(iter(v['content'].values())) for v in joint['state_projection']['observations']]
            pending = sum(v.get('needs_review') is True for v in joint['state_projection']['memory'])
            counter = len(joint['retrieval']['by_lane']['counter'])
            program = "import csv,json\nwith open('/input/public_csv',newline='') as f: rows=list(csv.DictReader(f))\nmean=sum(float(r['x']) for r in rows)/len(rows)\nobservations="+repr(observations)+"\npending="+repr(pending)+"\ncounter="+repr(counter)+"\nprint(json.dumps({'mean':mean,'observations':observations,'pending':pending,'counter':counter,'adjusted':sum(observations)/len(observations)-counter-pending},sort_keys=True))"
            if fault == 'docker': program = "raise ValueError('original Docker failure')"
            return FrozenRecord.from_dict({'analysis':'Compute the public mean with current state and counter-source adjustment.', 'program':program})
        return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'], 'outcome':'unknown',
            'evidence_ids':[], 'conclusion':'Observed public synthetic execution: '+b['execution_feedback'][0]['stdout'], 'programme_complete':False})
    return respond


def fixture(root, obligation, source_fault=None):
    root.mkdir(parents=True, exist_ok=True)
    calls=[]; retrieval_calls=[]
    source = admission_sources(calls) if obligation == 'pair:M1+M6' else provenance(calls)
    retrieval = provenance(retrieval_calls, source_fault)
    tasks = [PublicTask.create(DataIdentity(benchmark, 'public-example', 'public-group-'+benchmark, 'b'*64, 'c'*64, 'train'),
        {'question':'Compute the mean of x and examine current public observations.', 'columns':['x']}) for benchmark in ('blade','discoverybench')]
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze(t.identity for t in tasks),
        changes={'prompt':{'instructions':'Analyze the public measurements.'}}, search_cost=0)
    design=registered_design(obligation,'a'*64); cells=[]; args={}
    docs = [{'source_id':'private-origin-'+str(i), 'root_source_id':'private-origin-root-'+str(i), 'lane':lane, 'text':text}
        for i,(lane,text) in enumerate([('support','The old values suggest a high mean.'),('counter','Check a withdrawn old measurement.'),('method','Calculate the current public CSV mean.')])]
    for task in tasks:
        folder=root/task.identity.benchmark; folder.mkdir(); path=folder/'public.csv'; path.write_text('x\n0\n1\n2\n',encoding='utf-8')
        material=freeze_material(task,state_material(task,path,obligation=='pair:M1+M6'),docs,'Which observations distinguish the public explanations?')
        scenario=FrozenRecord.from_dict({'schema':'state-retrieval-combination-scenario-v1','obligation_id':obligation,
            'design_digest':design.content_hash,'task_digest':task.content_hash,'replicate':'r1','material_digest':material.record.content_hash,
            'source_verifier_binding':source.binding().data(),'retrieval_verifier_binding':retrieval.binding().data()})
        for arm in design.data()['cells']:
            cell=PanelCell(obligation,task.identity,'r1','combination',arm['id'],FrozenRecord.from_dict(arm['arm']),task.content_hash,
                scenario.content_hash,package.digest,'d'*64)
            cells.append(cell); args[cell.key]=dict(task=task,scenario=scenario,package=package,material=material,source_verifier=source,
                retrieval_verifier=retrieval,public_inputs={'public_csv':path},broker=DockerExecutionBroker([root]))
    panel=CombinationPanel('synthetic-state-retrieval','train','c'*64,obligation,'interaction_on_scale',design,
        FrozenRecord.from_dict({'schema':'combination-package-bundle-v1','packages':{c.runtime_arm.content_hash:package.record.data() for c in cells}}),
        FrozenRecord.from_dict({'engineering_only':True}),tuple(cells))
    for values in args.values(): values['panel']=panel
    return panel,args,calls,retrieval_calls


def execute(root, args, cell, fault=None):
    seen=[]; calls=[]
    result=run_state_retrieval_cell(cell=cell, **args, provider=Provider(calls,fault=='provider'), objective=FrozenRecord.from_dict({'goal':'public synthetic check'}),
        sidecar=root/cell.identity.benchmark/('run-'+cell.arm_id), image=IMAGE, model=model(seen,fault), audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    verify_state_retrieval_cell(result,**args)
    return result,seen,calls


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    outputs=[]
    for obligation in DESIGNS:
        root=tmp_path_factory.mktemp('state-retrieval-'+DESIGNS[obligation][0]); panel,args,sources,retrieval=fixture(root,obligation)
        for cell in panel.cells:
            result,seen,calls=execute(root,args[cell.key],cell)
            outputs.append((result,args[cell.key],seen,calls))
        assert len(sources)==len(retrieval)==16
    return outputs


def test_real_docker_all_three_pairs_share_state_and_retrieval_solver(grid):
    assert len(grid)==24
    for result,args,seen,calls in grid:
        assert result.runtime.status=='succeeded', result.solver.status if result.solver else result.runtime
        assert len(seen)==2 and len(calls)==3
        enabled=set(result.cell.runtime_arm.data()['enabled']); t=result.transition.data()
        observed=json.loads(result.solver.execution.record.data()['stdout'])
        assert observed['mean']==1 and observed['counter']==('M6' in enabled)
        if result.cell.coverage_id=='pair:M1+M6':
            assert len(observed['observations'])==(1 if 'M1' in enabled else 5)
            if 'M1' in enabled:
                assert t['decisions']['before']['current']['admitted'] is True
                assert t['decisions']['before']['uncalibrated']['admitted'] is False
                assert t['revoked']==['old']
        elif result.cell.coverage_id=='pair:M2+M6':
            assert len(observed['observations'])==(2 if 'M2' in enabled else 5)
            if 'M2' in enabled:
                assert len(t['evidence']['withdrawn'])==1 and any(c['needs_review'] for c in t['after_claims']['claims'])
        else:
            assert 'M2' in enabled
            assert observed['pending']>0 if 'M3' in enabled else observed['pending']==0
            if 'M3' in enabled: assert t['context_before_digest']!=t['context_after_digest']
        assert result.solver.session.sidecar==result.runtime.trace_path.parent
    for name in DESIGNS:
        for benchmark in ('blade','discoverybench'):
            outputs=[json.loads(r.solver.execution.record.data()['stdout'])['adjusted'] for r,_,_,_ in grid
                if r.cell.coverage_id==name and r.cell.identity.benchmark==benchmark]
            assert len(set(outputs))==4


@pytest.mark.parametrize('fault',['provider','model','analysis','docker'])
def test_original_failures_remain_replayable_without_false_success(tmp_path,fault):
    panel,args,_,_=fixture(tmp_path,'pair:M1+M6'); cell=panel.cells[-1]
    result,seen,calls=execute(tmp_path,args[cell.key],cell,fault)
    assert result.runtime.status=='failed'
    assert len(calls)==(1 if fault=='provider' else 3)
    if fault=='provider': assert not seen and result.solver is None
    if fault=='docker': assert result.solver.execution.record.data()['exit_code']!=0


@pytest.mark.parametrize('fault',['state_original','state_claims','corpus','query','provenance','authority_signature','program','csv'])
def test_original_material_files_and_signatures_are_rechecked(grid,fault):
    result,args,*_=next(row for row in grid if row[0].cell.coverage_id=='pair:M1+M6' and row[0].cell.arm_id=='11')
    if fault in ('state_original','state_claims','corpus','query','provenance'):
        b=args['material'].data()
        if fault=='state_original': b['state']['originals'][0]['content']['x']=500
        if fault=='state_claims': b['state']['claims'][0]['statement']='Forged interpretation.'
        if fault=='corpus': b['retrieval']['original_sources'][0]['text']['text']='Forged corpus.'
        if fault=='query': b['retrieval']['query']['question']='Forged query.'
        if fault=='provenance': b['provenance']['identity']['domain']='validation'
        with pytest.raises(ContractError):
            forged=FrozenStateRetrievalMaterial(FrozenRecord.from_dict(b))
            verify_state_retrieval_cell(result,**{**args,'material':forged})
        return
    path = (result.runtime.trace_path.parent/'analysis-1.py' if fault=='program' else args['public_inputs']['public_csv'] if fault=='csv'
        else result.runtime.trace_path.parent.parent/'retrieval'/'source-verification.json')
    before=path.read_bytes()
    try:
        if fault=='authority_signature':
            b=json.loads(before); b['calls'][0]['response']['body']['source_group']='forged'; path.write_text(json.dumps(b),encoding='utf-8')
        else: path.write_bytes(before+b'\n# forged bytes\n')
        with pytest.raises(ContractError): verify_state_retrieval_cell(result,**args)
    finally: path.write_bytes(before)


@pytest.mark.parametrize('fault',['transition','source_item','source_budget','retrieval_projection','state_journal','joint','request_context','response_program','order'])
def test_rehashed_forgeries_fail_independent_replay(grid,fault):
    result,args,*_=next(row for row in grid if row[0].cell.coverage_id=='pair:M3+M6' and row[0].cell.arm_id=='11')
    path=result.runtime.trace_path; before=path.read_bytes()
    if fault=='state_journal':
        path=path.parent/'claims.jsonl'; before=path.read_bytes()
        try:
            path.write_bytes(b'')
            with pytest.raises(ContractError,match='state journals'): verify_state_retrieval_cell(result,**args)
        finally: path.write_bytes(before)
        return
    def mutate(events):
        if fault=='transition': next(e for e in events if e['stage']=='state_retrieval_transition')['data']['transition']['public']['observations']=[]
        if fault=='source_item': next(e for e in events if e['stage']=='q8_retrieval_item')['data']['source_digest']='0'*64
        if fault=='source_budget': next(e for e in events if e['stage']=='q8_retrieval_request')['data']['remaining']['source_slots']=3
        if fault=='retrieval_projection': next(e for e in events if e['stage']=='retrieval_review_sources')['data']['projection']['by_lane']['counter']=[]
        if fault=='joint': next(e for e in events if e['stage']=='state_retrieval_joint')['data']['joint']['state_projection']['observations']=[]
        if fault=='request_context': next(e for e in events if e['stage']=='model_request')['data']['request']['module_context']['joint_mechanism']['retrieval']['by_lane']['counter']=[]
        if fault=='response_program': next(e for e in events if e['stage']=='model_response')['data']['response']['program']='print(99)'
        if fault=='order':
            row=next(e for e in events if e['stage']=='state_retrieval_transition'); events.remove(row)
            events.insert(next(i for i,e in enumerate(events) if e['stage']=='model_request')+1,row)
    try:
        digest=_rewrite_trace(path,mutate)
        forged=replace(result,runtime=replace(result.runtime,trace_digest=digest))
        with pytest.raises(ContractError): verify_state_retrieval_cell(forged,**args)
    finally: path.write_bytes(before)


def test_exact_family_material_types_and_signed_corpus_admission_precede_io(tmp_path):
    panel,args,sources,retrieval=fixture(tmp_path,'pair:M1+M6',source_fault='unknown'); cell=panel.cells[0]
    seen=[]; provider_calls=[]
    with pytest.raises(ContractError):
        run_state_retrieval_cell(cell=cell,**args[cell.key],provider=Provider(provider_calls),model=model(seen),
            objective=FrozenRecord.from_dict({'goal':'synthetic'}),sidecar=tmp_path/'failed',image=IMAGE,
            audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    assert len(sources)==len(retrieval)==2 and not seen and not provider_calls
    b=registered_design('pair:M3+M6','a'*64).data(); assert b['background']==['M2']
    with pytest.raises(ContractError): registered_design('pair:M4+M6','a'*64)
