"""Public synthetic custody -> actual modules -> mocked Codex -> Docker -> rubric."""
import hashlib
from dataclasses import replace
from pathlib import Path
import json
import pytest

from evaluation.modular.train_io import TrainPacketExporter
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig, FrozenRubricTransport
from evaluation.modular.lineage_combination_scoring import LineageCombinationScoringService, ENDPOINTS
from research_loop.modular import lineage_combination_controller as controller
from research_loop.modular.lineage_combination_controller import FrozenLineageTrainConfig, compile_lineage_train_panels, run_lineage_train_panels
from research_loop.modular.lineage_combination_driver import DESIGNS, SLOTS, verify_lineage_combination_cell
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, MaterialAuthority, DualMaterialVerifier
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, model_port, REVIEW, FINAL
from test_modular_combination_train_controller import ANALYSIS, IMAGE

EXECUTION = LinkedExecutionAuthority('lineage-execution', b'e'*32)
SCORER = LinkedExecutionAuthority('lineage-scoring', b's'*32)
SCHEMAS = {SLOTS[0]: REVIEW, SLOTS[1]: REVIEW, 'analysis_program': ANALYSIS, 'final_answer': FINAL}


def _sources(calls, *, fault=None, run_root=None):
    authorities = []
    for i in range(2):
        key = LinkedExecutionAuthority('source-'+str(i), bytes([97+i])*32)
        group = 'configured-public-origin-'+str(i)
        def verify(request, key=key, group=group):
            calls.append(request)
            b = request.data(); material = b['material']
            if run_root is not None:
                receipts=[json.loads(p.read_text(encoding='utf-8')) for p in run_root.glob('cells/*/source-verification.json')]
                assert any(r['request']==b and r['calls'][-1]['authority']==key.authority_id
                           and r['calls'][-1]['status']=='reserved' and r['calls'][-1]['cost_unknown'] is True
                           and r['calls'][-1]['limits']==b['limits'] for r in receipts)
            assert material['identity']['domain'] == 'train' and material['originals'] and material['withdrawals']
            if fault == 'exception' and len(calls) == 1: raise RuntimeError('public fixture source failure')
            return key.issue({'schema': 'lineage-material-provenance-response-v1', 'request_digest': request.content_hash,
                'material_digest': b['material_digest'] if fault != 'foreign_subject' else '0'*64,
                'identity': material['identity'], 'source_group': group,
                'verdict': 'unknown' if fault == 'unknown' and len(calls) == 1 else 'verified', 'cost_units': 1})
        authorities.append(MaterialAuthority(key, group, verify))
    return DualMaterialVerifier(tuple(authorities))


