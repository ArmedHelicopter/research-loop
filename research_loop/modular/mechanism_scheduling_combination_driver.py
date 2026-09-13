"""Exact prospective TRAIN M4/M5/M6 x M8 execution and original-input replay."""
from dataclasses import dataclass
from pathlib import Path
import re

from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.modules.predictions import PredictionRegistry, _prediction
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.modules.retrieval import FrozenSourceBundle
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.lineage_combination_material import DualMaterialVerifier
from research_loop.modular.lineage_combination_driver import _MemoryLog, _read_events, _source_binding, _verify_solver_files
from research_loop.modular.exploration_scheduler_combination import (
    FrozenExplorationSchedulerMaterial, check_inputs, selection, run_phase, verify_phase, _joint as phase_public, _read, _hash)
from research_loop.modular.m4_m5_useful_controls import (
    PLAN_INSTRUCTION, ORDINARY_INSTRUCTION, REVIEW_INSTRUCTION, REVISION_INSTRUCTION, proposal_envelope, review_context)
from research_loop.modular.retrieval_review_combination_driver import (
    freeze_material as freeze_retrieval, check_material as check_retrieval, _verify_sources, admission_receipt, public_retrieval, BUDGET)
from research_loop.modular.retrieval_panel_drivers import _select_sources
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, _IMAGE
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.state_scheduling_combination_driver import _INSTRUCTIONS
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession, AuditVerifier
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

DESIGNS = {'pair:M4+M8': ('M4','M8'), 'pair:M5+M8': ('M5','M8'), 'pair:M6+M8': ('M6','M8')}
KINDS = {'pair:M4+M8':'prediction', 'pair:M5+M8':'review', 'pair:M6+M8':'retrieval'}
SLOTS = {'pair:M4+M8':('proposal','analysis_program','final_answer'),
    'pair:M5+M8':('review_first','review_second','analysis_program','final_answer'),
    'pair:M6+M8':('analysis_program','final_answer')}
ROLES = (('mechanism','Identify a plausible public mechanism and an observation that could falsify it.'),
    ('measurement','Identify a public measurement risk and an observation that could distinguish it.'))
MODULE_EVENTS = {'mechanism_prediction','mechanism_review_open','mechanism_review_submission','mechanism_review_reveal'}


def registered_design(pair, baseline):
    if pair not in DESIGNS: raise ContractError('unimplemented mechanism scheduling pair')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[pair])


def recipe(pair):
    if pair not in DESIGNS: raise ContractError('exact three pair recipe required')
    return FrozenRecord.from_dict({'schema':'mechanism-scheduling-recipe-v1','kind':KINDS[pair],
        'slots':list(SLOTS[pair]),'proposal_off':'useful_ordinary_three_branch','proposal_on':'registered_discriminating',
        'review_off':'useful_sequential_revision','review_on':'sealed_independent',
        'retrieval_budget':BUDGET if KINDS[pair]=='retrieval' else None,
        'phase_jobs':2,'phase_cost_units':2,'phase_policy':'fifo','phase_max_concurrency':2,'solver_docker_attempts':1,
        'proposal_instructions':[ORDINARY_INSTRUCTION,PLAN_INSTRUCTION],
        'review_instructions':[REVISION_INSTRUCTION,REVIEW_INSTRUCTION], 'review_roles':[list(r) for r in ROLES]})


def ordinary_proposal(response):
    b=proposal_envelope(response)
    fields={'hypothesis_id','mechanism_key','mechanism','intervention','predictions','elimination_condition'}
    for v in b['branches']:
        if (set(v)!=fields or any(not isinstance(v[k],str) or not v[k].strip() for k in fields-{'predictions'})
                or not isinstance(v['predictions'],list) or not v['predictions']): raise ContractError('complete ordinary explanatory branches required')
        for p in v['predictions']: _prediction(p)
    if len({v['hypothesis_id'] for v in b['branches']})!=3: raise ContractError('three unique ordinary branches required')
    return b


