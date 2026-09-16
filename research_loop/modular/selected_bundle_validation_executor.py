"""Execute only the two frozen target bundles on an already consumed lease.

All learned-state creation remains in TRAIN. This seam owns no optimizer,
reference resolver, scorer key, acceptance key or deployment operation.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re

from research_loop.modular.admission_combination import transition as admission_transition
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.context_artifact import verify_session_context_artifacts
from research_loop.modular.full_loo_driver import _phase_artifact_bridge
from research_loop.modular.full_loo_modules import prepare, joint, slots
from research_loop.modular.lineage_combination_driver import _source_binding, _read_events, _MemoryLog, _verify_solver_files
from research_loop.modular.lineage_combination_material import check_material_inputs
from research_loop.modular.metaprogram_training import _exclusive, _read_record
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding, verify_signed
from research_loop.modular.runtime import RunSession
from research_loop.modular.selected_bundle_validation import SelectedBundleValidationPanel, verify_selected_validation_lease
from research_loop.modular.validation_bundle_material import (
    ValidationBundleMaterial, ValidationCsvMeasurementVerifier, validation_retrieval,
    replay_validation_retrieval, run_validation_phase,
)
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

R = FrozenRecord.from_dict


def files(root):
    paths = [p for p in root.rglob('*') if p.is_file() and p != root/'receipt.json']
    if any(DockerExecutionBroker._has_link_component(p) for p in [root, *paths]):
        raise ContractError('validation originals cannot be redirected through links')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _validate(panel, cell, task, material, source_verifier, broker, inputs, freeze_keys, lease, custody_keys):
    if (type(panel) is not SelectedBundleValidationPanel or cell not in panel.cells
            or type(material) is not ValidationBundleMaterial
            or type(source_verifier) is not ValidationCsvMeasurementVerifier
            or task.identity != cell.identity or task.content_hash != cell.task_digest
            or material.record.content_hash != cell.scenario_digest):
        raise ContractError('fixed validation cell, material and measured source verifier required')
    panel.verify_freeze(freeze_keys); material.__post_init__()
    verify_selected_validation_lease(panel, lease, custody_keys)
    check_material_inputs(material.admission, task, broker, inputs)
    public = [{'artifact': a.record.data(), 'container_path': '/input/'+a.artifact_id}
              for a in broker.validate_inputs(task.identity, inputs)]
    if public != material.phase.data()['public_artifacts']:
        raise ContractError('validation diagnostic input bytes differ')
    binding = source_verifier.binding().data()
    selected = {k: v for k, v in binding.items() if k != 'csv_measurement'}
    if selected != panel.design.data()['execution']['source_authorities']:
        raise ContractError('source authority identity, domain or implementation pins drift')
    spec = panel.spec(cell.arm_id)
    if material.admission.data()['context_budget_bytes'] != spec[0].record.data()['resource_schedule']['context_budget_bytes']:
        raise ContractError('validation material changed the frozen context budget')
    return spec


@dataclass(frozen=True)
class ValidationTargetResult:
    root: Path
    record: FrozenRecord
    cell: object
    runtime: object
    solver: object
    joint_mechanism: FrozenRecord | None
    phase: FrozenRecord | None


def evaluate_selected_primary_bundles(panel, materials, lease, *, root, materials_by_task, source_verifiers,
        inputs_by_task, broker, model, model_config, retrieval_provider, audit_verifier, freeze_keys, custody_keys,
        score_and_accept):
    """Private evaluator for PrimaryValidationCustodian.run, one complete pair.

    The custodian calls this only after durable lease consumption. A fixed
    service-owned root reserves the entire opportunity before any target run;
    a second call cannot replace an earlier failed or successful prefix.
    The independent scoring service receives the complete original manifests.
    """
    from evaluation.modular.primary_validation_custody import PrimaryValidationMaterial, PrimaryValidationResult
    if type(panel) is not SelectedBundleValidationPanel or not callable(score_and_accept):
        raise ContractError('fixed selected panel and independent scoring port required')
    panel.verify_freeze(freeze_keys)
    verify_selected_validation_lease(panel, lease, custody_keys)
    tasks = {m.task.content_hash: m for m in materials if type(m) is PrimaryValidationMaterial}
    wanted = {c.task_digest for c in panel.cells}
    if (len(tasks) != len(materials) or set(tasks) != wanted or set(materials_by_task) != wanted
            or set(source_verifiers) != wanted or set(inputs_by_task) != wanted):
        raise ContractError('fixed pair must consume the complete leased task/material inventory')
    for key, source in tasks.items():
        inputs = inputs_by_task[key]
        if set(inputs) != {'public_csv'} or Path(inputs['public_csv']).read_bytes() != source.csv:
            raise ContractError('fixed pair input is not the custody-extracted public CSV')
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    _exclusive(root/'fixed-pair-reservation.json', R({'schema': 'selected-bundle-validation-reservation-v1',
        'panel_digest': panel.digest, 'lease_digest': lease.content_hash,
        'cell_digests': [R(c.data()).content_hash for c in panel.cells]}))
    rows, requests = [], []
    for cell in panel.cells:
        key = cell.task_digest
        args = dict(panel=panel, task=tasks[key].task, material=materials_by_task[key], source_verifier=source_verifiers[key],
                    inputs=inputs_by_task[key], lease=lease)
        result = run_validation_target(cell=cell, **args, root=root/'cells'/R(cell.data()).content_hash,
            broker=broker, model=model, model_config=model_config, retrieval_provider=retrieval_provider,
            audit_verifier=audit_verifier, freeze_keys=freeze_keys, custody_keys=custody_keys)
        rows.append(result.runtime); requests.append(validation_score_request(result, **args))
    result = score_and_accept(panel, tuple(requests), tuple(rows), lease)
    if type(result) is not PrimaryValidationResult or result.runtime != tuple(rows):
        raise ContractError('independent scoring cannot replace original fixed-pair runtime cells')
    _exclusive(root/'fixed-pair-closed.json', R({'schema': 'selected-bundle-validation-closed-v1',
        'panel_digest': panel.digest, 'scope_ids': list(panel.scope_ids), 'variants': ['fixed_acceptance'],
        'lease_digest': lease.content_hash, 'replay_request_digests': [r.content_hash for r in requests],
        'runtime': [PanelReceiptVerifier._runtime_data(r) for r in rows],
        'scorer_receipts': [r.receipt.content_hash for r in result.scores], 'acceptance_digest': result.acceptance.content_hash}))
    return result


def run_validation_target(*, panel, cell, task, material, source_verifier, retrieval_provider, broker, inputs,
                          model, model_config, audit_verifier, root, freeze_keys, lease, custody_keys):
    """One fixed cell; no retry, builder, recipe mutation or feedback-to-TRAIN API."""
    args = dict(panel=panel, cell=cell, task=task, material=material, source_verifier=source_verifier,
        broker=broker, inputs=inputs, freeze_keys=freeze_keys, lease=lease, custody_keys=custody_keys)
    bundle, recipe, package, selection, _ = _validate(**args)
    execution = panel.design.data()['execution']; schedule = bundle.record.data()['resource_schedule']
    if type(model_config) is not FrozenRecord or model_config.data() != execution['model_config']:
        raise ContractError('target model configuration differs from TRAIN freeze')
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    session = RunSession(task, package_digest=bundle.digest, arm=cell.runtime_arm, objective=R(execution['objective']),
        slots=slots(recipe, 'target'), execution_limit=1, sidecar=root/'runtime', verifier=audit_verifier,
        required_audit=('measurement',), context_budget=schedule['context_budget_bytes'], experiment_id=panel.digest)
    workflow = ModularWorkflow(session); enabled = set(workflow.enabled); producer = source_snapshot(Path(__file__))
    prepared = phase = joined = solver = None; failure = None
    consumed = {'bundle': bundle.acknowledgement().data(), 'learned_package_digest': package.digest,
                'selection_digest': selection, 'train_freeze_digest': R(panel.design.data()['train_freeze']).content_hash,
                'lease_digest': lease.content_hash, 'target_levels': recipe['target_levels']}
    try:
        _exclusive(root/'material.json', material.record)
        _exclusive(root/'bundle.json', bundle.record)
        _exclusive(root/'consumed-lease.json', lease)
        _exclusive(root/'design.json', panel.design)
        session._record('validation_bundle_consumed', consumed)
        session.record_artifact(kind='frozen_train_candidate_consumed', module='M9', payload=consumed,
            status='produced', producer_source=producer)
        source = source_verifier.qualify(material.admission, root/'source/source.json', cell_binding=_source_binding(cell))
        qualification = source_verifier.assessments(material.admission, root/'source/source.json', cell_binding=_source_binding(cell))
        state = admission_transition(session.evidence, session.claims, session.cache, material.admission, enabled, qualification)
        session._record('validation_state', {'transition': state.data(), 'source_sha256': source})
        for name in ('M1', 'M2', 'M3'):
            session.record_artifact(kind='lineage_transition', module=name, payload=state,
                status='produced' if name in enabled else 'not_applied', producer_source=producer)
        def invoke(slot, instruction, context):
            _validate(**args)
            return session.invoke(slot, model, instruction=instruction, module_context=context)
        if recipe['procedure'] != 'baseline_b0':
            def record(name, data):
                event = session._record(name, data)
                module = {'c4_prediction_frozen': 'M4', 'c4_review_sealed': 'M5',
                          'c4_review_reveal': 'M5', 'c4_choice_frozen': 'M7'}.get(name)
                if module:
                    session.record_artifact(kind=name, module=module, payload=data,
                        status='produced' if module in enabled else 'not_applied', producer_source=producer)
                return event
            prepared = prepare(cell=cell, task=task, package=package, transition=state,
                predictions=workflow.predictions, reviews=workflow.reviews, invoke=invoke, record=record,
                retrieve=lambda: validation_retrieval(session, task, material.retrieval, retrieval_provider, 'M6' in enabled),
                phase_material=material.phase)
            session.record_artifact(kind='retrieval_result', module='M6', payload=prepared.data()['retrieval'],
                status='produced' if 'M6' in enabled else 'not_applied', producer_source=producer)
            phase = run_validation_phase(material=material.phase, cell=cell, objective=R(execution['objective']),
                root=root/'phase', broker=broker, inputs=inputs, image=execution['image'],
                timeout_seconds=schedule['timeout_seconds'], selected_job_id=prepared.data()['choice']['job_id'],
                artifact_bridge=_phase_artifact_bridge(session.artifacts, root, cell, prepared))
            session._record('validation_phase', {'phase_digest': phase.content_hash})
            for name in ('M7', 'M8'):
                session.record_artifact(kind='exploration_phase_receipt', module=name, payload=phase,
                    status='produced' if name in enabled else 'not_applied', producer_source=producer)
        joined = joint(prepared, phase, cell, task, package)
        session._record('validation_joint', {'joint': joined.data(), 'joint_digest': joined.content_hash})
        def solve_model(request):
            _validate(**args)
            return model(request)
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=inputs,
            image=execution['image'], broker=broker, model=solve_model, analysis_slot='analysis_program', final_slot='final_answer',
            joint_mechanism=joined, panel_cell_binding=R(opaque_panel_cell_binding(cell)),
            driver_id=cell.coverage_id, timeout_seconds=schedule['timeout_seconds'])
        _validate(**args)
    except Exception as exc:
        failure = type(exc).__name__
        if not session._terminal:
            session.controller_failure(driver_id=cell.coverage_id, error_type=failure, panel_cell=opaque_panel_cell_binding(cell))
    status = 'succeeded' if failure is None and solver is not None and solver.status == 'execution_succeeded' else 'failed'
    seal = session.artifacts.seal()
    receipt = R({'schema': 'selected-bundle-validation-target-v1', 'panel_digest': panel.digest, 'cell': cell.data(),
        'bundle_digest': bundle.digest, 'package_digest': package.digest, 'consumed': consumed,
        'status': status, 'failure_type': failure, 'source_verifier_binding': source_verifier.binding().data(),
        'artifact_catalogue_seal': seal.data(), 'files': files(root)})
    _exclusive(root/'receipt.json', receipt)
    return ValidationTargetResult(root, receipt, cell, _runtime(cell, session, joined, status), solver, joined, phase)


def verify_validation_target(result, *, panel, task, material, source_verifier, broker, inputs, freeze_keys, lease, custody_keys):
    """Recompute native operations from original requests; no model/provider I/O."""
    if type(result) is not ValidationTargetResult:
        raise ContractError('exact validation target result required')
    cell = result.cell; root = result.root; body = result.record.data()
    bundle, recipe, package, selection, _ = _validate(panel, cell, task, material, source_verifier,
        broker, inputs, freeze_keys, lease, custody_keys)
    execution = panel.design.data()['execution']; schedule = bundle.record.data()['resource_schedule']
    if (set(body) != {'schema', 'panel_digest', 'cell', 'bundle_digest', 'package_digest', 'consumed',
                     'status', 'failure_type', 'source_verifier_binding', 'artifact_catalogue_seal', 'files'}
            or body['schema'] != 'selected-bundle-validation-target-v1'
            or body['status'] not in {'succeeded', 'failed'} or body['status'] != result.runtime.status
            or _read_record(root/'receipt.json') != result.record or body['files'] != files(root)
            or body['panel_digest'] != panel.digest or body['cell'] != cell.data()
            or body['bundle_digest'] != bundle.digest or body['package_digest'] != package.digest
            or body['source_verifier_binding'] != source_verifier.binding().data()
            or _read_record(root/'material.json') != material.record or _read_record(root/'bundle.json') != bundle.record
            or _read_record(root/'consumed-lease.json') != lease or _read_record(root/'design.json') != panel.design):
        raise ContractError('validation target original bytes or frozen subject drift')
    PanelReceiptVerifier()._verify_runtime(result.runtime, cell)
    path = result.runtime.trace_path; events = _read_events(path); lock = R(events[0]['data'])
    seal = R(body['artifact_catalogue_seal'])
    catalogue = ArtifactCatalogue(root/'runtime/artifacts.jsonl', identity=task.identity,
        run_id=seal.data()['binding']['run_id'], experiment_id=panel.digest, lock_digest=lock.content_hash,
        producer_source=source_snapshot(Path(__file__)))
    catalogue.verify(seal)
    if [d.data()['payload']['canonical'] for d in catalogue.records() if d.data()['kind'] == 'trace_event'] != events:
        raise ContractError('validation trace differs from original artifact transactions')
    from research_loop.modular.evidence_artifacts import verify_evidence_artifacts
    from research_loop.modular.m4_m5_artifacts import verify_m4_m5_artifacts
    from research_loop.modular.retrieval_artifacts import verify_retrieval_event_stream
    evidence_replay = verify_evidence_artifacts(catalogue, root/'runtime').data()
    snapshots = {key: {'evidence': R(v['evidence_snapshot']), 'claims': R(v['claims_snapshot'])}
                 for key, v in evidence_replay['model_inputs'].items()}
    verify_session_context_artifacts(task=task, lock=lock, events=events, catalogue=catalogue, invocation_snapshots=snapshots)
    verify_m4_m5_artifacts(catalogue, root/'runtime')
    verify_retrieval_event_stream(catalogue, trace_path=path, task=task)
    if (lock.data()['objective'] != execution['objective'] or lock.data()['slots'] != list(slots(recipe, 'target'))
            or lock.data()['execution_limit'] != 1 or lock.data()['context_budget'] != schedule['context_budget_bytes']):
        raise ContractError('validation lock differs from frozen schedule')
    verified = R({'schema': 'selected-bundle-validation-target-verified-v1', 'panel_digest': panel.digest,
        'cell_digest': R(cell.data()).content_hash, 'receipt_digest': result.record.content_hash,
        'scope_ids': list(panel.scope_ids), 'variant': cell.variant, 'runtime_status': body['status'],
        'scientific_effect': 'not_measured'})
    if body['status'] == 'failed':
        # A failed original can only support an inconclusive denominator. The
        # generic verifier authenticates its terminal failure, and the entire
        # original inventory/catalogue is retained. It is never a score input.
        state = _solver_journal_state(events)
        _verify_solver_files(state, events, path, material.admission)
        if body['files'] != files(root): raise ContractError('failed validation bytes changed during replay')
        return verified
    source = source_verifier.replay(material.admission, root/'source/source.json', cell_binding=_source_binding(cell))
    qualification = source_verifier.assessments(material.admission, root/'source/source.json', cell_binding=_source_binding(cell))
    evidence = EvidenceLedger(task.identity); claims = ClaimLedger(evidence); cache = ContextCache()
    evidence._log = _MemoryLog(); claims._log = _MemoryLog()
    enabled = set(cell.runtime_arm.data()['enabled'])
    state = admission_transition(evidence, claims, cache, material.admission, enabled, qualification)
    consumed = {'bundle': bundle.acknowledgement().data(), 'learned_package_digest': package.digest,
                'selection_digest': selection, 'train_freeze_digest': R(panel.design.data()['train_freeze']).content_hash,
                'lease_digest': lease.content_hash, 'target_levels': recipe['target_levels']}
    if body['consumed'] != consumed:
        raise ContractError('frozen M9 selection or bundle consumption drift')
    expected = [('validation_bundle_consumed', consumed), ('validation_state', {'transition': state.data(), 'source_sha256': source})]
    requests = [e for e in events if e['stage'] == 'model_request']; responses = [e for e in events if e['stage'] == 'model_response']
    context = ContextBuilder(task.identity, budget_bytes=lock.data()['context_budget']).build(canonical(task.payload.data()),
        evidence, claims, mode='candidate' if 'M3' in enabled else 'baseline', baseline_summary='').public_data()
    cursor = 0
    def invoke(slot, instruction, module_context):
        nonlocal cursor
        request, response = requests[cursor], responses[cursor]; cursor += 1
        wanted = {'schema': 'public-model-request-v1', 'task': task.data(), 'lock_digest': lock.content_hash,
                  'objective': execution['objective'], 'slot': slot, 'instruction': instruction, 'context': context,
                  'module_context': module_context.data(), 'execution_feedback': []}
        if request['data']['request'] != wanted or response['data']['request_digest'] != request['data']['request_digest']:
            raise ContractError('validation native operation did not consume the frozen predecessor output')
        return R(response['data']['response'])
    predictions = PredictionRegistry(task.identity); reviews = ReviewEngine(task.identity)
    predictions._log = _MemoryLog(); reviews._log = _MemoryLog()
    prepared = phase = None
    if recipe['procedure'] != 'baseline_b0':
        retrieval = replay_validation_retrieval(events, task, material.retrieval, 'M6' in enabled)
        prepared = prepare(cell=cell, task=task, package=package, transition=state, predictions=predictions,
            reviews=reviews, invoke=invoke, record=lambda name, data: expected.append((name, data)),
            retrieve=lambda: retrieval, phase_material=material.phase)
        from research_loop.modular.phase_artifacts import verify_phase_artifacts
        phase = verify_phase_artifacts(bridge=_phase_artifact_bridge(catalogue, root, cell, prepared),
            material=material.phase, cell=cell, objective=R(execution['objective']), root=root/'phase',
            image=execution['image'], timeout_seconds=schedule['timeout_seconds'], inputs=inputs,
            selected_job_id=prepared.data()['choice']['job_id'])
        if phase != result.phase: raise ContractError('validation phase original differs')
        expected.append(('validation_phase', {'phase_digest': phase.content_hash}))
    joined = joint(prepared, phase, cell, task, package)
    expected.append(('validation_joint', {'joint': joined.data(), 'joint_digest': joined.content_hash}))
    if joined != result.joint_mechanism: raise ContractError('target omitted a module output')
    actual = [(e['stage'], e['data']) for e in events if e['stage'].startswith(('validation_', 'c4_'))
              and e['stage'] != 'validation_retrieval_binding']
    if actual != expected or any(_private_arm_marker(r['data']['request']) for r in requests):
        raise ContractError('validation operation ordering or private arm isolation drift')
    for name, log in (('evidence', evidence._log), ('claims', claims._log), ('predictions', predictions._log), ('reviews', reviews._log)):
        if _read_events(root/'runtime'/(name+'.jsonl')) != log.rows:
            raise ContractError('validation native '+name+' journal drift')
    solver_state = _solver_journal_state(events); _compare_solver_result(result.solver, solver_state)
    _verify_solver_files(solver_state, events, path, material.admission)
    executed = solver_state['execution']
    if executed is None or executed.artifact is None or executed.status != 'succeeded':
        raise ContractError('scored fixed target lacks a successful real execution')
    argv = executed.record.data().get('argv')
    if not isinstance(argv, list) or len(argv) < 6 or not re.fullmatch('research-loop-[0-9a-f]{20}', argv[5]):
        raise ContractError('fixed target lacks original restricted Docker command')
    wanted = ['docker', 'run', '--pull', 'never', '--name', argv[5], '--rm', '--network', 'none', '--read-only',
        '--user', '1000:1000', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '--pids-limit', '128', '--memory', '1g',
        '--cpus', '1.0', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
    for key in sorted(inputs): wanted.extend(['-v', DockerExecutionBroker._mount_source(inputs[key].absolute())+':/input/'+key+':ro'])
    wanted.extend(['-v', DockerExecutionBroker._mount_source((path.parent/'analysis-1.py').absolute())+':/task/analysis.py:ro',
                   execution['image'], 'python3', '/task/analysis.py'])
    if argv != wanted: raise ContractError('validation solver actual mounts or execution limits drift')
    for item in requests[cursor:]:
        request = item['data']['request']; module = request['module_context']
        if (module.get('joint_mechanism') != joined.data() or module.get('joint_mechanism_digest') != joined.content_hash
                or module.get('panel_cell') != opaque_panel_cell_binding(cell) or request['context'] != context):
            raise ContractError('common solve ignored actual fixed bundle outputs')
    if body['files'] != files(root): raise ContractError('validation bytes changed during replay')
    return verified


def derive_validation_score_input(result, **verification):
    verified = verify_validation_target(result, **verification)
    common = {'schema': 'selected-bundle-validation-score-input-v1', 'panel_digest': verification['panel'].digest,
        'cell': result.cell.data(), 'stage_receipt_digest': result.record.content_hash, 'verification_digest': verified.content_hash,
        'cell_key': list(result.cell.key), 'benchmark': result.cell.identity.benchmark,
        'identity_digest': R(result.cell.identity.data()).content_hash, 'runtime_status': result.runtime.status,
        'runtime_trace_digest': result.runtime.trace_digest, 'runtime_output_digest': result.runtime.output_digest,
        'scientific_validity': 'not_measured', 'failure_reason': result.runtime.failure_reason}
    if result.runtime.status != 'succeeded':
        return R({**common, 'submission': None, 'submission_digest': None, 'execution_digest': None,
                  'executed_program_sha256': None})
    events = _read_events(result.runtime.trace_path); state = _solver_journal_state(events)
    execution = state['execution'].record.data()
    submission = R({'analysis': state['analysis'].data()['analysis'], 'program': state['analysis'].data()['program'],
        'answer': state['answer'].data()['conclusion'],
        'execution_feedback': {k: execution[k] for k in ('status', 'exit_code', 'stdout', 'stderr')}})
    return R({**common,
        'submission': submission.data(), 'submission_digest': submission.content_hash,
        'execution_digest': state['execution'].content_hash, 'executed_program_sha256': state['execution'].artifact.sha256,
        'scientific_validity': 'not_measured'})


def load_validation_target(root):
    """Reconstruct the result from journals without constructing a RunSession."""
    from types import SimpleNamespace
    from research_loop.modular.contracts import DataIdentity
    from research_loop.modular.panel_receipts import PanelCell, RuntimeReceipt
    root = Path(root); record = _read_record(root/'receipt.json'); body = record.data(); row = body['cell']
    cell = PanelCell(**{**row, 'identity': DataIdentity.parse(row['identity']), 'runtime_arm': R(row['runtime_arm'])})
    events = _read_events(root/'runtime/trace.jsonl')
    responses = [e['data']['response'] for e in events if e['stage'] == 'model_response']
    output = R({'responses': responses, 'terminal': events[-1]['data']}).content_hash if body['status'] == 'succeeded' else None
    runtime = RuntimeReceipt(cell.key, body['status'], root/'runtime/trace.jsonl', R(events[-1]).content_hash,
        output, None if body['status'] == 'succeeded' else 'combination mechanism or solve failed')
    state = _solver_journal_state(events)
    joins = [e['data']['joint'] for e in events if e['stage'] == 'validation_joint']
    phase = _read_record(root/'phase/receipt.json') if (root/'phase/receipt.json').exists() else None
    return ValidationTargetResult(root, record, cell, runtime, SimpleNamespace(**state), R(joins[0]) if len(joins) == 1 else None, phase)


def validation_score_request(result, *, panel, task, material, source_verifier, inputs, lease):
    """Private execution-to-scorer manifest; no references or authority secrets."""
    from research_loop.modular.selected_bundle_validation import serialize_selected_panel
    return R({'schema': 'selected-bundle-validation-replay-request-v1', 'result_root': str(result.root.resolve()),
        'panel': serialize_selected_panel(panel), 'task': task.data(), 'material': material.record.data(),
        'lease': lease.data(), 'inputs': {k: str(Path(v).resolve()) for k, v in inputs.items()},
        'source_verifier': {'receipt_root': str(source_verifier.receipt_root),
            'authority_ids': [a.authority.authority_id for a in source_verifier.authorities],
            'datasets': {k: {'csv_path': str(v.csv_path), 'specifications': {n: s.record.data() for n, s in v.specs.items()}}
                         for k, v in source_verifier.datasets.items()}},
        'expected_stage_receipt_digest': result.record.content_hash})


def replay_validation_score_request(request, *, freeze_keys, custody_keys, source_keys):
    """Scorer process independently replays fixed original execution evidence.

    Authority keys are independent service configuration. Never read keys or
    replace the native verifier according to a caller's replay request.
    """
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority
    from research_loop.modular.contracts import DataIdentity, PublicTask
    from research_loop.modular.csv_measurement_authorities import CsvMeasurementDataset, CsvMeasurementSpec
    from research_loop.modular.selected_bundle_validation import parse_selected_panel
    from research_loop.modular.validation_bundle_material import (
        ValidationAdmissionMaterial, ValidationPhaseMaterial, build_validation_csv_verifier)
    if type(request) is not FrozenRecord:
        raise ContractError('frozen execution replay request required')
    body = request.data()
    if (set(body) != {'schema', 'result_root', 'panel', 'task', 'material', 'lease', 'inputs', 'source_verifier',
                     'expected_stage_receipt_digest'} or body['schema'] != 'selected-bundle-validation-replay-request-v1'):
        raise ContractError('exact execution replay request required')
    panel = parse_selected_panel(body['panel'])
    task = PublicTask(DataIdentity.parse(body['task']['identity']), R(body['task']['payload']))
    m = body['material']
    material = ValidationBundleMaterial(ValidationAdmissionMaterial(R(m['admission'])),
        ValidationPhaseMaterial(R(m['phase'])), R(m['retrieval']))
    if material.record.data() != m: raise ContractError('replay material serialization drift')
    sources = body['source_verifier']
    if set(sources) != {'receipt_root', 'authority_ids', 'datasets'}:
        raise ContractError('exact measured-source replay dependencies required')
    if any(name not in source_keys for name in sources['authority_ids']):
        raise ContractError('replay source authority is not independently configured')
    root = Path(body['result_root']); inputs = {k: Path(v) for k, v in body['inputs'].items()}
    paths = [root, Path(sources['receipt_root']), *inputs.values(),
             *[Path(v['csv_path']) for v in sources['datasets'].values()]]
    if any(not p.is_absolute() or DockerExecutionBroker._has_link_component(p) for p in paths):
        raise ContractError('replay dependencies require absolute regular original paths')
    if not (Path(sources['receipt_root'])/'authority-manifest.json').is_file():
        raise ContractError('replay cannot create a missing source authority manifest')
    verifier = build_validation_csv_verifier(
        authorities=tuple(LinkedExecutionAuthority(name, source_keys[name]) for name in sources['authority_ids']),
        datasets={k: CsvMeasurementDataset(Path(v['csv_path']), {n: CsvMeasurementSpec(R(s))
                  for n, s in v['specifications'].items()}) for k, v in sources['datasets'].items()},
        receipt_root=Path(sources['receipt_root']))
    result = load_validation_target(root)
    if result.record.content_hash != body['expected_stage_receipt_digest']:
        raise ContractError('replay target receipt differs from requested original')
    return derive_validation_score_input(result, panel=panel, task=task, material=material, source_verifier=verifier,
        broker=DockerExecutionBroker([root, *[p.parent for p in inputs.values()]]), inputs=inputs,
        freeze_keys=freeze_keys, lease=R(body['lease']), custody_keys=custody_keys)
