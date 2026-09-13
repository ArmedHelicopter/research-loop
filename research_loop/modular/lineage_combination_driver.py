"""One actual lineage/context/review session followed by the shared solver."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session, _program_from, _candidate_from
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combination_benchmark_driver import _close_failure, _runtime, _private_arm_marker
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, check_material_inputs
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.panel_receipts import PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession, AuditVerifier
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical


DESIGNS = {'pair:M2+M3': ('M2', 'M3'), 'pair:M2+M5': ('M2', 'M5'),
           'pair:M3+M5': ('M3', 'M5'), 'triple:M2+M3+M5': ('M2', 'M3', 'M5')}
SLOTS = ('lineage_review', 'measurement_review', 'analysis_program', 'final_answer')
ROLES = (('lineage', 'Which observations share one root, and which claims need review after withdrawal?'),
         ('measurement', 'What public measurement risk could invalidate the available claims?'))


class _MemoryLog:
    def __init__(self): self.rows = []
    def append(self, row): self.rows.append(FrozenRecord.from_dict(row).data())


def registered_design(obligation, baseline):
    from research_loop.modular.admission_combination import DESIGNS as ADMISSION_DESIGNS
    if obligation in ADMISSION_DESIGNS:
        return default_compatibility(baseline).conditional_factorial(ADMISSION_DESIGNS[obligation])
    if obligation not in DESIGNS:
        raise ContractError('unimplemented lineage combination obligation')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[obligation])


def _source_binding(cell):
    return FrozenRecord.from_dict({'cell_digest': FrozenRecord.from_dict(cell.data()).content_hash,
                                   'scenario_digest': cell.scenario_digest})


def _read_events(path):
    if DockerExecutionBroker._has_link_component(path) or not path.is_file():
        raise ContractError('replay requires existing regular event files')
    return [FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]


def _transition(evidence, claims, cache, material, enabled, qualification=None):
    from research_loop.modular.admission_combination import FrozenAdmissionMaterial, transition
    if type(material) is FrozenAdmissionMaterial:
        return transition(evidence, claims, cache, material, enabled, qualification)
    b = material.data(); roots, relations = {}, {}
    source = {row['key']: row for row in b['originals']}
    observation_rows = [(row['key'], row, 'raw', row['content']) for row in b['originals']]
    observation_rows += [(row['key'], source[row['root']], row['representation'], row['content']) for row in b['representations']]
    if 'M2' in enabled:
        for key, row, representation, content in observation_rows:
            record = evidence.append({'kind': 'observation', 'root_material': row['root_material'],
                'content': content, 'subject_bindings': row['subject_bindings'],
                'independent_group': evidence.identity.group_id, 'representation': representation},
                {'trusted_validator': 'public-material-provenance', 'validator_verified': True, 'admitted': True})
            roots[key] = record.root_id
        for row in b['claims']:
            claim = claims.create(row['statement'], subject_bindings=row['subject_bindings'])
            claims.apply(claim.claim_id, {'supports': [roots[k] for k in row['supports']],
                'refutes': [roots[k] for k in row['refutes']], 'subject_bindings': row['subject_bindings']}, expected_revision=0)
            relations[row['key']] = claim.claim_id
            if row['depends_on']:
                claim = next(c for c in claims.claims() if c.claim_id == claim.claim_id)
                claims.link_dependencies(claim.claim_id, [relations[k] for k in row['depends_on']], expected_revision=claim.revision)
    before = claims.snapshot()
    builder = ContextBuilder(evidence.identity, budget_bytes=b['context_budget_bytes'])
    mode = 'candidate' if 'M3' in enabled else 'baseline'
    prior_context = cache.get_or_build(builder, b['question'], evidence, claims, mode=mode, baseline_summary=b['ordinary_summary'])
    if 'M2' in enabled:
        for row in b['withdrawals']:
            evidence.withdraw(roots[row['root']], row['reason'])
        claims.refresh_after_withdrawal()
    after_context = cache.get_or_build(builder, b['question'], evidence, claims, mode=mode, baseline_summary=b['ordinary_summary'])
    if 'M3' in enabled:
        # Obsolete cached context is discarded, rather than merely left unused.
        cache._items.clear()
        cache.get_or_build(builder, b['question'], evidence, claims, mode=mode, baseline_summary=b['ordinary_summary'])
    observations = ([{'binding': root.root_id, 'content': root.payload.data()['content']}
                     for root in evidence.roots()] if 'M2' in enabled else
                    [{'binding': key, 'content': content} for key, _, _, content in observation_rows])
    entries = after_context.entries.data()['entries']
    # The joint public projection contains observations and claims, not source authority details.
    for entry in entries:
        if entry.get('kind') == 'evidence':
            entry['payload'] = {k: v for k, v in entry['payload'].items() if k not in {'trusted_validator', 'validator_verified'}}
    public = FrozenRecord.from_dict({'observations': observations, 'memory': entries})
    if len(public.encoded.encode('utf-8')) > b['context_budget_bytes']:
        raise ContractError('public lineage projection exceeds frozen byte budget')
    return FrozenRecord.from_dict({'material_digest': material.record.content_hash,
        'raw_representation_denominator': len(observation_rows), 'root_denominator': len({FrozenRecord.from_dict(
            {'root': row['root_material'], 'bindings': row['subject_bindings']}).content_hash for row in b['originals']}),
        'root_bindings': roots, 'claim_bindings': relations, 'before_claims': before.data(),
        'after_claims': claims.snapshot().data(), 'evidence': evidence.snapshot().data(),
        'context_before': prior_context.data(), 'context_after': after_context.data(),
        'context_before_digest': prior_context.content_hash, 'context_after_digest': after_context.content_hash,
        'public': public.data(), 'public_digest': public.content_hash, 'public_bytes': len(public.encoded.encode('utf-8')),
        'context_budget_bytes': b['context_budget_bytes']})


def _validate(panel, cell, task, scenario, package, material):
    from research_loop.modular.admission_combination import DESIGNS as ADMISSION_DESIGNS, FrozenAdmissionMaterial
    if (panel.obligation_id in ADMISSION_DESIGNS) != (type(material) is FrozenAdmissionMaterial):
        raise ContractError('combination obligation requires its exact material type')
    if (not isinstance(panel, CombinationPanel) or cell not in panel.cells
            or panel.design != registered_design(panel.obligation_id, cell.runtime_arm.data()['baseline_digest'])
            or not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest
            or not isinstance(material, FrozenLineageMaterial) or not isinstance(scenario, FrozenRecord)
            or scenario.content_hash != cell.scenario_digest):
        raise ContractError('lineage combination frozen cell binding mismatch')
    expected = {'schema': 'lineage-combination-scenario-v1', 'obligation_id': panel.obligation_id,
        'design_digest': panel.design.content_hash, 'task_digest': task.content_hash,
        'replicate': cell.replicate, 'material_digest': material.record.content_hash}
    if scenario.data() != expected or material.data()['task_digest'] != task.content_hash or material.data()['identity'] != task.identity.data():
        raise ContractError('scenario must freeze the exact material before execution')


@dataclass(frozen=True)
class LineageCombinationResult:
    cell: object
    runtime: object
    solver: object
    transition: FrozenRecord
    joint_mechanism: FrozenRecord | None


def _review_context(cell, task, transition, index):
    role, question = ROLES[index]
    return FrozenRecord.from_dict({'panel_cell': opaque_panel_cell_binding(cell), 'public_task': task.data(),
        'review_role': role, 'review_question': question, 'sealed': True, 'material': transition.data()['public']})


def _joint(cell, transition, responses, package):
    changes = package.record.data()['changes']
    return FrozenRecord.from_dict({'schema': 'lineage-combination-public-context-v1',
        'panel_cell': opaque_panel_cell_binding(cell), 'material': transition.data()['public'],
        'review_responses': [r.data() for r in responses] if 'M5' in cell.runtime_arm.data()['enabled'] else None,
        'candidate_context': {'prompt': changes.get('prompt', {}), 'memory': changes.get('memory', {})}})


def run_lineage_combination_cell(*, panel, cell, task, scenario, package, material, source_verifier,
        objective, sidecar, public_inputs, image, broker, model, audit_verifier, timeout_seconds=20):
    _validate(panel, cell, task, scenario, package, material)
    if (not isinstance(source_verifier, DualMaterialVerifier) or not isinstance(objective, FrozenRecord)
            or not isinstance(sidecar, Path) or sidecar.exists() or not callable(model)
            or not isinstance(audit_verifier, AuditVerifier) or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120):
        raise ContractError('lineage runtime needs typed unused dependencies')
    check_material_inputs(material, task, broker, public_inputs)  # Before authority and model calls.
    from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
    admission = type(material) is FrozenAdmissionMaterial
    if admission and type(source_verifier) is not AdmissionMaterialVerifier:
        raise ContractError('admission requires actual dual qualification receipts')
    # Exercise the complete deterministic material contract before reserving external calls.
    e = EvidenceLedger(task.identity); c = ClaimLedger(e)
    if not admission: _transition(e, c, ContextCache(), material, set(cell.runtime_arm.data()['enabled']))
    source_hash = source_verifier.qualify(material, sidecar / 'source-verification.json', cell_binding=_source_binding(cell))
    qualification = source_verifier.assessments(material, sidecar/'source-verification.json', cell_binding=_source_binding(cell)) if admission else None
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
        slots=SLOTS, execution_limit=1, sidecar=sidecar / 'runtime', verifier=audit_verifier,
        required_audit=('measurement',), context_budget=material.data()['context_budget_bytes'])
    workflow = ModularWorkflow(session)
    transition = _transition(session.evidence, session.claims, session.cache, material, workflow.enabled, qualification)
    session._record('lineage_transition', {'transition': transition.data(), 'source_sha256': source_hash})
    responses, solver, joint = [], None, None
    try:
        review = None
        if 'M5' in workflow.enabled:
            review = workflow.reviews.open(task_binding=task.content_hash, evidence_snapshot=transition.content_hash,
                roles=[{'role_id': r, 'question': q} for r, q in ROLES], budget_units=2)
        for index, slot in enumerate(SLOTS[:2]):
            response = workflow.invoke_model(slot, model, instruction='Answer only the assigned public review question.',
                module_context=_review_context(cell, task, transition, index), baseline_summary=material.data()['ordinary_summary'])
            ReviewEngine._response(response.data())  # Same response contract in every arm.
            responses.append(response)
            if review:
                workflow.reviews.submit(review.review_id, role_id=ROLES[index][0], reviewer_id='public-review-'+str(index),
                    response=response.data(), cost_units=1)
                session._record('lineage_review_submission', {'response_digest': response.content_hash,
                    'barrier_open': workflow.reviews.barrier_open(review.review_id)})
        if review:
            revealed = workflow.reviews.reveal(review.review_id)
            if [r.response for r in revealed] != responses:
                raise ContractError('review reveal changed provider responses')
        joint = _joint(cell, transition, responses, package)
        if len(joint.encoded.encode('utf-8')) > material.data()['context_budget_bytes']:
            raise ContractError('reviewed public context exceeds frozen byte budget')
        session._record('lineage_joint', {'joint': joint.data(), 'transition_digest': transition.content_hash,
            'response_digests': [r.content_hash for r in responses], 'public_bytes': len(joint.encoded.encode('utf-8'))})
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=public_inputs,
            image=image, broker=broker, model=model, analysis_slot=SLOTS[2], final_slot=SLOTS[3],
            joint_mechanism=joint, panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),
            driver_id=cell.coverage_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal: _close_failure(session, cell, scenario, exc)
        joint = None
    status = 'succeeded' if solver is not None and solver.status == 'execution_succeeded' else 'failed'
    return LineageCombinationResult(cell, _runtime(cell, session, joint, status), solver, transition, joint)


def verify_lineage_combination_cell(result, *, panel, task, scenario, package, material, source_verifier, public_inputs, broker):
    if not isinstance(result, LineageCombinationResult):
        raise ContractError('typed lineage result required')
    _validate(panel, result.cell, task, scenario, package, material)
    check_material_inputs(material, task, broker, public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime, result.cell)
    path = result.runtime.trace_path; events = _read_events(path)
    source_hash = source_verifier.replay(material, path.parent.parent / 'source-verification.json', cell_binding=_source_binding(result.cell))
    from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
    if type(material) is FrozenAdmissionMaterial and type(source_verifier) is not AdmissionMaterialVerifier:
        raise ContractError('admission replay requires the configured qualifier')
    qualification = source_verifier.assessments(material, path.parent.parent/'source-verification.json', cell_binding=_source_binding(result.cell)) if type(material) is FrozenAdmissionMaterial else None
    enabled = set(result.cell.runtime_arm.data()['enabled'])
    e = EvidenceLedger(task.identity); c = ClaimLedger(e); e._log = _MemoryLog(); c._log = _MemoryLog()
    transition = _transition(e, c, ContextCache(), material, enabled, qualification)
    if transition != result.transition or _read_events(path.parent/'evidence.jsonl') != e._log.rows or _read_events(path.parent/'claims.jsonl') != c._log.rows:
        raise ContractError('actual lineage events differ from replayed original and withdrawal operations')
    transition_events = [v for v in events if v['stage'] == 'lineage_transition']
    if len(transition_events) != 1 or transition_events[0]['data'] != {'transition': transition.data(), 'source_sha256': source_hash}:
        raise ContractError('lineage transition does not bind source verification and replay')
    requests = [v for v in events if v['stage'] == 'model_request']
    if tuple(v['data']['request']['slot'] for v in requests) != SLOTS[:len(requests)] or any(_private_arm_marker(v['data']['request']) for v in requests):
        raise ContractError('lineage public request sequence or projection drift')
    if requests and events.index(transition_events[0]) >= events.index(requests[0]):
        raise ContractError('lineage operations occurred after the model saw their result')
    responses = {v['data']['request_digest']: FrozenRecord.from_dict(v['data']['response']) for v in events if v['stage'] == 'model_response'}
    review_engine = ReviewEngine(task.identity); review_engine._log = _MemoryLog()
    review = review_engine.open(task_binding=task.content_hash, evidence_snapshot=transition.content_hash,
        roles=[{'role_id': r, 'question': q} for r, q in ROLES], budget_units=2) if 'M5' in enabled else None
    actual_responses = []
    for index, request in enumerate(requests[:2]):
        if request['data']['request']['module_context'] != _review_context(result.cell, task, transition, index).data():
            raise ContractError('review does not consume actual post-transition state or is not sealed')
        response = responses.get(request['data']['request_digest'])
        if response is None: break
        try: ReviewEngine._response(response.data())
        except ContractError:
            if events[-1]['stage'] != 'driver_failure' or events[-1]['data'].get('request_digest') != request['data']['request_digest']:
                raise ContractError('invalid review response lacks original driver failure')
            break
        actual_responses.append(response)
        if review: review_engine.submit(review.review_id, role_id=ROLES[index][0], reviewer_id='public-review-'+str(index), response=response.data(), cost_units=1)
    if _read_events(path.parent/'reviews.jsonl') != review_engine._log.rows:
        raise ContractError('sealed review events differ from the actual provider responses')
    submissions = [v for v in events if v['stage'] == 'lineage_review_submission']
    expected_submissions = [{'response_digest': r.content_hash, 'barrier_open': i == 1}
                            for i, r in enumerate(actual_responses)] if review else []
    if [s['data'] for s in submissions] != expected_submissions:
        raise ContractError('review barrier opened before both actual submissions')
    for i, submission in enumerate(submissions):
        response_event = next(v for v in events if v['stage'] == 'model_response'
                              and v['data']['request_digest'] == requests[i]['data']['request_digest'])
        if (events.index(submission) <= events.index(response_event)
                or i+1 < len(requests) and events.index(submission) >= events.index(requests[i+1])):
            raise ContractError('review submission order contradicts its provider response')
    # Reconstruct the builtin context that RunSession actually produced at each slot.
    builder = ContextBuilder(task.identity, budget_bytes=material.data()['context_budget_bytes'])
    for request in requests:
        b = request['data']['request']; summary = material.data()['ordinary_summary'] if b['slot'] in SLOTS[:2] else ''
        expected = builder.build(canonical(task.payload.data()),
            e, c, mode='candidate' if 'M3' in enabled else 'baseline', baseline_summary=summary).public_data()
        if b['context'] != expected:
            raise ContractError('request context was not reconstructed from the actual current ledger')
    joints = [v for v in events if v['stage'] == 'lineage_joint']
    if result.joint_mechanism is None:
        if result.solver is not None or joints or len(requests) > 2 or result.runtime.status != 'failed':
            raise ContractError('missing joint must preserve a pre-solver failure')
        if (len(actual_responses) == 2 and len(_joint(result.cell, transition, actual_responses, package).encoded.encode('utf-8'))
                <= material.data()['context_budget_bytes']):
            raise ContractError('valid completed reviews cannot invent a pre-solver rejection')
    else:
        expected_joint = _joint(result.cell, transition, actual_responses, package)
        if len(actual_responses) != 2 or expected_joint != result.joint_mechanism or len(joints) != 1:
            raise ContractError('joint context does not consume the original matched reviews')
        expected_event = {'joint': expected_joint.data(), 'transition_digest': transition.content_hash,
            'response_digests': [r.content_hash for r in actual_responses], 'public_bytes': len(expected_joint.encoded.encode('utf-8'))}
        if joints[0]['data'] != expected_event or result.solver is None or result.solver.session.sidecar != path.parent:
            raise ContractError('shared solver joint/session binding drift')
        last_review = max(i for i, v in enumerate(events) if v['stage'] == 'model_response'
                          and v['data']['request_digest'] in {r['data']['request_digest'] for r in requests[:2]})
        if (events.index(joints[0]) <= last_review
                or len(requests) > 2 and events.index(joints[0]) >= events.index(requests[2])):
            raise ContractError('joint context must follow both reviews and precede analysis')
        state = _solver_journal_state(events); _compare_solver_result(result.solver, state)
        if result.runtime.status != ('succeeded' if state['status'] == 'execution_succeeded' else 'failed'):
            raise ContractError('solver failure was relabeled')
        for request in requests[2:]:
            context = request['data']['request']['module_context']
            if context.get('joint_mechanism') != expected_joint.data() or context.get('joint_mechanism_digest') != expected_joint.content_hash:
                raise ContractError('solver ignored the actual public joint material')
        _verify_solver_files(state, events, path, material)
    return FrozenRecord.from_dict({'schema': 'lineage-combination-verification-v1', 'status': result.runtime.status,
        'engineering_verified': True, 'cell_key': list(result.cell.key), 'transition_digest': transition.content_hash,
        'scientific_validity': 'not_measured'})


def _verify_solver_files(state, events, path, material):
    if state['analysis'] is None: return
    try: program = _program_from(state['analysis'])
    except ContractError:
        if state['status'] != 'analysis_rejected': raise
        return
    if state['status'] == 'analysis_rejected':
        raise ContractError('valid analysis cannot be relabeled rejected')
    execution = state['execution']
    if execution is not None and execution.artifact is not None:
        fixed = path.parent/'analysis-1.py'; expected = program.replace('\n', os.linesep).encode('utf-8')
        if (DockerExecutionBroker._has_link_component(fixed) or Path(execution.artifact.path) != fixed.absolute()
                or not fixed.is_file() or fixed.stat().st_size != len(expected) or fixed.read_bytes() != expected
                or execution.artifact.sha256 != hashlib.sha256(expected).hexdigest() or execution.artifact.byte_count != len(expected)):
            raise ContractError('literal solver program and actual artifact differ')
        from research_loop.modular.panel_receipts import _failed_solve_public_inputs
        inputs = _failed_solve_public_inputs(material.data()['public_artifacts'])
        if FrozenRecord.from_dict(execution.record.data().get('input_artifacts', {})) != FrozenRecord.from_dict(inputs):
            raise ContractError('execution omitted or changed the frozen inputs')
        if execution.status in {'succeeded', 'failed'} and (type(execution.record.data().get('exit_code')) is not int or (execution.record.data()['exit_code'] == 0) != (execution.status == 'succeeded')):
            raise ContractError('execution status contradicts literal exit code')
    requests = [v['data']['request'] for v in events if v['stage'] == 'model_request' and v['data']['request']['slot'] in SLOTS[2:]]
    for request in requests:
        context = request['module_context']
        if context.get('public_artifacts') != material.data()['public_artifacts']:
            raise ContractError('solver request changed the exact public input set')
        if request['slot'] == 'final_answer':
            if execution is None or execution.artifact is None:
                raise ContractError('final answer has no corresponding execution')
            record = execution.record.data()
            expected_fields = {'analysis': state['analysis'].data(), 'analysis_digest': state['analysis'].content_hash,
                'analysis_program_sha256': execution.artifact.sha256, 'execution_digest': execution.content_hash,
                'execution_status': execution.status, 'execution_input_artifacts': record['input_artifacts'],
                'required_objective_digest': FrozenRecord.from_dict(events[0]['data']['objective']).content_hash,
                'execution_feedback': [{'execution_digest': execution.content_hash, 'status': execution.status,
                    'stdout': record.get('stdout', ''), 'stderr': record.get('stderr', ''), 'program_sha256': execution.artifact.sha256}]}
            if (any(context.get(k) != v for k, v in expected_fields.items())
                    or request['execution_feedback'] != [{'id': execution.content_hash, 'status': execution.status,
                        'stdout': record.get('stdout', ''), 'stderr': record.get('stderr', '')}]):
                raise ContractError('final answer context does not bind the actual analysis and execution')
    if state['answer'] is not None:
        try: _candidate_from(state['answer'], FrozenRecord.from_dict(events[0]['data']['objective']))
        except ContractError:
            if state['status'] != 'answer_rejected': raise
        else:
            if state['status'] == 'answer_rejected': raise ContractError('valid answer cannot be relabeled rejected')