@dataclass(frozen=True)
class FrozenMechanismSchedulingMaterial:
    record: FrozenRecord
    def __post_init__(self):
        if type(self.record) is not FrozenRecord or len(self.record.encoded.encode())>524288: raise ContractError('bounded frozen composite required')
        b=self.data()
        if (set(b)!={'schema','identity','task_digest','kind','mechanism','scheduling','provenance'}
                or b['schema']!='mechanism-scheduling-material-v1' or b['kind'] not in set(KINDS.values())): raise ContractError('closed mechanism scheduling material required')
        DataIdentity.parse(b['identity']).require_train();jobs=self.scheduling();m=b['mechanism']
        if jobs.data()['identity']!=b['identity'] or jobs.data()['task_digest']!=b['task_digest']: raise ContractError('job task binding drift')
        if b['kind']=='prediction':
            if set(m)!={'question'} or not isinstance(m['question'],str) or not m['question'].strip(): raise ContractError('frozen public proposal question required')
        elif b['kind']=='review': ordinary_proposal(FrozenRecord.from_dict(m))
        elif m.get('identity')!=b['identity'] or m.get('task_digest')!=b['task_digest']: raise ContractError('retrieval task binding drift')
        if b['provenance']!={'identity':b['identity'],'task_digest':b['task_digest'],'jobs_digest':jobs.record.content_hash,
            'mechanism_digest':FrozenRecord.from_dict(m).content_hash,'origin':'caller_public_train_unvalidated'}: raise ContractError('original mechanism/job provenance drift')
    def data(self): return self.record.data()
    def scheduling(self): return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(self.data()['scheduling']))


def freeze_material(task, kind, mechanism, jobs):
    if type(task) is not PublicTask or type(jobs) is not FrozenExplorationSchedulerMaterial or type(mechanism) is not FrozenRecord: raise ContractError('exact public task and frozen component inputs required')
    result=FrozenMechanismSchedulingMaterial(FrozenRecord.from_dict({'schema':'mechanism-scheduling-material-v1',
        'identity':task.identity.data(),'task_digest':task.content_hash,'kind':kind,'mechanism':mechanism.data(),'scheduling':jobs.data(),
        'provenance':{'identity':task.identity.data(),'task_digest':task.content_hash,'jobs_digest':jobs.record.content_hash,
            'mechanism_digest':mechanism.content_hash,'origin':'caller_public_train_unvalidated'}}))
    if kind=='retrieval': check_retrieval(mechanism,task)
    return result


def _validate(panel,cell,task,scenario,package,material,source_verifier):
    if (type(panel) is not CombinationPanel or panel.obligation_id not in DESIGNS or cell not in panel.cells
            or panel.design!=registered_design(panel.obligation_id,cell.runtime_arm.data()['baseline_digest'])
            or type(task) is not PublicTask or task.identity!=cell.identity or task.content_hash!=cell.task_digest
            or type(package) is not CandidatePackage or package.digest!=cell.package_digest
            or type(material) is not FrozenMechanismSchedulingMaterial or type(source_verifier) is not DualMaterialVerifier
            or type(scenario) is not FrozenRecord or scenario.content_hash!=cell.scenario_digest): raise ContractError('exact mechanism scheduling cell dependencies required')
    b=scenario.data();expected={'schema':'mechanism-scheduling-scenario-v1','obligation_id':panel.obligation_id,
        'design_digest':panel.design.content_hash,'task_digest':task.content_hash,'replicate':cell.replicate,
        'material_digest':material.record.content_hash,'source_verifier_binding':source_verifier.binding().data(),
        'recipe':recipe(panel.obligation_id).data(),'objective':b.get('objective'),'image':b.get('image'),'timeout_seconds':b.get('timeout_seconds')}
    if (b!=expected or not isinstance(b['objective'],dict) or not b['objective'] or not isinstance(b['image'],str)
            or not _IMAGE.fullmatch(b['image']) or type(b['timeout_seconds']) is not int or not 1<=b['timeout_seconds']<=120
            or material.data()['kind']!=KINDS[panel.obligation_id]
            or freeze_material(task,material.data()['kind'],FrozenRecord.from_dict(material.data()['mechanism']),material.scheduling())!=material): raise ContractError('scenario recipe or original material binding drift')


class _MechanismResponseError(ContractError): pass
class _RecordedFailure(Exception): pass