def _fixture(root, source_verifier):
    snapshot, custody = snapshot_and_custody(root)
    items = ['discoverybench:synth:train:family_1_1', 'blade:fish']
    packets = TrainPacketExporter(custody, snapshot, root/'material').export(items)
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([p.task.identity for p in packets]),
        changes={'prompt': {'instructions': 'Use the supplied public observation and withdrawal history.'}}, search_cost=0)
    materials, bindings = {}, {}
    for packet in packets:
        task = packet.task; data = packet.csv_path.read_bytes(); binding = {'task': task.identity.task_id, 'variable': 'x'}
        materials[task.content_hash] = {'schema': 'lineage-combination-material-v1', 'identity': task.identity.data(),
            'task_digest': task.content_hash, 'public_artifacts': [{'artifact': {'artifact_id': 'public_csv',
                'sha256': hashlib.sha256(data).hexdigest(), 'byte_count': len(data)}, 'container_path': '/input/public_csv'}],
            'question': 'Which current public observations support the value of x?', 'context_budget_bytes': 16000,
            'ordinary_summary': 'Earlier observations suggest x is high; the old summary has not been revised.',
            'originals': [{'key': 'old', 'root_material': {'observation': 'old-public-measurement'}, 'content': {'x': 8}, 'subject_bindings': binding},
                          {'key': 'current', 'root_material': {'observation': 'current-public-measurement'}, 'content': {'x': 1}, 'subject_bindings': binding}],
            'representations': [{'key': 'copy-report', 'root': 'old', 'representation': 'report', 'content': {'reported_x': 8}},
                                {'key': 'copy-summary', 'root': 'old', 'representation': 'summary', 'content': {'summary_x': 8}}],
            'claims': [{'key': 'upstream', 'statement': 'The older observed x is high.', 'subject_bindings': binding,
                        'supports': ['old'], 'refutes': [], 'depends_on': []},
                       {'key': 'downstream', 'statement': 'The earlier interpretation depends on the old observation.',
                        'subject_bindings': binding, 'supports': ['current'], 'refutes': [], 'depends_on': ['upstream']}],
            'withdrawals': [{'root': 'old', 'reason': 'Public source withdrew its earlier observation.'}]}
        bindings[f'{task.identity.benchmark}:{task.identity.task_id}'] = {'identity': task.identity.data(),
            'task_digest': task.content_hash, 'csv_sha256': hashlib.sha256(data).hexdigest(), 'csv_byte_count': len(data)}
    scorer = ScorerConfig.create(benchmark='core_pair', evaluator_id='synthetic-lineage-rubric', version='v1',
        rubric_digest=FrozenRecord.from_dict({'fixture_rubric': list(ENDPOINTS)}).content_hash)
    handles = {FrozenRecord.from_dict(p.task.identity.data()).content_hash: 'synthetic-'+p.task.identity.benchmark for p in packets}
    config = FrozenLineageTrainConfig(FrozenRecord.from_dict({'schema': 'lineage-combination-train-config-v1',
        'domain': 'train', 'stage': 'synthetic-lineage', 'item_ids': items, 'task_bindings': bindings, 'baseline_digest': 'a'*64,
        'packages_by_arm': {k: package.record.data() for k in controller._arms('a'*64)}, 'scorer': scorer.record.data(),
        'scorer_handle_bindings': {k: hashlib.sha256(v.encode()).hexdigest() for k,v in handles.items()},
        'acceptance_criteria': {'contrast_analysis': controller._ANALYSIS}, 'replicates': ['r1'],
        'model': 'gpt-5.6-luna', 'effort': 'low', 'max_calls': 136, 'max_tokens': 1000, 'schemas': SCHEMAS,
        'allocation': {'model_slots_per_cell': list(SLOTS), 'docker_attempts_per_cell': 1, 'scorer_calls_per_cell': 1,
            'scorer_call_limit': 34, 'scorer_token_accounting': 'transport_not_provided', 'source_calls_per_cell': 2},
        'image': IMAGE, 'timeout_seconds': 20, 'materials_by_task': materials,
        'source_verifier_binding': source_verifier.binding().data()}))
    return snapshot, custody, packets, config, scorer, handles


def _model(calls, fault=None):
    def respond(request):
        b = request.data(); calls.append(b)
        assert all(marker not in request.encoded for marker in ('"arm_id"', '"enabled"', '"control"', '"truth"',
            '"source_group"', '"key_digest"', '"argv"', '"packages_by_arm"'))
        if b['slot'] in SLOTS[:2]:
            if fault == 'review_invalid' and len(calls) == 1:
                return FrozenRecord.from_dict({'assessment': 'invalid', 'evidence_refs': [], 'counterexamples': [], 'uncertainty': 'unknown'})
            material = b['module_context']['material']
            return FrozenRecord.from_dict({'assessment': 'concern', 'evidence_refs': [], 'counterexamples': [],
                'uncertainty': b['slot']+' public observations '+str(len(material['observations']))})
        if b['slot'] == 'analysis_program':
            if fault == 'analysis_invalid': return FrozenRecord.from_dict({'analysis': '', 'program': 'print(1)'})
            if fault == 'solver_transport': raise RuntimeError('synthetic solver failure')
            joint = b['module_context']['joint_mechanism']; material = joint['material']
            observed = {'observations': len(material['observations']), 'needs_review': sum(e.get('needs_review') is True for e in material['memory']),
                        'reviews': len(joint['review_responses'] or [])}
            program = "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))\nprint("+repr(str(observed))+")"
            if fault == 'docker_failed': program = "raise ValueError('public synthetic failure')"
            return FrozenRecord.from_dict({'analysis': 'Use the actual public lineage and reviews.', 'program': program})
        assert b['slot'] == 'final_answer'
        return FrozenRecord.from_dict({'objective_digest': b['module_context']['required_objective_digest'], 'outcome': 'unknown',
            'evidence_ids': [], 'conclusion': '' if fault == 'answer_invalid' else 'Observed: '+b['execution_feedback'][0]['stdout']+'; no scientific validity established.',
            'programme_complete': False})
    return respond


