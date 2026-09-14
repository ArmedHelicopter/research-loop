"""The frozen history candidate and actual qualified state feed one shared solve."""
from dataclasses import dataclass
from pathlib import Path
import json
import re
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel, DESIGNS, registered_design
from research_loop.modular.state_improvement_build import qualifier_check, FrozenProviderLedger
from research_loop.modular.admission_combination import FrozenAdmissionMaterial
from research_loop.modular.lineage_combination_material import check_material_inputs
from research_loop.modular.lineage_combination_driver import _transition, _source_binding, _MemoryLog, _read_events, _verify_solver_files
from research_loop.modular.metaprogram_training import _projection, _phase_rows
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.state_retrieval_combination_driver import _INSTRUCTIONS
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.context import ContextCache, ContextBuilder
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.runtime import RunSession, AuditVerifier
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.ontology import ContractError, canonical
from research_loop.modular.phase_provider import PhaseProviderLedger

from research_loop.modular.mechanism_improvement_modules import slots, apply_target_module, execute_retrieval, _verify_sources, public_retrieval
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.state_retrieval_combination_driver import FrozenStateRetrievalMaterial
from research_loop.modular.lineage_combination_material import DualMaterialVerifier


def _validate(panel,cell,task,scenario,package,material,source_verifier,barrier,retrieval_material,retrieval_verifier):
    from research_loop.modular.mechanism_improvement_combination_controller import CandidateBarrier
    if type(barrier) is not CandidateBarrier:
        raise ContractError('exact candidate barrier required for original build replay')
    if (type(panel) is not MechanismImprovementPanel or cell not in panel.cells or not isinstance(task,PublicTask)
            or task.identity!=cell.identity or task.content_hash!=cell.task_digest or not isinstance(package,CandidatePackage)
            or package.digest!=cell.package_digest or not isinstance(scenario,FrozenRecord) or scenario.content_hash!=cell.scenario_digest):
        raise ContractError('exact state improvement panel cell bindings required')
    qualifier_check(panel.obligation_id,material,source_verifier)
    if panel.obligation_id=='pair:M6+M9':
        if (type(retrieval_material) is not FrozenStateRetrievalMaterial or retrieval_material.state()!=material
                or type(retrieval_verifier) is not DualMaterialVerifier):
            raise ContractError('exact independently qualified corpus/state composition required')
    elif retrieval_material is not None or retrieval_verifier is not None:
        raise ContractError('retrieval cannot vary outside its target-only factor')
    barrier.verify()
    if barrier.package(panel.obligation_id,cell.arm_id)!=package:
        raise ContractError('target candidate differs from frozen build barrier')
    if panel.training_provenance!=barrier.provenance(): raise ContractError('panel exposure differs from immutable build barrier')
    expected={'schema':'mechanism-improvement-scenario-v1','pair':panel.obligation_id,'design_digest':panel.design.content_hash,
        'task_digest':task.content_hash,'material_digest':material.record.content_hash,'replicate':cell.replicate,
        'source_verifier_binding':source_verifier.binding().data(),'barrier_digest':barrier.record.content_hash,
        'objective':barrier.plan.data()['objective'],'image':barrier.plan.data()['image'],
        'timeout_seconds':barrier.plan.data()['timeout_seconds'],
        'retrieval_material_digest':retrieval_material.record.content_hash if retrieval_material else None,
        'retrieval_verifier_binding':retrieval_verifier.binding().data() if retrieval_verifier else None}
    if scenario.data()!=expected: raise ContractError('frozen target scenario drift')


@dataclass(frozen=True)
class MechanismImprovementResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    joint_mechanism: FrozenRecord


