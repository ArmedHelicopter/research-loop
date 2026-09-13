"""TRAIN-only M1/M2/M3 x M6, with independently replayed frozen inputs.

State qualification and retrieval provenance are separate signed observations.
Neither provenance signatures nor execution success establish scientific validity.
"""
from dataclasses import dataclass
from pathlib import Path

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
from research_loop.modular.modules.context import ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.modules.retrieval import FrozenSourceBundle
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.retrieval_panel_drivers import _select_sources
from research_loop.modular.retrieval_review_combination_driver import (
    freeze_material as freeze_retrieval, check_material as check_retrieval,
    admission_receipt, _verify_sources, public_retrieval, BUDGET)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError

DESIGNS = {'pair:M1+M6': ('M1', 'M6'), 'pair:M2+M6': ('M2', 'M6'), 'pair:M3+M6': ('M3', 'M6')}
SLOTS = ('analysis_program', 'final_answer')


def registered_design(obligation, baseline):
    if obligation not in DESIGNS:
        raise ContractError('unimplemented state/retrieval combination')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[obligation])


@dataclass(frozen=True)
class FrozenStateRetrievalMaterial:
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord) or len(self.record.encoded.encode('utf-8')) > 524288:
            raise ContractError('bounded frozen composite material required')
        b = self.data()
        if (set(b) != {'schema', 'identity', 'task_digest', 'state_kind', 'state', 'retrieval', 'provenance'}
                or b['schema'] != 'state-retrieval-material-v1' or b['state_kind'] not in ('admission', 'lineage')):
            raise ContractError('closed composite material schema required')
        DataIdentity.parse(b['identity']).require_train()
        state = self.state()
        if state.data()['identity'] != b['identity'] or state.data()['task_digest'] != b['task_digest']:
            raise ContractError('state identity differs from composite')
        r = b['retrieval']; p = b['provenance']
        if (r.get('identity') != b['identity'] or r.get('task_digest') != b['task_digest']
                or not isinstance(p, dict) or set(p) != {'identity', 'task_digest', 'corpus_digest', 'query_digest', 'origin'}
                or p['identity'] != b['identity'] or p['task_digest'] != b['task_digest']
                or p['origin'] != 'caller_public_train_unvalidated'
                or p['corpus_digest'] != FrozenRecord.from_dict({'sources': r['original_sources']}).content_hash
                or p['query_digest'] != FrozenRecord.from_dict(r['query']).content_hash):
            raise ContractError('corpus/query TRAIN provenance binding drift')

    def data(self): return self.record.data()

    def state(self):
        cls = FrozenAdmissionMaterial if self.data()['state_kind'] == 'admission' else FrozenLineageMaterial
        return cls(FrozenRecord.from_dict(self.data()['state']))

    def retrieval(self): return FrozenRecord.from_dict(self.data()['retrieval'])


def freeze_material(task, state_material, sources, question):
    if not isinstance(task, PublicTask) or task.identity.domain != 'train' or type(state_material) not in (FrozenAdmissionMaterial, FrozenLineageMaterial):
        raise ContractError('TRAIN task and exact state material required')
    retrieval = freeze_retrieval(task, sources, question)
    provenance = {'identity': task.identity.data(), 'task_digest': task.content_hash,
        'corpus_digest': FrozenRecord.from_dict({'sources': retrieval.data()['original_sources']}).content_hash,
        'query_digest': FrozenRecord.from_dict(retrieval.data()['query']).content_hash,
        'origin': 'caller_public_train_unvalidated'}
    return FrozenStateRetrievalMaterial(FrozenRecord.from_dict({'schema': 'state-retrieval-material-v1',
        'identity': task.identity.data(), 'task_digest': task.content_hash,
        'state_kind': 'admission' if type(state_material) is FrozenAdmissionMaterial else 'lineage',
        'state': state_material.data(), 'retrieval': retrieval.data(), 'provenance': provenance}))