def _service(config, handles, calls, fault=None):
    def evaluate(request):
        calls.append(request)
        b = request.data()
        assert b['schema'] == 'lineage-adapted-rubric-request-v1' and b['lineage_endpoints'] == list(ENDPOINTS)
        assert b['task_handle'] in handles.values() and b['public_context']['material']['observations']
        if fault == 'scorer' and len(calls) == 1: raise RuntimeError('synthetic rubric failure')
        # Explicitly synthetic rubric transport; no scientific calibration claim.
        dimensions = {k: 1.0 for k in (('cvars','transform','model') if b['benchmark']=='blade' else ('context','variable_f1','relation'))}
        material = b['public_context']['material']
        endpoints = {'root_attribution': float(len(material['observations'])==1),
            'withdrawal_awareness': float('needs_review' in b['candidate']['program']),
            'context_currency': float(any(e.get('needs_review') is True for e in material['memory'])),
            'review_responsiveness': float(bool(b['public_context']['review_responses']))}
        return FrozenRecord.from_dict({'schema':'adapted-rubric-evaluation-response-v1','panel_digest':b['panel_digest'],
            'scorer_config_digest': config.digest, 'benchmark': b['benchmark'], 'task_handle_digest':hashlib.sha256(b['task_handle'].encode()).hexdigest(),
            'candidate_digest':b['candidate_digest'], 'dimensions':dimensions,
            'public_context_digest':b['public_context_digest'], 'lineage_endpoints':endpoints,
            'evidence': {'schema':'frozen-rubric-call-evidence-v1', 'evaluator_id':config.record.data()['evaluator_id'],
                'evaluator_version':'v1', 'prompt_digest':request.content_hash, 'schema_digest':FrozenRecord.from_dict({'endpoints':list(ENDPOINTS)}).content_hash,
                'output_digest':FrozenRecord.from_dict({'primary':dimensions,'endpoints':endpoints}).content_hash,
                'reference_digest':FrozenRecord.from_dict({'synthetic_public_expected_x':1}).content_hash,
                'rubric_digest':config.record.data()['rubric_digest'], 'mode':'single_candidate_train_only'}})
    return LineageCombinationScoringService(config=config, evaluator=FrozenRubricTransport(evaluate),
        execution_authority_keys={EXECUTION.authority_id:EXECUTION.key}, task_handles=handles, scorer_authority=SCORER)


def _run(root, monkeypatch, fault=None):
    source_calls=[]; sources=_sources(source_calls, fault=fault, run_root=root/'run')
    snapshot,custody,packets,config,scorer,handles = _fixture(root,sources)
    model_calls=[]; score_calls=[]
    port=model_port(root/'port',monkeypatch,max_calls=136,max_tokens=1000,schemas=SCHEMAS,response_factory=_model(model_calls,fault))
    result=run_lineage_train_panels(config,custody=custody,snapshot_root=snapshot,export_root=root/'export',run_root=root/'run',
        model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),source_verifier=sources,
        execution_authority=EXECUTION,scoring_service=_service(scorer,handles,score_calls,fault),scorer_authority_keys={SCORER.authority_id:SCORER.key})
    return result,port,model_calls,score_calls,source_calls,sources


@pytest.fixture(scope='module')
def grid(tmp_path_factory):
    root = tmp_path_factory.mktemp('lineage-grid')
    with pytest.MonkeyPatch.context() as patch:
        yield (*_run(root,patch), root)


def test_complete_34_cell_custody_compiler_shared_session_docker_and_independent_rubric(grid):
    result,port,calls,scores,sources,_,_ = grid
    assert len(result.results)==len(result.scores)==34, [r.data() for r in result.attempts if r.data()['status']!='succeeded']
    assert len(calls)==len(port.ledger['calls'])==136 and len(scores)==34 and len(sources)==68
    assert [len(p.cells) for p in result.compiled.panels]==[6,8,8,12]
    assert [c.data()['status'] for c in result.contrasts]==['not_identifiable','estimated','estimated','not_identifiable']
    for executed in result.results:
        enabled=set(executed.cell.runtime_arm.data()['enabled']); transition=executed.transition.data()
        assert transition['raw_representation_denominator']==4 and transition['root_denominator']==2
        if 'M2' in enabled:
            claims=transition['after_claims']['claims']
            assert len(transition['evidence']['withdrawn'])==1 and all(c['needs_review'] for c in claims)
            assert len(transition['public']['observations'])==1
        if 'M3' in enabled:
            assert 'M2' in enabled and transition['context_before_digest']!=transition['context_after_digest']
            assert not any(e['kind']=='untrusted_summary' for e in transition['public']['memory'])
        stdout=executed.solver.execution.record.data()['stdout']
        assert "'observations': "+('1' if 'M2' in enabled else '4') in stdout
        assert "'reviews': "+('2' if 'M5' in enabled else '0') in stdout
    assert result.receipt.data()['pruned_cells']==[] and result.receipt.data()['validation_opened'] is False


