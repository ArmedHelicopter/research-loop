"""The frozen history candidate and actual qualified state feed one shared solve."""
from dataclasses import dataclass
from pathlib import Path
import json
import re
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS, registered_design
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

SLOTS=('analysis_program','final_answer')


def _validate(panel,cell,task,scenario,package,material,source_verifier,barrier):
    from research_loop.modular.state_improvement_combination_controller import CandidateBarrier
    if type(barrier) is not CandidateBarrier:
        raise ContractError('exact candidate barrier required for original build replay')
    if (type(panel) is not StateImprovementPanel or cell not in panel.cells or not isinstance(task,PublicTask)
            or task.identity!=cell.identity or task.content_hash!=cell.task_digest or not isinstance(package,CandidatePackage)
            or package.digest!=cell.package_digest or not isinstance(scenario,FrozenRecord) or scenario.content_hash!=cell.scenario_digest):
        raise ContractError('exact state improvement panel cell bindings required')
    qualifier_check(panel.obligation_id,material,source_verifier)
    barrier.verify()
    if barrier.package(panel.obligation_id,cell.arm_id)!=package:
        raise ContractError('target candidate differs from frozen build barrier')
    if panel.training_provenance!=barrier.provenance(): raise ContractError('panel exposure differs from immutable build barrier')
    expected={'schema':'state-improvement-scenario-v1','pair':panel.obligation_id,'design_digest':panel.design.content_hash,
        'task_digest':task.content_hash,'material_digest':material.record.content_hash,'replicate':cell.replicate,
        'source_verifier_binding':source_verifier.binding().data(),'barrier_digest':barrier.record.content_hash,
        'objective':barrier.plan.data()['objective'],'image':barrier.plan.data()['image'],
        'timeout_seconds':barrier.plan.data()['timeout_seconds']}
    if scenario.data()!=expected: raise ContractError('frozen target scenario drift')


@dataclass(frozen=True)
class StateImprovementResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    joint_mechanism: FrozenRecord


def _joint(cell,transition,package):
    return FrozenRecord.from_dict({'schema':'state-improvement-public-joint-v1',
        'panel_cell':opaque_panel_cell_binding(cell),'state_projection':transition.data()['public'],
        'candidate_context':_projection(package).data()})


def run_state_improvement_cell(*,panel,cell,task,scenario,package,material,source_verifier,barrier,
        sidecar,public_inputs,broker,model,audit_verifier):
    _validate(panel,cell,task,scenario,package,material,source_verifier,barrier)
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
    session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=FrozenRecord.from_dict(scenario.data()['objective']),
        slots=SLOTS,execution_limit=1,sidecar=sidecar/'runtime',verifier=audit_verifier,required_audit=('measurement',),
        context_budget=material.data()['context_budget_bytes'])
    workflow=ModularWorkflow(session)
    transition=_transition(session.evidence,session.claims,session.cache,material,workflow.enabled,q)
    session._record('state_improvement_transition',{'transition':transition.data(),'source_sha256':source,
        'barrier_digest':barrier.record.content_hash})
    joint=_joint(cell,transition,package)
    session._record('state_improvement_joint',{'joint':joint.data(),'joint_digest':joint.content_hash})
    solver=run_benchmark_solve_in_session(session=session,workflow=workflow,public_inputs=public_inputs,
        image=scenario.data()['image'],broker=broker,model=model,analysis_slot=SLOTS[0],final_slot=SLOTS[1],
        joint_mechanism=joint,panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),
        driver_id=cell.coverage_id,timeout_seconds=scenario.data()['timeout_seconds'])
    return StateImprovementResult(cell,_runtime(cell,session,joint,'succeeded' if solver.status=='execution_succeeded' else 'failed'),
        solver,transition,joint)


def verify_state_improvement_cell(result,*,panel,task,scenario,package,material,source_verifier,barrier,public_inputs,broker,ledger):
    if type(result) is not StateImprovementResult or type(ledger) is not FrozenProviderLedger:
        raise ContractError('typed target result and sealed provider ledger required')
    cell=result.cell;_validate(panel,cell,task,scenario,package,material,source_verifier,barrier)
    check_material_inputs(material,task,broker,public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime,cell)
    path=result.runtime.trace_path;events=_read_events(path);lock=events[0]['data'];binding=_source_binding(cell)
    if (lock['objective']!=scenario.data()['objective'] or lock['slots']!=list(SLOTS) or lock['execution_limit']!=1
            or lock['context_budget']!=material.data()['context_budget_bytes'] or lock['required_audit']!=['measurement']):
        raise ContractError('target allocation changed')
    sourcepath=path.parent.parent/'source-verification.json';source=source_verifier.replay(material,sourcepath,cell_binding=binding)
    q=source_verifier.assessments(material,sourcepath,cell_binding=binding) if type(material) is FrozenAdmissionMaterial else None
    evidence=EvidenceLedger(task.identity);claims=ClaimLedger(evidence);evidence._log=_MemoryLog();claims._log=_MemoryLog()
    transition=_transition(evidence,claims,ContextCache(),material,set(cell.runtime_arm.data()['enabled']),q)
    if (transition!=result.transition or _read_events(path.parent/'evidence.jsonl')!=evidence._log.rows
            or _read_events(path.parent/'claims.jsonl')!=claims._log.rows):
        raise ContractError('target state side effects differ from source replay')
    transitions=[e for e in events if e['stage']=='state_improvement_transition'];joints=[e for e in events if e['stage']=='state_improvement_joint']
    joint=_joint(cell,transition,package)
    if (len(transitions)!=1 or transitions[0]['data']!={'transition':transition.data(),'source_sha256':source,'barrier_digest':barrier.record.content_hash}
            or result.joint_mechanism!=joint or len(joints)!=1 or joints[0]['data']!={'joint':joint.data(),'joint_digest':joint.content_hash}):
        raise ContractError('target joint differs from actual state or selected candidate')
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    first=next((i for i,e in enumerate(events) if e['stage'] in ('model_request','execution_request')),len(events))
    if not events.index(transitions[0])<events.index(joints[0])<first: raise ContractError('joint was not frozen before target I/O')
    if tuple(r['slot'] for r in requests)!=SLOTS[:len(requests)] or any(_private_arm_marker(r) for r in requests):
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
                or request['schema']!='public-model-request-v1' or request['instruction']!=_INSTRUCTIONS[request['slot']]):
            raise ContractError('shared target request contract drift')
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
    seals=[r['data'] for r in _phase_rows(barrier.root/'controller.jsonl')
        if r['stage']=='target_ledger_sealed']
    if ledger.path!=barrier.root/'target-provider-ledger.json' or seals!=[{'digest':ledger.record.content_hash}]:
        raise ContractError('target provider ledger is not the original controller seal')
    ledger.bind_events(events)
    return FrozenRecord.from_dict({'schema':'state-improvement-verification-v1','engineering_verified':True,
        'cell_key':list(cell.key),'status':result.runtime.status,'barrier_digest':barrier.record.content_hash,'scientific_effect':'not_measured'})
