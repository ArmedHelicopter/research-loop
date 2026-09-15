"""Exact prospective TRAIN M1 x M4 x M7 execution and original-input replay."""
from dataclasses import dataclass
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.lineage_combination_material import check_material_inputs
from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
from research_loop.modular.csv_measurement_authorities import CsvMeasurementAdmissionMaterialVerifier
from research_loop.modular.lineage_combination_driver import _MemoryLog, _read_events, _source_binding, _transition
from research_loop.modular.exploration_scheduler_combination import (
    FrozenExplorationSchedulerMaterial, check_inputs, selection, _joint as phase_public, _read, _hash)
from research_loop.modular.m4_m5_useful_controls import PLAN_INSTRUCTION, ORDINARY_INSTRUCTION
from research_loop.modular.mechanism_exploration_combination_driver import ordinary_proposal, _verify_solver_contract
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, _IMAGE
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession, AuditVerifier
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.phase_host_artifacts import run_audited_phase, verify_audited_phase
from research_loop.ontology import ContractError, canonical

DESIGNS = {'triple:M1+M4+M7': ('M1','M4','M7')}
SLOTS = ('proposal','analysis_program','final_answer')
MODULE_EVENTS = {'admission_prediction_plan'}


def registered_design(pair, baseline):
    if pair not in DESIGNS: raise ContractError('unimplemented admission prediction exploration pair')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[pair])


def recipe(pair):
    if pair not in DESIGNS:raise ContractError('exact required triple recipe')
    return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-recipe-v1','slots':list(SLOTS),
        'state_input':'original_admission_transition','proposal_off':'useful_ordinary_three_branch',
        'proposal_on':'registered_discriminating','proposal_budget_units':3,
        'proposal_instructions':[ORDINARY_INSTRUCTION,PLAN_INSTRUCTION],
        'phase_jobs':2,'phase_cost_units':2,'phase_policy':'fifo','solver_docker_attempts':1})


@dataclass(frozen=True)
class FrozenAdmissionPredictionExplorationMaterial:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord or len(self.record.encoded.encode('utf-8')) > 524288:
            raise ContractError('bounded frozen composite material required')
        b = self.data()
        if (set(b) != {'schema', 'identity', 'task_digest', 'state_kind', 'state', 'exploration', 'provenance'}
                or b['schema'] != 'admission-prediction-exploration-material-v1' or b['state_kind'] != 'admission'):
            raise ContractError('closed composite material schema required')
        DataIdentity.parse(b['identity']).require_train()
        state, jobs = self.state(), self.exploration()
        for material in (state, jobs):
            if material.data()['identity'] != b['identity'] or material.data()['task_digest'] != b['task_digest']:
                raise ContractError('component identity differs from composite')
        if (state.data()['public_artifacts'] != jobs.data()['public_artifacts']
                or state.data()['context_budget_bytes'] != jobs.data()['context_budget_bytes']
                or b['provenance'] != {'identity': b['identity'], 'task_digest': b['task_digest'],
                    'jobs_digest': jobs.record.content_hash, 'origin': 'caller_public_train_unvalidated'}):
            raise ContractError('literal job TRAIN provenance or shared input binding drift')

    def data(self): return self.record.data()

    def state(self):
        return FrozenAdmissionMaterial(FrozenRecord.from_dict(self.data()['state']))

    def exploration(self):
        return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(self.data()['exploration']))


def freeze_material(task, state_material, jobs):
    if (type(task) is not PublicTask or task.identity.domain != 'train'
            or type(state_material) is not FrozenAdmissionMaterial
            or type(jobs) is not FrozenExplorationSchedulerMaterial):
        raise ContractError('TRAIN task and exact state and literal job material required')
    return FrozenAdmissionPredictionExplorationMaterial(FrozenRecord.from_dict({'schema': 'admission-prediction-exploration-material-v1',
        'identity': task.identity.data(), 'task_digest': task.content_hash,
        'state_kind': 'admission',
        'state': state_material.data(), 'exploration': jobs.data(),
        'provenance': {'identity': task.identity.data(), 'task_digest': task.content_hash,
            'jobs_digest': jobs.record.content_hash, 'origin': 'caller_public_train_unvalidated'}}))