@pytest.mark.parametrize('fault', ['request_context', 'ledger_withdrawal', 'review_response', 'script_same_size',
    'source_cost_bool', 'source_foreign_cell', 'final_execution_binding', 'joint_before_reviews', 'barrier_open_early'])
def test_readonly_replay_rejects_consistently_rehashed_public_artifact_forgery(grid, fault):
    from test_modular_combination_benchmark_driver import _rewrite_trace
    run,_,_,_,_,sources,root = grid
    result=next(r for r in run.results if set(r.cell.runtime_arm.data()['enabled'])=={'M2','M3','M5'})
    panel=next(p for p in run.compiled.panels if result.cell in p.cells)
    packet=next(p for p in run.compiled.packets if p.task.content_hash==result.cell.task_digest)
    args=dict(panel=panel,task=packet.task,scenario=run.compiled.scenarios[result.cell.key],
        package=run.compiled.packages[result.cell.runtime_arm.content_hash],material=run.compiled.materials[result.cell.task_digest],
        source_verifier=sources,public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([root/'export',root/'run']))
    trace=result.runtime.trace_path; saved={p:p.read_bytes() for p in trace.parent.iterdir() if p.is_file()}
    source_path=trace.parent.parent/'source-verification.json'; saved[source_path]=source_path.read_bytes()
    def change(events):
        if fault in {'request_context','final_execution_binding'}:
            request=next(e for e in events if e['stage']=='model_request' and e['data']['request']['slot']==('lineage_review' if fault=='request_context' else 'final_answer'))
            if fault=='request_context': request['data']['request']['module_context']['material']['observations']=[]
            else: request['data']['request']['module_context']['execution_digest']='0'*64
            old=request['data']['request_digest']; new=FrozenRecord.from_dict(request['data']['request']).content_hash
            request['data']['request_digest']=new
            for event in events:
                if event['stage']=='model_response' and event['data']['request_digest']==old: event['data']['request_digest']=new
        elif fault=='ledger_withdrawal':
            path=trace.parent/'evidence.jsonl'; rows=path.read_text(encoding='utf-8').splitlines()
            path.write_text('\n'.join(line for line in rows if FrozenRecord(line).data()['event']!='withdraw')+'\n',encoding='utf-8')
        elif fault=='review_response':
            path=trace.parent/'reviews.jsonl'; rows=[FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
            rows[1]['response']['uncertainty']='a different provider response'
            path.write_text('\n'.join(FrozenRecord.from_dict(r).encoded for r in rows)+'\n',encoding='utf-8')
        elif fault=='script_same_size':
            path=trace.parent/'analysis-1.py'; original=path.read_bytes(); altered=original.replace(b'print(',b'PRINT(',1)
            assert altered!=original and len(altered)==len(original); path.write_bytes(altered)
        elif fault=='source_cost_bool':
            data=json.loads(source_path.read_text(encoding='utf-8')); data['calls'][0]['cost_units']=True
            source_path.write_text(json.dumps(data),encoding='utf-8')
            next(e for e in events if e['stage']=='lineage_transition')['data']['source_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
        elif fault=='source_foreign_cell':
            other=next(r for r in run.results if r.cell.task_digest==result.cell.task_digest and r.cell.key!=result.cell.key)
            source_path.write_bytes((other.runtime.trace_path.parent.parent/'source-verification.json').read_bytes())
            next(e for e in events if e['stage']=='lineage_transition')['data']['source_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
        elif fault=='joint_before_reviews':
            joint=next(e for e in events if e['stage']=='lineage_joint'); events.remove(joint)
            events.insert(next(i for i,e in enumerate(events) if e['stage']=='model_request'),joint)
        elif fault=='barrier_open_early':
            next(e for e in events if e['stage']=='lineage_review_submission')['data']['barrier_open']=True
    try:
        tail=_rewrite_trace(trace,change)
        with pytest.raises(ContractError):
            verify_lineage_combination_cell(replace(result,runtime=replace(result.runtime,trace_digest=tail)),**args)
    finally:
        for path,data in saved.items(): path.write_bytes(data)


@pytest.mark.parametrize('fault', ['unknown','exception','scorer','solver_transport'])
def test_closed_controller_preserves_failed_cells_usage_and_full_denominator(tmp_path,monkeypatch,fault):
    result,port,calls,scores,source_calls,_=_run(tmp_path,monkeypatch,fault)
    assert len(result.results)==len(result.attempts)==result.receipt.data()['expected_cells']==34
    assert result.receipt.data()['pruned_cells']==[] and result.receipt.data()['status']=='inconclusive'
    first=result.attempts[0].data(); assert first['status']=='failed'
    assert first['model_usage_after']['model_calls']>=first['model_usage_before']['model_calls']
    if fault in {'unknown','exception'}:
        assert len(source_calls)==68 and len(calls)==132 and len(scores)==33
        assert len(first['source_verification']['calls'])==2
        if fault=='exception': assert first['source_verification']['calls'][0]['cost_unknown'] is True
    elif fault=='scorer':
        assert len(calls)==136 and len(scores)==34 and first['scorer_calls']==1 and len(result.scores)==33
    else:
        assert len(calls)==3 and len(scores)==0 and result.receipt.data()['blocked_cells']==33
        assert port.ledger['usage_incomplete'] is True
    assert result.contrasts[0].data()['status']=='inconclusive'


@pytest.mark.parametrize('fault',['analysis_invalid','answer_invalid','docker_failed','review_invalid'])
def test_original_rejected_response_and_failed_docker_remain_verifiable(tmp_path,monkeypatch,fault):
    from research_loop.modular.lineage_combination_driver import run_lineage_combination_cell
    sources=_sources([]); snapshot,custody,packets,config,_,_=_fixture(tmp_path,sources)
    compiled=compile_lineage_train_panels(config,packets); panel=compiled.panels[-1]
    cell=next(c for c in panel.cells if set(c.runtime_arm.data()['enabled'])=={'M2','M3','M5'})
    packet=next(p for p in packets if p.task.content_hash==cell.task_digest); calls=[]
    port=model_port(tmp_path/'port',monkeypatch,max_calls=136,max_tokens=1000,schemas=SCHEMAS,response_factory=_model(calls,fault))
    broker=DockerExecutionBroker([tmp_path/'material',tmp_path])
    args=dict(panel=panel,task=packet.task,scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],
        material=compiled.materials[cell.task_digest],source_verifier=sources,public_inputs={'public_csv':packet.csv_path},broker=broker)
    result=run_lineage_combination_cell(cell=cell,**args,objective=FrozenRecord.from_dict({'public':'synthetic'}),sidecar=tmp_path/'cell',
        image=IMAGE,model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))
    assert result.runtime.status=='failed' and result.runtime.output_digest is None
    assert verify_lineage_combination_cell(result,**args).data()['status']=='failed'


@pytest.mark.parametrize('fault',['source_bytes','missing_material','missing_arm','budget_bool','foreign_task','unknown_dependency'])
def test_bad_inputs_fail_before_any_authority_model_or_scorer_call(tmp_path,monkeypatch,fault):
    calls=[]; sources=_sources(calls); snapshot,custody,packets,config,scorer,handles=_fixture(tmp_path,sources)
    body=config.data()
    if fault=='source_bytes': packets[0].csv_path.write_bytes(b'x\n999\n')
    elif fault=='missing_material': body['materials_by_task'].pop(next(iter(body['materials_by_task'])))
    elif fault=='missing_arm': body['packages_by_arm'].pop(next(iter(body['packages_by_arm'])))
    elif fault=='budget_bool': body['allocation']['docker_attempts_per_cell']=True
    elif fault=='foreign_task': next(iter(body['materials_by_task'].values()))['task_digest']='0'*64
    else: next(iter(body['materials_by_task'].values()))['claims'][0]['depends_on']=['unbound']
    with pytest.raises(ContractError):
        config=FrozenLineageTrainConfig(FrozenRecord.from_dict(body)); compile_lineage_train_panels(config,packets)
    assert not calls


def test_evidence_root_representative_is_deterministic_across_fresh_processes(tmp_path):
    import os, subprocess, sys
    code = '''
import json, os, importlib.util, sys
from research_loop.modular.contracts import DataIdentity
if os.environ.get('LINEAGE_LEGACY_EVIDENCE'):
 spec=importlib.util.spec_from_file_location('legacy_evidence',os.environ['LINEAGE_LEGACY_EVIDENCE'])
 m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
 EvidenceLedger=m.EvidenceLedger
else:
 from research_loop.modular.modules.evidence import EvidenceLedger
i=DataIdentity('blade','t','g','v','s','train'); e=EvidenceLedger(i)
def add(representation,admitted,content,root='root'):
 return e.append({'kind':'observation','root_material':{'id':root},'content':{'value':content},'subject_bindings':{'task':'t'},'independent_group':'g','representation':representation}, {'trusted_validator':'public-fixture','validator_verified':True,'admitted':admitted})
r=add('raw',True,1); add('report',True,9); add('summary',True,7)
assert e.roots()[0].representation=='raw', 'same-root report replaced original raw record'
e.withdraw(r.root_id,'fixture withdrawal'); assert e.roots()==()
assert len(e.roots(active_only=False))==1
add('raw',False,2,'other'); add('report',True,3,'other')
assert e.roots()[0].representation=='report' and e.roots()[0].admitted, 'raw preference weakened admission semantics'
print('verified')
'''
    failures=[]
    for seed in range(8):
        env=dict(os.environ,PYTHONHASHSEED=str(seed),PYTHONDONTWRITEBYTECODE='1')
        process=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,encoding='utf-8')
        if process.returncode: failures.append((seed,process.stderr))
    assert failures==[], failures