def _validate(panel, cell, task, scenario, package, material, source_verifier, retrieval_verifier):
    if (not isinstance(panel, CombinationPanel) or panel.obligation_id not in DESIGNS or cell not in panel.cells
            or panel.design != registered_design(panel.obligation_id, cell.runtime_arm.data()['baseline_digest'])
            or not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest
            or not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or type(material) is not FrozenStateRetrievalMaterial):
        raise ContractError('state/retrieval frozen cell binding mismatch')
    state = material.state(); admission = panel.obligation_id == 'pair:M1+M6'
    if (type(state) is not (FrozenAdmissionMaterial if admission else FrozenLineageMaterial)
            or type(source_verifier) is not (AdmissionMaterialVerifier if admission else DualMaterialVerifier)
            or type(retrieval_verifier) is not DualMaterialVerifier):
        raise ContractError('obligation requires its exact state and provenance verifiers')
    expected = {'schema': 'state-retrieval-combination-scenario-v1', 'obligation_id': panel.obligation_id,
        'design_digest': panel.design.content_hash, 'task_digest': task.content_hash,
        'replicate': cell.replicate, 'material_digest': material.record.content_hash,
        'source_verifier_binding': source_verifier.binding().data(),
        'retrieval_verifier_binding': retrieval_verifier.binding().data()}
    if scenario.data() != expected:
        raise ContractError('scenario must freeze exact material and configured authority keys')
    docs = check_retrieval(material.retrieval(), task)
    if freeze_material(task, state, material.retrieval().data()['original_sources'], material.retrieval().data()['query']['question']) != material:
        raise ContractError('composite material reconstruction drift')
    return state, docs


@dataclass(frozen=True)
class StateRetrievalResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    retrieval: FrozenRecord | None
    joint_mechanism: FrozenRecord | None


def _joint(cell, transition, projection, package):
    changes = package.record.data()['changes']
    return FrozenRecord.from_dict({'schema': 'state-retrieval-public-joint-v1',
        'panel_cell': opaque_panel_cell_binding(cell), 'state_projection': transition.data()['public'],
        'retrieval': public_retrieval(projection),
        'candidate_context': {'prompt': changes.get('prompt', {}), 'memory': changes.get('memory', {})}})


def run_state_retrieval_cell(*, panel, cell, task, scenario, package, material, source_verifier, retrieval_verifier,
        provider, objective, sidecar, public_inputs, image, broker, model, audit_verifier, timeout_seconds=20):
    state, docs = _validate(panel, cell, task, scenario, package, material, source_verifier, retrieval_verifier)
    if (not isinstance(sidecar, Path) or sidecar.exists() or not callable(getattr(provider, 'search', None))
            or not isinstance(objective, FrozenRecord) or not callable(model) or not isinstance(audit_verifier, AuditVerifier)
            or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120):
        raise ContractError('closed runtime dependencies required')
    check_material_inputs(state, task, broker, public_inputs)
    binding = _source_binding(cell)
    source_path = sidecar / 'source-verification.json'
    source_hash = source_verifier.qualify(state, source_path, cell_binding=binding)
    # A separate signed request covers literal original corpus/query, task and state.
    retrieval_hash = retrieval_verifier.qualify(material, sidecar / 'retrieval' / 'source-verification.json', cell_binding=binding)
    qualification = source_verifier.assessments(state, source_path, cell_binding=binding) if type(state) is FrozenAdmissionMaterial else None
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
        slots=SLOTS, execution_limit=1, sidecar=sidecar / 'runtime', verifier=audit_verifier,
        required_audit=('measurement',), context_budget=state.data()['context_budget_bytes'])
    workflow = ModularWorkflow(session)
    transition = _transition(session.evidence, session.claims, session.cache, state, workflow.enabled, qualification)
    session._record('state_retrieval_transition', {'transition': transition.data(), 'source_sha256': source_hash,
        'retrieval_source_sha256': retrieval_hash})
    retrieval = joint = solver = None
    try:
        pool = FrozenSourceBundle('public-train-retrieval-pool-v1', docs)
        admitted = admission_receipt(task, pool)
        session._record('q8_source_admission', {'receipt': admitted.data(), 'receipt_digest': admitted.content_hash})
        projection, usage = _select_sources(provider, session, docs, material.retrieval().data()['query'], BUDGET,
            'Q8.3', 'three_lane', 'M6' in workflow.enabled)
        session._record('retrieval_review_sources', {'projection': projection, 'usage': usage})
        retrieval = FrozenRecord.from_dict({'projection': projection, 'usage': usage})
        joint = _joint(cell, transition, projection, package)
        session._record('state_retrieval_joint', {'joint': joint.data(), 'joint_digest': joint.content_hash})
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=public_inputs,
            image=image, broker=broker, model=model, analysis_slot=SLOTS[0], final_slot=SLOTS[1],
            joint_mechanism=joint, panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),
            driver_id=cell.coverage_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            session.controller_failure(driver_id=cell.coverage_id, error_type=type(exc).__name__, panel_cell=opaque_panel_cell_binding(cell))
    status = 'succeeded' if solver is not None and solver.status == 'execution_succeeded' else 'failed'
    return StateRetrievalResult(cell, _runtime(cell, session, joint, status), solver, transition, retrieval, joint)


