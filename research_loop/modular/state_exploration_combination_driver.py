"""TRAIN-only M1/M2/M3 x M7, with independently replayed frozen inputs.

Signed state qualification binds the composite scenario and its original literal jobs.
Neither provenance signatures nor execution success establish scientific validity.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask, DataIdentity
from research_loop.modular.lineage_combination_driver import _transition, _source_binding, _MemoryLog, _read_events, _verify_solver_files
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, check_material_inputs
from research_loop.modular.modules.context import ContextCache, ContextBuilder
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.exploration_scheduler_combination import (
    FrozenExplorationSchedulerMaterial, check_inputs, selection, run_phase, verify_phase,
    _joint as phase_public, _read, _hash)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

DESIGNS = {'pair:M1+M7': ('M1', 'M7'), 'pair:M2+M7': ('M2', 'M7'), 'pair:M3+M7': ('M3', 'M7')}
SLOTS = ('analysis_program', 'final_answer')
# The shared solver seam has two fixed public request contracts. Keep them exact
# so a rehashed trace cannot replace instructions while preserving its context.
_INSTRUCTIONS = {
    'analysis_program': ('Write a Python analysis program for the supplied public task and only the named /input files. '
        'Use the supplied joint mechanism context only as train-only reasoning context. '
        'Return exactly analysis and program; the program must print concise task-relevant observations.'),
    'final_answer': ('Give the benchmark answer using only the public task, joint mechanism context, and recorded execution feedback. '
        'Return exactly objective_digest, outcome, evidence_ids, conclusion, and programme_complete. '
        'Copy module_context.required_objective_digest; set outcome to unknown, evidence_ids to [], and programme_complete to false.'),
}



def registered_design(obligation, baseline):
    if obligation not in DESIGNS:
        raise ContractError('unimplemented state/exploration combination')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[obligation])


@dataclass(frozen=True)
class FrozenStateExplorationMaterial:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord or len(self.record.encoded.encode('utf-8')) > 524288:
            raise ContractError('bounded frozen composite material required')
        b = self.data()
        if (set(b) != {'schema', 'identity', 'task_digest', 'state_kind', 'state', 'exploration', 'provenance'}
                or b['schema'] != 'state-exploration-material-v1' or b['state_kind'] not in ('admission', 'lineage')):
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
        cls = FrozenAdmissionMaterial if self.data()['state_kind'] == 'admission' else FrozenLineageMaterial
        return cls(FrozenRecord.from_dict(self.data()['state']))

    def exploration(self):
        return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(self.data()['exploration']))


def freeze_material(task, state_material, jobs):
    if (type(task) is not PublicTask or task.identity.domain != 'train'
            or type(state_material) not in (FrozenAdmissionMaterial, FrozenLineageMaterial)
            or type(jobs) is not FrozenExplorationSchedulerMaterial):
        raise ContractError('TRAIN task and exact state and literal job material required')
    return FrozenStateExplorationMaterial(FrozenRecord.from_dict({'schema': 'state-exploration-material-v1',
        'identity': task.identity.data(), 'task_digest': task.content_hash,
        'state_kind': 'admission' if type(state_material) is FrozenAdmissionMaterial else 'lineage',
        'state': state_material.data(), 'exploration': jobs.data(),
        'provenance': {'identity': task.identity.data(), 'task_digest': task.content_hash,
            'jobs_digest': jobs.record.content_hash, 'origin': 'caller_public_train_unvalidated'}}))


def _validate(panel, cell, task, scenario, package, material, source_verifier):
    if (not isinstance(panel, CombinationPanel) or panel.obligation_id not in DESIGNS or cell not in panel.cells
            or panel.design != registered_design(panel.obligation_id, cell.runtime_arm.data()['baseline_digest'])
            or not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest
            or not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or type(material) is not FrozenStateExplorationMaterial):
        raise ContractError('state/exploration frozen cell binding mismatch')
    state = material.state(); admission = panel.obligation_id == 'pair:M1+M7'
    if (type(state) is not (FrozenAdmissionMaterial if admission else FrozenLineageMaterial)
            or type(source_verifier) is not (AdmissionMaterialVerifier if admission else DualMaterialVerifier)):
        raise ContractError('obligation requires its exact state and provenance verifiers')
    expected = {'schema': 'state-exploration-combination-scenario-v1', 'obligation_id': panel.obligation_id,
        'design_digest': panel.design.content_hash, 'task_digest': task.content_hash,
        'replicate': cell.replicate, 'material_digest': material.record.content_hash,
        'source_verifier_binding': source_verifier.binding().data(),
        'objective': scenario.data().get('objective'), 'image': scenario.data().get('image'),
        'timeout_seconds': scenario.data().get('timeout_seconds')}
    from research_loop.modular.benchmarks.execution import _IMAGE
    if not isinstance(expected['objective'], dict) or not expected['objective']:
        raise ContractError('scenario must freeze the public solver objective')
    if not isinstance(expected['image'], str) or not _IMAGE.fullmatch(expected['image']):
        raise ContractError('scenario requires a digest-pinned image')
    if type(expected['timeout_seconds']) is not int or not 1 <= expected['timeout_seconds'] <= 120 or scenario.data() != expected:
        raise ContractError('scenario must freeze exact material and configured authority keys')
    if freeze_material(task, state, material.exploration()) != material:
        raise ContractError('composite material reconstruction drift')
    return state, material.exploration()



@dataclass(frozen=True)
class StateExplorationResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    phase: FrozenRecord | None
    joint_mechanism: FrozenRecord | None


def _joint(cell, transition, projection, package, material):
    changes = package.record.data()['changes']
    return FrozenRecord.from_dict({'schema': 'state-exploration-public-joint-v1',
        'panel_cell': opaque_panel_cell_binding(cell), 'state_projection': transition.data()['public'],
        'exploration': phase_public(projection, material).data()['material'],
        'candidate_context': {'prompt': changes.get('prompt', {}), 'memory': changes.get('memory', {})}})


def _phase_objective(objective, transition, material):
    return FrozenRecord.from_dict({'solver_objective': objective.data(),
        'state_transition_digest': transition.content_hash, 'composite_material_digest': material.record.content_hash})


def run_state_exploration_cell(*, panel, cell, task, scenario, package, material, source_verifier,
        objective, sidecar, public_inputs, image, broker, model, audit_verifier, timeout_seconds=20):
    state, jobs = _validate(panel, cell, task, scenario, package, material, source_verifier)
    if (not isinstance(sidecar, Path) or sidecar.exists()
            or not isinstance(objective, FrozenRecord) or not callable(model) or not isinstance(audit_verifier, AuditVerifier)
            or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120):
        raise ContractError('closed runtime dependencies required')
    check_material_inputs(state, task, broker, public_inputs)
    check_inputs(material.exploration(), task, broker, public_inputs)
    if objective.data() != scenario.data()['objective'] or image != scenario.data()['image'] or timeout_seconds != scenario.data()['timeout_seconds']:
        raise ContractError('runtime objective or execution allocation differs from frozen scenario')
    binding = _source_binding(cell)
    source_path = sidecar / 'source-verification.json'
    source_hash = source_verifier.qualify(state, source_path, cell_binding=binding)
    qualification = source_verifier.assessments(state, source_path, cell_binding=binding) if type(state) is FrozenAdmissionMaterial else None
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
        slots=SLOTS, execution_limit=1, sidecar=sidecar / 'runtime', verifier=audit_verifier,
        required_audit=('measurement',), context_budget=state.data()['context_budget_bytes'])
    workflow = ModularWorkflow(session)
    transition = _transition(session.evidence, session.claims, session.cache, state, workflow.enabled, qualification)
    session._record('state_exploration_transition', {'transition': transition.data(), 'source_sha256': source_hash})
    phase = joint = solver = None
    try:
        phase_objective = _phase_objective(objective, transition, material)
        session._record('state_exploration_phase_start', {'objective': phase_objective.data(),
            'selection': selection(jobs, workflow.enabled).data()})
        phase = run_phase(material=jobs, cell=cell, objective=phase_objective, root=sidecar/'phase',
            broker=broker, inputs=public_inputs, image=image, timeout_seconds=timeout_seconds)
        session._record('state_exploration_phase', {'phase_digest': phase.content_hash,
            'phase_receipt_sha256': _hash(_read(sidecar/'phase/receipt.json'))})
        if phase.data()['status'] != 'succeeded': raise ContractError('auxiliary execution failed')
        joint = _joint(cell, transition, phase, package, jobs)
        session._record('state_exploration_joint', {'joint': joint.data(), 'joint_digest': joint.content_hash})
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=public_inputs,
            image=image, broker=broker, model=model, analysis_slot=SLOTS[0], final_slot=SLOTS[1],
            joint_mechanism=joint, panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),
            driver_id=cell.coverage_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=cell.coverage_id, error_type=type(exc).__name__, panel_cell={
                'experiment_id': cell.coverage_id, 'variant': cell.variant, 'replicate': cell.replicate,
                'arm_id': cell.arm_id, 'scenario_digest': cell.scenario_digest})
    status = 'succeeded' if solver is not None and solver.status == 'execution_succeeded' else 'failed'
    return StateExplorationResult(cell, _runtime(cell, session, joint, status), solver, transition, phase, joint)


def verify_state_exploration_cell(result, *, panel, task, scenario, package, material, source_verifier,
         public_inputs, broker):
    """Read-only replay of original signed inputs, actual module journals and solve."""
    if type(result) is not StateExplorationResult:
        raise ContractError('typed state/exploration result required')
    cell = result.cell
    state, _ = _validate(panel, cell, task, scenario, package, material, source_verifier)
    check_material_inputs(state, task, broker, public_inputs)
    check_inputs(material.exploration(), task, broker, public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime, cell)
    path = result.runtime.trace_path; events = _read_events(path); binding = _source_binding(cell)
    lock = events[0]['data']
    if (lock['objective'] != scenario.data()['objective'] or lock['slots'] != list(SLOTS)
            or lock['execution_limit'] != 1 or lock['context_budget'] != state.data()['context_budget_bytes']
            or lock['required_audit'] != ['measurement']):
        raise ContractError('runtime allocation or objective differs from frozen scenario')
    source_path = path.parent.parent / 'source-verification.json'
    source_hash = source_verifier.replay(state, source_path, cell_binding=binding)
    qualification = source_verifier.assessments(state, source_path, cell_binding=binding) if type(state) is FrozenAdmissionMaterial else None
    evidence = EvidenceLedger(task.identity); claims = ClaimLedger(evidence)
    evidence._log = _MemoryLog(); claims._log = _MemoryLog()
    transition = _transition(evidence, claims, ContextCache(), state, set(cell.runtime_arm.data()['enabled']), qualification)
    if (transition != result.transition or _read_events(path.parent / 'evidence.jsonl') != evidence._log.rows
            or _read_events(path.parent / 'claims.jsonl') != claims._log.rows):
        raise ContractError('state journals differ from original qualification and transition replay')
    transitions = [e for e in events if e['stage'] == 'state_exploration_transition']
    if len(transitions) != 1 or transitions[0]['data'] != {'transition': transition.data(), 'source_sha256': source_hash}:
        raise ContractError('state transition lost its original source binding')
    phase_objective = _phase_objective(FrozenRecord.from_dict(scenario.data()['objective']), transition, material)
    starts = [e for e in events if e['stage'] == 'state_exploration_phase_start']
    completions = [e for e in events if e['stage'] == 'state_exploration_phase']
    expected_start = {'objective': phase_objective.data(),
        'selection': selection(material.exploration(), set(cell.runtime_arm.data()['enabled'])).data()}
    phase = verify_phase(material=material.exploration(), cell=cell, objective=phase_objective,
        root=path.parent.parent/'phase', image=scenario.data()['image'],
        timeout_seconds=scenario.data()['timeout_seconds'], inputs=public_inputs)
    if (phase != result.phase or len(starts) != 1 or starts[0]['data'] != expected_start
            or len(completions) != 1 or completions[0]['data'] != {'phase_digest': phase.content_hash,
                'phase_receipt_sha256': _hash(_read(path.parent.parent/'phase/receipt.json'))}
            or not events.index(transitions[0]) < events.index(starts[0]) < events.index(completions[0])):
        raise ContractError('actual phase, permit, budget or state-before-phase operation binding drift')
    requests = [e['data']['request'] for e in events if e['stage'] == 'model_request']
    if tuple(r['slot'] for r in requests) != SLOTS[:len(requests)] or any(_private_arm_marker(r) for r in requests):
        raise ContractError('solver schedule or public isolation drift')
    joints = [e for e in events if e['stage'] == 'state_exploration_joint']
    try:
        joint = _joint(cell, transition, phase, package, material.exploration())
    except ContractError:
        joint = None
    if phase.data()['status'] != 'succeeded' or joint is None:
        if result.joint_mechanism is not None or joints or requests or result.solver is not None or result.runtime.status != 'failed':
            raise ContractError('failed or invalid phase reached unbound solver')
    else:
        if result.joint_mechanism != joint or len(joints) != 1 or joints[0]['data'] != {'joint': joint.data(), 'joint_digest': joint.content_hash}:
            raise ContractError('joint differs from actual state and literal job execution')
        first_solver = next((i for i, e in enumerate(events) if e['stage'] in ('model_request', 'execution_request')), len(events))
        if not events.index(completions[0]) < events.index(joints[0]) < first_solver:
            raise ContractError('joint was not frozen before solver')
        if result.solver is None or result.solver.session.sidecar != path.parent:
            raise ContractError('joint requires the shared solver session')
        solver_state = _solver_journal_state(events); _compare_solver_result(result.solver, solver_state)
        if result.runtime.status != ('succeeded' if solver_state['status'] == 'execution_succeeded' else 'failed'):
            raise ContractError('solver failure was relabeled')
        mode = 'candidate' if 'M3' in cell.runtime_arm.data()['enabled'] else 'baseline'
        public_context = ContextBuilder(task.identity, budget_bytes=state.data()['context_budget_bytes'])
        cache = ContextCache()
        for request in requests:
            claims.refresh_after_withdrawal()
            expected_context = cache.get_or_build(public_context, canonical(task.payload.data()), evidence, claims,
                mode=mode, baseline_summary='').public_data()
            if request['context'] != expected_context:
                raise ContractError('model evidence context differs from actual post-transition state')
            if (set(request) != {'schema', 'task', 'lock_digest', 'objective', 'slot', 'instruction', 'context',
                    'module_context', 'execution_feedback'} or request['schema'] != 'public-model-request-v1'
                    or request['instruction'] != _INSTRUCTIONS[request['slot']]):
                raise ContractError('solver request instruction or schema differs from shared solver contract')
            context = request['module_context']
            common_keys = {'solver', 'public_artifacts', 'panel_cell', 'joint_mechanism', 'joint_mechanism_digest'}
            final_keys = {'analysis', 'analysis_digest', 'analysis_program_sha256', 'execution_digest', 'execution_status',
                'execution_input_artifacts', 'execution_feedback', 'required_objective_digest'}
            if (set(context) != common_keys | (final_keys if request['slot'] == 'final_answer' else set())
                    or context.get('solver') != 'public-benchmark-solve-v1'
                    or context.get('panel_cell') != opaque_panel_cell_binding(cell)
                    or request['slot'] == 'analysis_program' and request['execution_feedback'] != []):
                raise ContractError('solver request context contains unbound fields or early feedback')
            if context.get('joint_mechanism') != joint.data() or context.get('joint_mechanism_digest') != joint.content_hash:
                raise ContractError('solver omitted the actual state or exploration context')
        _verify_solver_files(solver_state, events, path, state)
        execution = solver_state['execution']
        if execution is not None and execution.status != 'rejected':
            argv = execution.record.data().get('argv')
            if (not isinstance(argv, list) or len(argv) < 6 or not isinstance(argv[5], str)
                    or not re.fullmatch('research-loop-[0-9a-f]{20}', argv[5])):
                raise ContractError('missing actual bounded solver Docker invocation')
            expected_argv = ['docker', 'run', '--pull', 'never', '--name', argv[5], '--rm', '--network', 'none', '--read-only',
                '--user', '1000:1000', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '--pids-limit', '128',
                '--memory', '1g', '--cpus', '1.0', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
            for key in sorted(public_inputs):
                expected_argv.extend(['-v', DockerExecutionBroker._mount_source(public_inputs[key].absolute())+':/input/'+key+':ro'])
            expected_argv.extend(['-v', DockerExecutionBroker._mount_source((path.parent/'analysis-1.py').absolute())+
                ':/task/analysis.py:ro', scenario.data()['image'], 'python3', '/task/analysis.py'])
            if argv != expected_argv:
                raise ContractError('solver Docker limits or exact program/input mounts differ from frozen allocation')
    return FrozenRecord.from_dict({'schema': 'state-exploration-verification-v1', 'engineering_verified': True,
        'cell_key': list(cell.key), 'status': result.runtime.status, 'scientific_effect': 'not_measured'})