def run_mechanism_improvement_cell(*,panel,cell,task,scenario,package,material,source_verifier,barrier,
        sidecar,public_inputs,broker,model,audit_verifier,retrieval_material=None,retrieval_verifier=None,provider=None):
    _validate(panel,cell,task,scenario,package,material,source_verifier,barrier,retrieval_material,retrieval_verifier)
    if not isinstance(sidecar,Path) or sidecar.exists() or not isinstance(audit_verifier,AuditVerifier):
        raise ContractError('fresh target runtime required')
    check_material_inputs(material,task,broker,public_inputs)
    binding=_source_binding(cell);sourcepath=sidecar/'source-verification.json'
    source=source_verifier.qualify(material,sourcepath,cell_binding=binding)
    if any(c['cost_unknown'] for c in json.loads(sourcepath.read_bytes())['calls']):
        raise ContractError('unknown source cost blocks target model I/O')
    check_material_inputs(material,task,broker,public_inputs)
    barrier.verify()
    q=source_verifier.assessments(material,sourcepath,cell_binding=binding) if type(material) is FrozenAdmissionMaterial else None
    retrieval_source=None
    if retrieval_material is not None:
        retrievalpath=sidecar/'retrieval'/'source-verification.json'
        retrieval_source=retrieval_verifier.qualify(retrieval_material,retrievalpath,cell_binding=binding)
        if any(c['cost_unknown'] for c in json.loads(retrievalpath.read_bytes())['calls']):
            raise ContractError('unknown corpus qualification cost blocks target I/O')
        barrier.verify();check_material_inputs(material,task,broker,public_inputs)
    session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=FrozenRecord.from_dict(scenario.data()['objective']),
        slots=slots(cell.coverage_id),execution_limit=1,sidecar=sidecar/'runtime',verifier=audit_verifier,required_audit=('measurement',),
        context_budget=material.data()['context_budget_bytes'])
    workflow=ModularWorkflow(session)
    transition=_transition(session.evidence,session.claims,session.cache,material,workflow.enabled,q)
    session._record('mechanism_improvement_transition',{'transition':transition.data(),'source_sha256':source,
        'barrier_digest':barrier.record.content_hash,'retrieval_source_sha256':retrieval_source})
    joint=solver=None
    try:
        retrieval=execute_retrieval(session,task,retrieval_material,provider,'M6' in workflow.enabled) if retrieval_material else None
        joint=apply_target_module(cell=cell,task=task,package=package,transition=transition,predictions=workflow.predictions,
            reviews=workflow.reviews,invoke=lambda slot,instruction,context:workflow.invoke_model(slot,model,instruction=instruction,module_context=context),
            record=session._record,retrieval=retrieval)
        session._record('mechanism_improvement_joint',{'joint':joint.data(),'joint_digest':joint.content_hash})
        solver=run_benchmark_solve_in_session(session=session,workflow=workflow,public_inputs=public_inputs,
            image=scenario.data()['image'],broker=broker,model=model,analysis_slot='analysis_program',final_slot='final_answer',
            joint_mechanism=joint,panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),
            driver_id=cell.coverage_id,timeout_seconds=scenario.data()['timeout_seconds'])
    except Exception as exc:
        if not session._terminal:session.controller_failure(driver_id=cell.coverage_id,error_type=type(exc).__name__,panel_cell=opaque_panel_cell_binding(cell))
    status='succeeded' if solver is not None and solver.status=='execution_succeeded' else 'failed'
    return MechanismImprovementResult(cell,_runtime(cell,session,joint,status),solver,transition,joint)