def test_missing_structural_or_executable_cell_cannot_manufacture_contrast(grid):
    from research_loop.modular.combination_panels import CombinationPanelVerifier
    run=grid[0]
    for panel in run.compiled.panels:
        with pytest.raises(ContractError): replace(panel,cells=panel.cells[:-1])
        rows=[r.runtime for r in run.results if r.cell in panel.cells]
        with pytest.raises(ContractError): CombinationPanelVerifier().verify(panel,rows[:-1])
    assert run.compiled.panels[0].design.data()['contrast'] is None
    assert run.compiled.panels[-1].design.data()['contrast'] is None
    assert run.compiled.panels[2].design.data()['background']==['M2']


def test_withdrawal_context_does_not_turn_absent_support_into_refutation(tmp_path):
    from research_loop.modular.lineage_combination_driver import _transition
    from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
    from research_loop.modular.modules.context import ContextCache
    sources=_sources([]); _,_,packets,config,_,_=_fixture(tmp_path,sources)
    material=FrozenLineageMaterial(FrozenRecord.from_dict(config.data()['materials_by_task'][packets[0].task.content_hash]))
    evidence=EvidenceLedger(packets[0].task.identity)
    transition=_transition(evidence,ClaimLedger(evidence),ContextCache(),material,{'M2','M3'}).data()
    empty=next(c for c in transition['after_claims']['claims'] if not c['support_roots'] and not c['refute_roots'])
    assert empty['status']=='undetermined'
    entry=next(c for c in transition['public']['memory'] if c.get('claim_id')==empty['claim_id'])
    assert entry['status']=='undetermined'