def _mechanism(task,cell,material,enabled,predictions,reviews,request,record,retrieve):
    kind=material.data()['kind'];m=material.data()['mechanism'];binding=opaque_panel_cell_binding(cell)
    if kind=='prediction':
        response=request('proposal',PLAN_INSTRUCTION if 'M4' in enabled else ORDINARY_INSTRUCTION,
            {'panel_cell':binding,'public_task':task.data(),'question':m['question'],'mechanism_phase':'proposal'})
        try:
            b=ordinary_proposal(response)
            plan=predictions.freeze(b['question'],b['branches'],budget_units=3) if 'M4' in enabled else None
        except ContractError as exc: raise _MechanismResponseError(str(exc)) from exc
        record('mechanism_prediction',{'proposal':response.data(),'proposal_digest':response.content_hash,
            'registered_plan':plan.data() if plan else None})
        return FrozenRecord.from_dict({'kind':kind,'proposal':response.data(),'prediction_plan':plan.payload.data() if plan else None})
    if kind=='review':
        sealed='M5' in enabled;review=None;responses=[]
        if sealed:
            review=reviews.open(task_binding=task.content_hash,evidence_snapshot=FrozenRecord.from_dict(m).content_hash,
                roles=[{'role_id':role,'question':question} for role,question in ROLES],budget_units=2)
            record('mechanism_review_open',{'review':review.data()})
        for slot,(role,question) in zip(SLOTS[cell.coverage_id][:-2],ROLES,strict=True):
            response=request(slot,REVIEW_INSTRUCTION if sealed else REVISION_INSTRUCTION,
                review_context(binding=binding,task=task.data(),role=role,question=question,proposal=m,sealed=sealed,earlier=[r.data() for r in responses]))
            try:reviews._response(response.data())
            except ContractError as exc:raise _MechanismResponseError(str(exc)) from exc
            responses.append(response)
            if review:
                reviews.submit(review.review_id,role_id=role,reviewer_id=role,response=response.data(),cost_units=1)
                record('mechanism_review_submission',{'response_digest':response.content_hash,'barrier_open':reviews.barrier_open(review.review_id)})
        if review:record('mechanism_review_reveal',{'review_id':review.review_id,'submissions':[r.data() for r in reviews.reveal(review.review_id)]})
        return FrozenRecord.from_dict({'kind':kind,'proposal':m,'review_responses':[r.data() for r in responses]})
    projection=retrieve()
    return FrozenRecord.from_dict({'kind':kind,'retrieval':public_retrieval(projection)})


def _phase_objective(objective,mechanism,material):
    return FrozenRecord.from_dict({'solver_objective':objective.data(),'mechanism_digest':mechanism.content_hash,'composite_material_digest':material.record.content_hash})


def _joint(cell,mechanism,phase,material,package):
    changes=package.record.data()['changes']
    return FrozenRecord.from_dict({'schema':'mechanism-scheduling-public-joint-v1','panel_cell':opaque_panel_cell_binding(cell),
        'mechanism':mechanism.data(),'scheduling':phase_public(phase,material.scheduling()).data()['material'],
        'candidate_context':{'prompt':changes.get('prompt',{}),'memory':changes.get('memory',{})}})


@dataclass(frozen=True)
class MechanismSchedulingResult:
    cell: object
    runtime: object
    solver: object
    mechanism: FrozenRecord | None
    phase: FrozenRecord | None
    joint_mechanism: FrozenRecord | None