def verify_mechanism_improvement_cell(result,*,panel,task,scenario,package,material,source_verifier,barrier,public_inputs,broker,ledger,retrieval_material=None,retrieval_verifier=None):
    if type(result) is not MechanismImprovementResult or type(ledger) is not (PhaseProviderLedger if barrier.plan.data()['schema'].endswith('-v2') else FrozenProviderLedger):
        raise ContractError('typed target result and sealed provider ledger required')
    cell=result.cell;_validate(panel,cell,task,scenario,package,material,source_verifier,barrier,retrieval_material,retrieval_verifier)
    check_material_inputs(material,task,broker,public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime,cell)
    path=result.runtime.trace_path;events=_read_events(path);lock=events[0]['data'];binding=_source_binding(cell)
    if (lock['objective']!=scenario.data()['objective'] or lock['slots']!=list(slots(cell.coverage_id)) or lock['execution_limit']!=1
            or lock['context_budget']!=material.data()['context_budget_bytes'] or lock['required_audit']!=['measurement']):
        raise ContractError('target allocation changed')
    sourcepath=path.parent.parent/'source-verification.json';source=source_verifier.replay(material,sourcepath,cell_binding=binding)
    if any(c['cost_unknown'] for c in json.loads(sourcepath.read_bytes())['calls']):
        raise ContractError('unknown source cost blocks target model I/O')
    q=source_verifier.assessments(material,sourcepath,cell_binding=binding) if type(material) is FrozenAdmissionMaterial else None
    evidence=EvidenceLedger(task.identity);claims=ClaimLedger(evidence);evidence._log=_MemoryLog();claims._log=_MemoryLog()
    transition=_transition(evidence,claims,ContextCache(),material,set(cell.runtime_arm.data()['enabled']),q)
    if (transition!=result.transition or _read_events(path.parent/'evidence.jsonl')!=evidence._log.rows
            or _read_events(path.parent/'claims.jsonl')!=claims._log.rows):
        raise ContractError('target state side effects differ from source replay')
    retrieval_source=None;retrieval=None
    if retrieval_material is not None:
        retrieval_source=retrieval_verifier.replay(retrieval_material,path.parent.parent/'retrieval'/'source-verification.json',cell_binding=binding)
        if any(c['cost_unknown'] for c in json.loads((path.parent.parent/'retrieval'/'source-verification.json').read_bytes())['calls']):
            raise ContractError('unknown corpus qualification cost blocks target I/O')
        projection=_verify_sources(events,task,retrieval_material.retrieval(),'M6' in cell.runtime_arm.data()['enabled'])
        retrieval=public_retrieval(projection)
    predictions=PredictionRegistry(task.identity);reviews=ReviewEngine(task.identity)
    predictions._log=_MemoryLog();reviews._log=_MemoryLog();module_records=[];module_requests={}
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    responses={e['data']['request_digest']:e['data']['response'] for e in events if e['stage']=='model_response'}
    module_cursor=0
    actual_owned=[(i,e) for i,e in enumerate(events) if e['stage'].startswith(('mechanism_improvement_prediction','mechanism_improvement_review_'))]
    if retrieval_material is not None:
        completed=[i for i,e in enumerate(events) if e['stage']=='retrieval_review_sources']
        if len(completed)!=1:raise ContractError('exact retrieval completion required')
        module_cursor=completed[0]
        if any(i>=module_cursor for i,e in enumerate(events) if e['stage'].startswith('q8_')):
            raise ContractError('retrieval bookkeeping continues after its completion')
    def replay_record(stage,data):
        nonlocal module_cursor
        if len(module_records)>=len(actual_owned):raise ContractError('missing original native module operation')
        index,event=actual_owned[len(module_records)]
        if index<=module_cursor or event['stage']!=stage or event['data']!=data:
            raise ContractError('native module operation must follow its original response')
        module_records.append({'stage':stage,'data':data});module_cursor=index
    def replay_invoke(slot,instruction,context):
        nonlocal module_cursor
        matching=[r for r in requests if r['slot']==slot]
        if len(matching)!=1:raise ContractError('module requires one original response per slot')
        request=matching[0]
        if request['instruction']!=instruction or request['module_context']!=context.data() or request['execution_feedback']!=[]:
            raise ContractError('target module context leaks future outcomes or changes useful control')
        request_digest=FrozenRecord.from_dict(request).content_hash
        request_events=[(i,e) for i,e in enumerate(events) if e['stage']=='model_request' and e['data']['request_digest']==request_digest]
        response_events=[(i,e) for i,e in enumerate(events) if e['stage'] in ('model_response','model_failure') and e['data']['request_digest']==request_digest]
        if (len(request_events)!=1 or request_events[0][0]<=module_cursor or len(response_events)!=1
                or response_events[0][0]<=request_events[0][0] or response_events[0][1]['stage']!='model_response'):
            raise ContractError('native module request and response order drift')
        module_cursor=response_events[0][0]
        module_requests[slot]=(instruction,context.data())
        return FrozenRecord.from_dict(response_events[0][1]['data']['response'])
    joint=apply_target_module(cell=cell,task=task,package=package,transition=transition,predictions=predictions,reviews=reviews,
        invoke=replay_invoke,record=replay_record,retrieval=retrieval)
    if (_read_events(path.parent/'predictions.jsonl')!=predictions._log.rows or _read_events(path.parent/'reviews.jsonl')!=reviews._log.rows):
        raise ContractError('native prediction/review persistent journals differ from replay')
    actual_modules=[{'stage':e['stage'],'data':e['data']} for e in events if e['stage'].startswith(('mechanism_improvement_prediction','mechanism_improvement_review_'))]
    if actual_modules!=module_records:raise ContractError('prediction/review order or sealed barrier changed')
    transitions=[e for e in events if e['stage']=='mechanism_improvement_transition'];joints=[e for e in events if e['stage']=='mechanism_improvement_joint']
    if (len(transitions)!=1 or transitions[0]['data']!={'transition':transition.data(),'source_sha256':source,
            'barrier_digest':barrier.record.content_hash,'retrieval_source_sha256':retrieval_source}
            or result.joint_mechanism!=joint or len(joints)!=1 or joints[0]['data']!={'joint':joint.data(),'joint_digest':joint.content_hash}):
        raise ContractError('target joint differs from original native module execution')
    if len(module_records)!=len(actual_owned) or events.index(joints[0])<=module_cursor:
        raise ContractError('joint must follow complete original native module operations')
    first=next((i for i,e in enumerate(events) if e['stage'] in ('model_request','q8_retrieval_request','execution_request')),len(events))
    solve=next(i for i,e in enumerate(events) if e['stage']=='model_request' and e['data']['request']['slot']=='analysis_program')
    if not events.index(transitions[0])<first or not events.index(joints[0])<solve:
        raise ContractError('qualification/module freeze must precede shared solve')
    if any(e['stage']=='execution_request' or e['stage']=='model_request' and e['data']['request']['slot'] in ('analysis_program','final_answer') for e in events[:events.index(joints[0])]):
        raise ContractError('module registration is not prospective to target execution')
    if any(events.index(e)>=events.index(joints[0]) for e in events if e['stage'].startswith(('mechanism_improvement_prediction','mechanism_improvement_review_'))):
        raise ContractError('native module registration occurs after target context freeze')
    if tuple(r['slot'] for r in requests)!=slots(cell.coverage_id)[:len(requests)] or any(_private_arm_marker(r) for r in requests):
        raise ContractError('target schedule or isolation drift')
    state=_solver_journal_state(events);_compare_solver_result(result.solver,state)
    if result.solver.session.sidecar!=path.parent or result.runtime.status!=('succeeded' if state['status']=='execution_succeeded' else 'failed'):
        raise ContractError('target solver result relabeled')
    cache=ContextCache();builder=ContextBuilder(task.identity,budget_bytes=material.data()['context_budget_bytes'])
    for request in requests:
        claims.refresh_after_withdrawal()
        context=cache.get_or_build(builder,canonical(task.payload.data()),evidence,claims,
            mode='candidate' if 'M3' in cell.runtime_arm.data()['enabled'] else 'baseline',baseline_summary='').public_data()
        if (request['context']!=context or set(request)!={'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}
                or request['schema']!='public-model-request-v1' or request['instruction']!=(module_requests[request['slot']][0] if request['slot'] in module_requests else _INSTRUCTIONS[request['slot']])):
            raise ContractError('shared target request contract drift')
        if request['slot'] in module_requests:continue
        module=request['module_context'];keys={'solver','public_artifacts','panel_cell','joint_mechanism','joint_mechanism_digest'}
        if request['slot']=='final_answer': keys|={'analysis','analysis_digest','analysis_program_sha256','execution_digest','execution_status',
            'execution_input_artifacts','execution_feedback','required_objective_digest'}
        if (set(module)!=keys or module['solver']!='public-benchmark-solve-v1' or module['panel_cell']!=opaque_panel_cell_binding(cell)
                or module['joint_mechanism']!=joint.data() or module['joint_mechanism_digest']!=joint.content_hash
                or request['slot']=='analysis_program' and request['execution_feedback']!=[]):
            raise ContractError('target request includes unselected proposal or omits candidate')
    _verify_solver_files(state,events,path,material)
    execution=state['execution']
    if execution is not None and execution.status!='rejected':
        argv=execution.record.data().get('argv')
        if not isinstance(argv,list) or len(argv)<6 or not isinstance(argv[5],str) or not re.fullmatch('research-loop-[0-9a-f]{20}',argv[5]):
            raise ContractError('missing actual bounded target Docker invocation')
        expected=['docker','run','--pull','never','--name',argv[5],'--rm','--network','none','--read-only',
            '--user','1000:1000','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--pids-limit','128','--memory','1g',
            '--cpus','1.0','--cap-drop','ALL','--security-opt','no-new-privileges']
        for key in sorted(public_inputs):
            expected.extend(['-v',DockerExecutionBroker._mount_source(public_inputs[key].absolute())+':/input/'+key+':ro'])
        expected.extend(['-v',DockerExecutionBroker._mount_source((path.parent/'analysis-1.py').absolute())+
            ':/task/analysis.py:ro',scenario.data()['image'],'python3','/task/analysis.py'])
        if argv!=expected: raise ContractError('target Docker limits or exact program/input mounts differ from frozen allocation')
    if cell.coverage_id=='pair:M4+M9' and result.runtime.status=='succeeded':
        try:measured=json.loads(execution.record.data()['stdout'])
        except (ValueError,TypeError) as exc:raise ContractError('fresh target measurement must be observable in actual execution') from exc
        if not isinstance(measured,dict) or 'target_statistic' not in measured:raise ContractError('declared prospective observable was not measured')
    seals=[r['data'] for r in _phase_rows(barrier.root/'controller.jsonl')
        if r['stage']=='target_ledger_sealed']
    if ledger.path!=barrier.root/'target-provider-ledger.json' or seals!=[{'digest':ledger.record.content_hash}]:
        raise ContractError('target provider ledger is not the original controller seal')
    if type(ledger) is PhaseProviderLedger:
        ledger.bind_events(events,scope_id='target:'+FrozenRecord.from_dict(cell.data()).content_hash)
    else: ledger.bind_events(events)
    return FrozenRecord.from_dict({'schema':'mechanism-improvement-verification-v1','engineering_verified':True,
        'cell_key':list(cell.key),'status':result.runtime.status,'barrier_digest':barrier.record.content_hash,'scientific_effect':'not_measured'})