@pytest.mark.parametrize('fault',['endpoint','response','metric','foreign_source'])
def test_independent_score_wrapper_binds_original_response_and_cell(grid,fault):
    from evaluation.modular.lineage_combination_scoring import verify_lineage_score
    run=grid[0]; score=run.scores[0]; cell=run.results[0].cell; panel=next(p for p in run.compiled.panels if cell in p.cells)
    attempt=next(r.data() for r in run.attempts if r.data()['cell']['task_digest']==cell.task_digest and r.data()['cell']['arm_id']==cell.arm_id and r.data()['cell']['coverage_id']==cell.coverage_id)
    source=FrozenRecord.from_dict(attempt['score_input']); body=score.receipt.data()['body']
    if fault=='endpoint': body['endpoints']['root_attribution']=1-body['endpoints']['root_attribution']
    elif fault=='response': body['rubric_response']['dimensions'][next(iter(body['rubric_response']['dimensions']))]=0.123
    elif fault=='metric': body['metric']['value']=0.123
    else: body['source_digest']='0'*64
    body.pop('authority')
    config=ScorerConfig.create(benchmark='core_pair',evaluator_id='synthetic-lineage-rubric',version='v1',
        rubric_digest=FrozenRecord.from_dict({'fixture_rubric':list(ENDPOINTS)}).content_hash)
    verify_lineage_score(score,authority_keys={SCORER.authority_id:SCORER.key},config=config,panel=panel,cell=cell,
        score_input=source,execution_authority_keys={EXECUTION.authority_id:EXECUTION.key})
    with pytest.raises(ContractError):
        verify_lineage_score(replace(score,receipt=SCORER.issue(body)),authority_keys={SCORER.authority_id:SCORER.key},
            config=config,panel=panel,cell=cell,score_input=source,
            execution_authority_keys={EXECUTION.authority_id:EXECUTION.key})