def verify_state_retrieval_cell(result, *, panel, task, scenario, package, material, source_verifier,
        retrieval_verifier, public_inputs, broker):
    """Read-only replay of original signed inputs, actual module journals and solve."""
    if type(result) is not StateRetrievalResult:
        raise ContractError('typed state/retrieval result required')
    cell = result.cell
    state, _ = _validate(panel, cell, task, scenario, package, material, source_verifier, retrieval_verifier)
    check_material_inputs(state, task, broker, public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime, cell)
    path = result.runtime.trace_path; events = _read_events(path); binding = _source_binding(cell)
    source_path = path.parent.parent / 'source-verification.json'
    source_hash = source_verifier.replay(state, source_path, cell_binding=binding)
    retrieval_hash = retrieval_verifier.replay(material, path.parent.parent / 'retrieval' / 'source-verification.json', cell_binding=binding)
    qualification = source_verifier.assessments(state, source_path, cell_binding=binding) if type(state) is FrozenAdmissionMaterial else None
    evidence = EvidenceLedger(task.identity); claims = ClaimLedger(evidence)
    evidence._log = _MemoryLog(); claims._log = _MemoryLog()
    transition = _transition(evidence, claims, ContextCache(), state, set(cell.runtime_arm.data()['enabled']), qualification)
    if (transition != result.transition or _read_events(path.parent / 'evidence.jsonl') != evidence._log.rows
            or _read_events(path.parent / 'claims.jsonl') != claims._log.rows):
        raise ContractError('state journals differ from original qualification and transition replay')
    transitions = [e for e in events if e['stage'] == 'state_retrieval_transition']
    if len(transitions) != 1 or transitions[0]['data'] != {'transition': transition.data(), 'source_sha256': source_hash,
            'retrieval_source_sha256': retrieval_hash}:
        raise ContractError('state transition lost its original source binding')
    io = [e for e in events if e['stage'] in ('q8_source_admission', 'q8_retrieval_request', 'model_request', 'execution_request')]
    if io and events.index(transitions[0]) >= events.index(io[0]):
        raise ContractError('source and state qualification must precede retrieval and model I/O')
    projection = _verify_sources(events, task, material.retrieval(), 'M6' in cell.runtime_arm.data()['enabled'])
    requests = [e['data']['request'] for e in events if e['stage'] == 'model_request']
    if tuple(r['slot'] for r in requests) != SLOTS[:len(requests)] or any(_private_arm_marker(r) for r in requests):
        raise ContractError('solver schedule or public isolation drift')
    joints = [e for e in events if e['stage'] == 'state_retrieval_joint']
    if projection is None:
        if result.retrieval is not None or result.joint_mechanism is not None or joints or requests or result.solver is not None or result.runtime.status != 'failed':
            raise ContractError('retrieval failure reached unbound solver')
    else:
        sources = next(e for e in events if e['stage'] == 'retrieval_review_sources')
        if result.retrieval != FrozenRecord.from_dict(sources['data']):
            raise ContractError('retrieval result differs from individual item replay')
        joint = _joint(cell, transition, projection, package)
        if result.joint_mechanism != joint or len(joints) != 1 or joints[0]['data'] != {'joint': joint.data(), 'joint_digest': joint.content_hash}:
            raise ContractError('joint differs from actual state and selected corpus')
        first_solver = next((i for i, e in enumerate(events) if e['stage'] in ('model_request', 'execution_request')), len(events))
        if not events.index(sources) < events.index(joints[0]) < first_solver:
            raise ContractError('joint was not frozen before solver')
        if result.solver is None or result.solver.session.sidecar != path.parent:
            raise ContractError('joint requires the shared solver session')
        solver_state = _solver_journal_state(events); _compare_solver_result(result.solver, solver_state)
        if result.runtime.status != ('succeeded' if solver_state['status'] == 'execution_succeeded' else 'failed'):
            raise ContractError('solver failure was relabeled')
        for request in requests:
            context = request['module_context']
            if context.get('joint_mechanism') != joint.data() or context.get('joint_mechanism_digest') != joint.content_hash:
                raise ContractError('solver omitted the actual state or retrieval context')
        _verify_solver_files(solver_state, events, path, state)
    return FrozenRecord.from_dict({'schema': 'state-retrieval-verification-v1', 'engineering_verified': True,
        'cell_key': list(cell.key), 'status': result.runtime.status, 'scientific_effect': 'not_measured'})