def _validate(panel,cell,task,scenario,package,material,source_verifier):
    if (type(panel) is not CombinationPanel or panel.obligation_id not in DESIGNS or cell not in panel.cells
            or panel.design!=registered_design(panel.obligation_id,cell.runtime_arm.data()['baseline_digest'])
            or type(task) is not PublicTask or task.identity!=cell.identity or task.content_hash!=cell.task_digest
            or type(package) is not CandidatePackage or package.digest!=cell.package_digest
            or type(material) is not FrozenAdmissionPredictionExplorationMaterial
            or type(source_verifier) is not (CsvMeasurementAdmissionMaterialVerifier if 'csv_measurement' in source_verifier.binding().data() else AdmissionMaterialVerifier)
            or type(scenario) is not FrozenRecord or scenario.content_hash!=cell.scenario_digest): raise ContractError('exact admission prediction exploration cell dependencies required')
    b=scenario.data();expected={'schema':'admission-prediction-exploration-scenario-v1','obligation_id':panel.obligation_id,
        'design_digest':panel.design.content_hash,'task_digest':task.content_hash,'replicate':cell.replicate,
        'material_digest':material.record.content_hash,'source_verifier_binding':source_verifier.binding().data(),
        'recipe':recipe(panel.obligation_id).data(),'objective':b.get('objective'),'image':b.get('image'),'timeout_seconds':b.get('timeout_seconds')}
    if (b!=expected or not isinstance(b['objective'],dict) or not b['objective'] or not isinstance(b['image'],str)
            or not _IMAGE.fullmatch(b['image']) or type(b['timeout_seconds']) is not int or not 1<=b['timeout_seconds']<=120
            or freeze_material(task,material.state(),material.exploration())!=material): raise ContractError('scenario recipe or original material binding drift')


class _MechanismResponseError(ContractError): pass
class _RecordedFailure(Exception): pass


def _mechanism(task,cell,material,enabled,predictions,transition,request,record):
    response=request('proposal',PLAN_INSTRUCTION if 'M4' in enabled else ORDINARY_INSTRUCTION,
        {'panel_cell':opaque_panel_cell_binding(cell),'public_task':task.data(),
         'state_projection':transition.data()['public'],'question':material.state().data()['question'],'mechanism_phase':'proposal'})
    try:
        b=ordinary_proposal(response)
        plan=predictions.freeze(b['question'],b['branches'],budget_units=3) if 'M4' in enabled else None
    except ContractError as exc:raise _MechanismResponseError(str(exc)) from exc
    record('admission_prediction_plan',{'proposal':response.data(),'proposal_digest':response.content_hash,
        'registered_plan':plan.data() if plan else None})
    return FrozenRecord.from_dict({'state_projection':transition.data()['public'],'proposal':response.data(),
        'prediction_plan':plan.payload.data() if plan else None})


def _phase_objective(objective,mechanism,material):
    return FrozenRecord.from_dict({'solver_objective':objective.data(),'mechanism_digest':mechanism.content_hash,'composite_material_digest':material.record.content_hash})


def _joint(cell,mechanism,phase,material,package):
    changes=package.record.data()['changes']
    return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-public-joint-v1','panel_cell':opaque_panel_cell_binding(cell),
        'mechanism':mechanism.data(),'exploration':phase_public(phase,material.exploration()).data()['material'],
        'candidate_context':{'prompt':changes.get('prompt',{}),'memory':changes.get('memory',{})}})


@dataclass(frozen=True)
class AdmissionPredictionExplorationResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    mechanism: FrozenRecord | None
    phase: FrozenRecord | None
    joint_mechanism: FrozenRecord | None