def run_mechanism_scheduling_cell(*,panel,cell,task,scenario,package,material,source_verifier,provider,
        objective,sidecar,public_inputs,image,broker,model,audit_verifier,timeout_seconds=20):
    _validate(panel,cell,task,scenario,package,material,source_verifier)
    if (not isinstance(sidecar,Path) or sidecar.exists() or type(objective) is not FrozenRecord or not callable(model)
            or not isinstance(audit_verifier,AuditVerifier) or not callable(getattr(provider,'search',None))
            or objective.data()!=scenario.data()['objective'] or image!=scenario.data()['image'] or timeout_seconds!=scenario.data()['timeout_seconds']): raise ContractError('runtime dependencies differ from frozen allocation')
    check_inputs(material.scheduling(),task,broker,public_inputs)
    source_hash=source_verifier.qualify(material,sidecar/'source-verification.json',cell_binding=_source_binding(cell))
    session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=objective,slots=SLOTS[cell.coverage_id],
        execution_limit=1,sidecar=sidecar/'runtime',verifier=audit_verifier,required_audit=('measurement',),context_budget=material.scheduling().data()['context_budget_bytes'])
    workflow=ModularWorkflow(session);mechanism=phase=joint=solver=None
    session._record('mechanism_scheduling_source',{'source_sha256':source_hash,'material_digest':material.record.content_hash})
    def request(slot,instruction,context):return workflow.invoke_model(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict(context))
    def retrieve():
        retrieval=FrozenRecord.from_dict(material.data()['mechanism']);docs=check_retrieval(retrieval,task);pool=FrozenSourceBundle('public-train-retrieval-pool-v1',docs)
        admitted=admission_receipt(task,pool);session._record('q8_source_admission',{'receipt':admitted.data(),'receipt_digest':admitted.content_hash})
        projection,usage=_select_sources(provider,session,docs,retrieval.data()['query'],BUDGET,'Q8.3','three_lane','M6' in workflow.enabled)
        session._record('retrieval_review_sources',{'projection':projection,'usage':usage});return projection
    try:
        mechanism=_mechanism(task,cell,material,workflow.enabled,workflow.predictions,workflow.reviews,request,session._record,retrieve)
        session._record('mechanism_scheduling_mechanism',{'mechanism':mechanism.data(),'mechanism_digest':mechanism.content_hash})
        phase_objective=_phase_objective(objective,mechanism,material)
        session._record('mechanism_scheduling_phase_start',{'objective':phase_objective.data(),'selection':selection(material.scheduling(),workflow.enabled).data()})
        phase=run_phase(material=material.scheduling(),cell=cell,objective=phase_objective,root=sidecar/'phase',broker=broker,inputs=public_inputs,image=image,timeout_seconds=timeout_seconds)
        session._record('mechanism_scheduling_phase',{'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(sidecar/'phase/receipt.json'))})
        if phase.data()['status']!='succeeded':raise ContractError('auxiliary phase failed')
        joint=_joint(cell,mechanism,phase,material,package)
        session._record('mechanism_scheduling_joint',{'joint':joint.data(),'joint_digest':joint.content_hash})
        solver=run_benchmark_solve_in_session(session=session,workflow=workflow,public_inputs=public_inputs,image=image,broker=broker,model=model,
            analysis_slot='analysis_program',final_slot='final_answer',joint_mechanism=joint,panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),driver_id=cell.coverage_id,timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:session.controller_failure(driver_id=cell.coverage_id,error_type=type(exc).__name__,panel_cell={
            'experiment_id':cell.coverage_id,'variant':cell.variant,'replicate':cell.replicate,'arm_id':cell.arm_id,'scenario_digest':cell.scenario_digest})
    return MechanismSchedulingResult(cell,_runtime(cell,session,joint,'succeeded' if solver and solver.status=='execution_succeeded' else 'failed'),solver,mechanism,phase,joint)


def _replay_mechanism(events,path,task,cell,material):
    enabled=set(cell.runtime_arm.data()['enabled']);predictions=PredictionRegistry(task.identity);reviews=ReviewEngine(task.identity)
    predictions._log=_MemoryLog();reviews._log=_MemoryLog();cursor=1;owned=[];response_error=None
    requests=[(i,e) for i,e in enumerate(events) if e['stage']=='model_request'];index=0
    actual_owned=[(i,e) for i,e in enumerate(events) if e['stage'] in MODULE_EVENTS]
    def record(stage,data):
        nonlocal cursor
        if len(owned)>=len(actual_owned):raise ContractError('missing actual module operation')
        i,e=actual_owned[len(owned)]
        if i<=cursor or e['stage']!=stage or e['data']!=data:raise ContractError('module operation content or order drift')
        owned.append((stage,data));cursor=i
    def request(slot,instruction,context):
        nonlocal cursor,index
        if index>=len(requests):raise ContractError('missing actual module request')
        i,event=requests[index];index+=1;r=event['data']['request'];digest=event['data']['request_digest']
        if i<=cursor or r['slot']!=slot or r['instruction']!=instruction or r['module_context']!=context or r['execution_feedback']!=[]:raise ContractError('module request recipe or ordering drift')
        responses=[(j,e) for j,e in enumerate(events) if e['stage'] in ('model_response','model_failure') and e['data']['request_digest']==digest]
        if len(responses)!=1 or responses[0][0]<=i:raise ContractError('actual module response binding drift')
        cursor,event=responses[0]
        if event['stage']=='model_failure':raise _RecordedFailure()
        return FrozenRecord.from_dict(event['data']['response'])
    def retrieve():
        nonlocal cursor
        if not any(e['stage']=='q8_source_admission' for e in events):raise ContractError('missing source admission')
        projection=_verify_sources(events,task,FrozenRecord.from_dict(material.data()['mechanism']),'M6' in enabled)
        if projection is None:
            if not any(e['stage']=='q8_retrieval_failure' for e in events):raise ContractError('missing recorded retrieval failure')
            raise _RecordedFailure()
        cursor=next(i for i,e in enumerate(events) if e['stage']=='retrieval_review_sources');return projection
    mechanism=None
    try:mechanism=_mechanism(task,cell,material,enabled,predictions,reviews,request,record,retrieve)
    except _MechanismResponseError as exc:
        response_error=type(exc).__name__
        if events[-1]['stage']!='controller_failure' or events[-1]['data']['error_type']!=response_error:raise ContractError('invalid module response lost its original failure')
    except _RecordedFailure:pass
    if len(owned)!=len(actual_owned):raise ContractError('unexpected module operations')
    for name,rows in [('predictions.jsonl',predictions._log.rows),('reviews.jsonl',reviews._log.rows),('evidence.jsonl',[]),('claims.jsonl',[])]:
        if _read_events(path.parent/name)!=rows:raise ContractError('persistent module journals differ from original response replay')
    if material.data()['kind']!='retrieval' and any(e['stage'].startswith('q8_') or e['stage']=='retrieval_review_sources' for e in events):raise ContractError('unallocated retrieval operations')
    return mechanism,cursor


def verify_mechanism_scheduling_cell(result,*,panel,task,scenario,package,material,source_verifier,public_inputs,broker):
    if type(result) is not MechanismSchedulingResult:raise ContractError('typed mechanism scheduling result required')
    cell=result.cell;_validate(panel,cell,task,scenario,package,material,source_verifier);check_inputs(material.scheduling(),task,broker,public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime,cell);path=result.runtime.trace_path;events=_read_events(path);lock=events[0]['data']
    if (lock['objective']!=scenario.data()['objective'] or lock['slots']!=list(SLOTS[cell.coverage_id]) or lock['execution_limit']!=1
            or lock['context_budget']!=material.scheduling().data()['context_budget_bytes'] or lock['required_audit']!=['measurement']):raise ContractError('frozen runtime allocation drift')
    source_hash=source_verifier.replay(material,path.parent.parent/'source-verification.json',cell_binding=_source_binding(cell))
    if events[1]['stage']!='mechanism_scheduling_source' or events[1]['data']!={'source_sha256':source_hash,'material_digest':material.record.content_hash}:raise ContractError('source qualification did not precede all module I/O')
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    if tuple(r['slot'] for r in requests)!=SLOTS[cell.coverage_id][:len(requests)] or any(_private_arm_marker(r) for r in requests):raise ContractError('solver schedule or label isolation drift')
    evidence=EvidenceLedger(task.identity);claims=ClaimLedger(evidence);cache=ContextCache();builder=ContextBuilder(task.identity,budget_bytes=lock['context_budget'])
    for r in requests:
        if (set(r)!={'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}
                or r['schema']!='public-model-request-v1' or r['context']!=cache.get_or_build(builder,canonical(task.payload.data()),evidence,claims,mode='baseline',baseline_summary='').public_data()):raise ContractError('model request schema or evidence context drift')
    mechanism,cursor=_replay_mechanism(events,path,task,cell,material)
    owned=[e for e in events if e['stage']=='mechanism_scheduling_mechanism']
    solver_requests=[r for r in requests if r['slot'] in ('analysis_program','final_answer')]
    if mechanism is None:
        if result.mechanism is not None or result.phase is not None or result.joint_mechanism is not None or result.solver is not None or result.runtime.status!='failed' or owned or solver_requests or (path.parent.parent/'phase').exists():raise ContractError('failed mechanism reached downstream work')
    else:
        if result.mechanism!=mechanism or len(owned)!=1 or owned[0]['data']!={'mechanism':mechanism.data(),'mechanism_digest':mechanism.content_hash} or events.index(owned[0])<=cursor:raise ContractError('mechanism differs from original module responses or order')
        objective=_phase_objective(FrozenRecord.from_dict(scenario.data()['objective']),mechanism,material)
        starts=[e for e in events if e['stage']=='mechanism_scheduling_phase_start'];ends=[e for e in events if e['stage']=='mechanism_scheduling_phase']
        phase=verify_phase(material=material.scheduling(),cell=cell,objective=objective,root=path.parent.parent/'phase',image=scenario.data()['image'],timeout_seconds=scenario.data()['timeout_seconds'],inputs=public_inputs)
        if (result.phase!=phase or len(starts)!=1 or starts[0]['data']!={'objective':objective.data(),'selection':selection(material.scheduling(),set(cell.runtime_arm.data()['enabled'])).data()}
                or len(ends)!=1 or ends[0]['data']!={'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(path.parent.parent/'phase/receipt.json'))}
                or not events.index(owned[0])<events.index(starts[0])<events.index(ends[0])):raise ContractError('phase original inputs, permit, budget or ordering drift')
        joints=[e for e in events if e['stage']=='mechanism_scheduling_joint']
        try:joint=_joint(cell,mechanism,phase,material,package)
        except ContractError:joint=None
        if phase.data()['status']!='succeeded' or joint is None:
            if result.solver is not None or result.joint_mechanism is not None or joints or solver_requests or result.runtime.status!='failed':raise ContractError('failed auxiliary phase reached solver')
        else:
            if result.joint_mechanism!=joint or len(joints)!=1 or joints[0]['data']!={'joint':joint.data(),'joint_digest':joint.content_hash}:raise ContractError('solver joint omits actual module or phase output')
            first=next((i for i,e in enumerate(events) if e['stage']=='model_request' and e['data']['request']['slot']=='analysis_program'),len(events))
            if not events.index(ends[0])<events.index(joints[0])<first or result.solver is None or result.solver.session.sidecar!=path.parent:raise ContractError('shared solver preceded original mechanism/phase completion')
            state=_solver_journal_state(events);_compare_solver_result(result.solver,state)
            if result.runtime.status!=('succeeded' if state['status']=='execution_succeeded' else 'failed'):raise ContractError('solver failure relabelled')
            _verify_solver_contract(state,events,path,material,scenario,public_inputs,joint)
    return FrozenRecord.from_dict({'schema':'mechanism-scheduling-verification-v1','engineering_verified':True,'cell_key':list(cell.key),'status':result.runtime.status,'scientific_effect':'not_measured'})


def _verify_solver_contract(state,events,path,material,scenario,public_inputs,joint):
    _verify_solver_files(state,events,path,material.scheduling())
    for request in [e['data']['request'] for e in events if e['stage']=='model_request' and e['data']['request']['slot'] in ('analysis_program','final_answer')]:
        context=request['module_context'];common={'solver','public_artifacts','panel_cell','joint_mechanism','joint_mechanism_digest'}
        final={'analysis','analysis_digest','analysis_program_sha256','execution_digest','execution_status','execution_input_artifacts','execution_feedback','required_objective_digest'}
        if (request['instruction']!=_INSTRUCTIONS[request['slot']] or set(context)!=common|(final if request['slot']=='final_answer' else set())
                or context.get('solver')!='public-benchmark-solve-v1' or context.get('panel_cell')!=joint.data()['panel_cell']
                or context.get('joint_mechanism')!=joint.data() or context.get('joint_mechanism_digest')!=joint.content_hash
                or request['slot']=='analysis_program' and request['execution_feedback']!=[]):raise ContractError('solver instructions or actual joint context drift')
    execution=state['execution']
    if execution is not None and execution.status!='rejected':
        argv=execution.record.data().get('argv')
        if not isinstance(argv,list) or len(argv)<6 or not isinstance(argv[5],str) or not re.fullmatch('research-loop-[0-9a-f]{20}',argv[5]):raise ContractError('missing actual bounded Docker invocation')
        expected=['docker','run','--pull','never','--name',argv[5],'--rm','--network','none','--read-only','--user','1000:1000','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--pids-limit','128','--memory','1g','--cpus','1.0','--cap-drop','ALL','--security-opt','no-new-privileges']
        for key in sorted(public_inputs):expected.extend(['-v',DockerExecutionBroker._mount_source(public_inputs[key].absolute())+':/input/'+key+':ro'])
        expected.extend(['-v',DockerExecutionBroker._mount_source((path.parent/'analysis-1.py').absolute())+':/task/analysis.py:ro',scenario.data()['image'],'python3','/task/analysis.py'])
        if argv!=expected:raise ContractError('solver Docker limits or mounts differ from frozen allocation')