def run_admission_prediction_exploration_cell(*,panel,cell,task,scenario,package,material,source_verifier,
        objective,sidecar,public_inputs,image,broker,model,audit_verifier,timeout_seconds=20):
    _validate(panel,cell,task,scenario,package,material,source_verifier)
    if (not isinstance(sidecar,Path) or sidecar.exists() or type(objective) is not FrozenRecord or not callable(model)
            or not isinstance(audit_verifier,AuditVerifier)
            or objective.data()!=scenario.data()['objective'] or image!=scenario.data()['image'] or timeout_seconds!=scenario.data()['timeout_seconds']): raise ContractError('runtime dependencies differ from frozen allocation')
    check_inputs(material.exploration(),task,broker,public_inputs)
    check_material_inputs(material.state(),task,broker,public_inputs)
    source_hash=source_verifier.qualify(material.state(),sidecar/'source-verification.json',cell_binding=_source_binding(cell))
    qualification=source_verifier.assessments(material.state(),sidecar/'source-verification.json',cell_binding=_source_binding(cell))
    session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=objective,slots=SLOTS,
        execution_limit=1,sidecar=sidecar/'runtime',verifier=audit_verifier,required_audit=('measurement',),context_budget=material.exploration().data()['context_budget_bytes'])
    workflow=ModularWorkflow(session);mechanism=phase=joint=solver=None
    session._record('admission_prediction_exploration_source',{'source_sha256':source_hash,'material_digest':material.record.content_hash})
    transition=_transition(session.evidence,session.claims,session.cache,material.state(),workflow.enabled,qualification)
    session._record('admission_prediction_transition',{'transition':transition.data(),'source_sha256':source_hash})
    def request(slot,instruction,context):return workflow.invoke_model(slot,model,instruction=instruction,module_context=FrozenRecord.from_dict(context))
    try:
        mechanism=_mechanism(task,cell,material,workflow.enabled,workflow.predictions,transition,request,session._record)
        session._record('admission_prediction_exploration_mechanism',{'mechanism':mechanism.data(),'mechanism_digest':mechanism.content_hash})
        phase_objective=_phase_objective(objective,mechanism,material)
        session._record('admission_prediction_exploration_phase_start',{'objective':phase_objective.data(),'selection':selection(material.exploration(),workflow.enabled).data()})
        phase=run_audited_phase(session=session, material=material.exploration(),cell=cell,objective=phase_objective,root=sidecar/'phase',broker=broker,inputs=public_inputs,image=image,timeout_seconds=timeout_seconds)
        session._record('admission_prediction_exploration_phase',{'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(sidecar/'phase/receipt.json'))})
        if phase.data()['status']!='succeeded':raise ContractError('auxiliary phase failed')
        joint=_joint(cell,mechanism,phase,material,package)
        session._record('admission_prediction_exploration_joint',{'joint':joint.data(),'joint_digest':joint.content_hash})
        solver=run_benchmark_solve_in_session(session=session,workflow=workflow,public_inputs=public_inputs,image=image,broker=broker,model=model,
            analysis_slot='analysis_program',final_slot='final_answer',joint_mechanism=joint,panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),driver_id=cell.coverage_id,timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:session.controller_failure(driver_id=cell.coverage_id,error_type=type(exc).__name__,panel_cell={
            'experiment_id':cell.coverage_id,'variant':cell.variant,'replicate':cell.replicate,'arm_id':cell.arm_id,'scenario_digest':cell.scenario_digest})
    return AdmissionPredictionExplorationResult(cell,_runtime(cell,session,joint,'succeeded' if solver and solver.status=='execution_succeeded' else 'failed'),solver,transition,mechanism,phase,joint)


def _replay_mechanism(events,path,task,cell,material,transition):
    enabled=set(cell.runtime_arm.data()['enabled']);predictions=PredictionRegistry(task.identity)
    predictions._log=_MemoryLog();cursor=2;owned=[];response_error=None
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
    mechanism=None
    try:mechanism=_mechanism(task,cell,material,enabled,predictions,transition,request,record)
    except _MechanismResponseError as exc:
        response_error=type(exc).__name__
        if events[-1]['stage']!='controller_failure' or events[-1]['data']['error_type']!=response_error:raise ContractError('invalid module response lost its original failure')
    except _RecordedFailure:pass
    if len(owned)!=len(actual_owned):raise ContractError('unexpected module operations')
    for name,rows in [('predictions.jsonl',predictions._log.rows),('reviews.jsonl',[])]:
        if _read_events(path.parent/name)!=rows:raise ContractError('persistent module journals differ from original response replay')
    if any(e['stage'].startswith('q8_') or e['stage']=='retrieval_review_sources' for e in events):raise ContractError('unallocated retrieval operations')
    return mechanism,cursor


def verify_admission_prediction_exploration_cell(result,*,panel,task,scenario,package,material,source_verifier,public_inputs,broker):
    if type(result) is not AdmissionPredictionExplorationResult:raise ContractError('typed admission prediction exploration result required')
    cell=result.cell;_validate(panel,cell,task,scenario,package,material,source_verifier);check_inputs(material.exploration(),task,broker,public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime,cell);path=result.runtime.trace_path;events=_read_events(path);lock=events[0]['data']
    if (lock['objective']!=scenario.data()['objective'] or lock['slots']!=list(SLOTS) or lock['execution_limit']!=1
            or lock['context_budget']!=material.exploration().data()['context_budget_bytes'] or lock['required_audit']!=['measurement']):raise ContractError('frozen runtime allocation drift')
    source_hash=source_verifier.replay(material.state(),path.parent.parent/'source-verification.json',cell_binding=_source_binding(cell))
    if events[1]['stage']!='admission_prediction_exploration_source' or events[1]['data']!={'source_sha256':source_hash,'material_digest':material.record.content_hash}:raise ContractError('source qualification did not precede all module I/O')
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    if tuple(r['slot'] for r in requests)!=SLOTS[:len(requests)] or any(_private_arm_marker(r) for r in requests):raise ContractError('solver schedule or label isolation drift')
    qualification=source_verifier.assessments(material.state(),path.parent.parent/'source-verification.json',cell_binding=_source_binding(cell))
    evidence=EvidenceLedger(task.identity);claims=ClaimLedger(evidence);cache=ContextCache()
    evidence._log=_MemoryLog();claims._log=_MemoryLog()
    transition=_transition(evidence,claims,cache,material.state(),set(cell.runtime_arm.data()['enabled']),qualification)
    if (transition!=result.transition or _read_events(path.parent/'evidence.jsonl')!=evidence._log.rows
            or _read_events(path.parent/'claims.jsonl')!=claims._log.rows
            or events[2]['stage']!='admission_prediction_transition'
            or events[2]['data']!={'transition':transition.data(),'source_sha256':source_hash}):raise ContractError('original admission transition or persistent journal drift')
    builder=ContextBuilder(task.identity,budget_bytes=lock['context_budget'])
    for r in requests:
        if (set(r)!={'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}
                or r['schema']!='public-model-request-v1' or r['context']!=cache.get_or_build(builder,canonical(task.payload.data()),evidence,claims,mode='baseline',baseline_summary='').public_data()):raise ContractError('model request schema or evidence context drift')
    mechanism,cursor=_replay_mechanism(events,path,task,cell,material,transition)
    owned=[e for e in events if e['stage']=='admission_prediction_exploration_mechanism']
    solver_requests=[r for r in requests if r['slot'] in ('analysis_program','final_answer')]
    if mechanism is None:
        if result.mechanism is not None or result.phase is not None or result.joint_mechanism is not None or result.solver is not None or result.runtime.status!='failed' or owned or solver_requests or (path.parent.parent/'phase').exists():raise ContractError('failed mechanism reached downstream work')
    else:
        if result.mechanism!=mechanism or len(owned)!=1 or owned[0]['data']!={'mechanism':mechanism.data(),'mechanism_digest':mechanism.content_hash} or events.index(owned[0])<=cursor:raise ContractError('mechanism differs from original module responses or order')
        objective=_phase_objective(FrozenRecord.from_dict(scenario.data()['objective']),mechanism,material)
        starts=[e for e in events if e['stage']=='admission_prediction_exploration_phase_start'];ends=[e for e in events if e['stage']=='admission_prediction_exploration_phase']
        phase=verify_audited_phase(trace_path=path, material=material.exploration(),cell=cell,objective=objective,root=path.parent.parent/'phase',image=scenario.data()['image'],timeout_seconds=scenario.data()['timeout_seconds'],inputs=public_inputs)
        if (result.phase!=phase or len(starts)!=1 or starts[0]['data']!={'objective':objective.data(),'selection':selection(material.exploration(),set(cell.runtime_arm.data()['enabled'])).data()}
                or len(ends)!=1 or ends[0]['data']!={'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(path.parent.parent/'phase/receipt.json'))}
                or not events.index(owned[0])<events.index(starts[0])<events.index(ends[0])):raise ContractError('phase original inputs, permit, budget or ordering drift')
        joints=[e for e in events if e['stage']=='admission_prediction_exploration_joint']
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
    return FrozenRecord.from_dict({'schema':'admission-prediction-exploration-verification-v1','engineering_verified':True,'cell_key':list(cell.key),'status':result.runtime.status,'scientific_effect':'not_measured'})

