"""Actual C4 history preparation/build and target solve with original replay."""
from dataclasses import dataclass
from pathlib import Path
import json
import re
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_modules import slots, prepare, joint, select_builder, execute_retrieval, PROPOSAL_INSTRUCTION, REVISION_INSTRUCTION
from research_loop.modular.full_loo_panel import runtime_arm, OBLIGATION
from research_loop.modular.metaprogram_training import _exclusive, _sha, _path, _read_record, _checked_build
from research_loop.modular.state_improvement_build import FrozenProviderLedger, check_history
from research_loop.modular.admission_combination import AdmissionMaterialVerifier
from research_loop.modular.lineage_combination_driver import _transition, _source_binding, _read_events, _MemoryLog, _verify_solver_files
from research_loop.modular.lineage_combination_material import check_material_inputs, DualMaterialVerifier
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.context import ContextCache, ContextBuilder
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, RestrictedBuilderPort, BuilderRunReceipt
from research_loop.modular.exploration_scheduler_combination import run_phase, verify_phase, check_inputs
from research_loop.modular.retrieval_review_combination_driver import _verify_sources, public_retrieval
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.combination_benchmark_driver import _runtime, _private_arm_marker
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession, verify_trace
from research_loop.modular.artifact_catalogue import source_snapshot, ArtifactCatalogue
from research_loop.modular.context_artifact import verify_session_context_artifacts
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.state_retrieval_combination_driver import _INSTRUCTIONS
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import ContractError, canonical


def files(root):
    return {p.relative_to(root).as_posix():_sha(_path(p).read_bytes()) for p in root.rglob('*') if p.is_file() and p.name!='receipt.json'}


@dataclass(frozen=True)
class FullLooResult:
    root: Path
    record: FrozenRecord
    cell: PanelCell
    runtime: object
    solver: object
    joint_mechanism: FrozenRecord | None
    phase: FrozenRecord | None


def run_stage(*, plan, recipe, stage, cell, task, package, material, phase_material,
              source_verifier, corpus_verifier, provider, broker, inputs, model, audit_verifier, root):
    """One immutable recipe; exceptions close a charged failed denominator."""
    root.mkdir(parents=True,exist_ok=False)
    session=solver=prepared=phase=joined=transition=candidate=None; reason=None
    catalogue_source=source_snapshot(Path(__file__))
    try:
        check_material_inputs(material.state(),task,broker,inputs);check_inputs(phase_material,task,broker,inputs)
        binding=_source_binding(cell)
        source=source_verifier.qualify(material.state(),root/'source/source.json',cell_binding=binding)
        if any(c['cost_unknown'] for c in json.loads((root/'source/source.json').read_bytes())['calls']):
            raise ContractError('unknown qualification cost blocks work')
        qualification=source_verifier.assessments(material.state(),root/'source/source.json',cell_binding=binding)
        nonbaseline=stage=='history_build' or recipe['procedure']!='baseline_b0'
        corpus=None
        if nonbaseline:
            corpus=corpus_verifier.qualify(material,root/'corpus/source.json',cell_binding=binding)
            if any(c['cost_unknown'] for c in json.loads((root/'corpus/source.json').read_bytes())['calls']):
                raise ContractError('unknown corpus cost blocks work')
        session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=plan.objective(stage),
            slots=slots(recipe,stage),execution_limit=int(stage=='target'),sidecar=root/'runtime',verifier=audit_verifier,
            required_audit=('measurement',),context_budget=material.state().data()['context_budget_bytes'],
            experiment_id=plan.record.content_hash)
        workflow=ModularWorkflow(session)
        transition=_transition(session.evidence,session.claims,session.cache,material.state(),workflow.enabled,qualification)
        session._record('c4_state',{'transition':transition.data(),'source_sha256':source,'corpus_sha256':corpus})
        enabled=set(workflow.enabled)
        for module in ('M1','M2','M3'):
            session.record_artifact(kind='lineage_transition',module=module,payload=transition,
                status='produced' if module in enabled else 'not_applied',producer_source=catalogue_source)
        if nonbaseline:
            def record(stage, data):
                event=session._record(stage,data)
                module={'c4_prediction_frozen':'M4','c4_review_sealed':'M5','c4_review_reveal':'M5','c4_choice_frozen':'M7'}.get(stage)
                if module: session.record_artifact(kind=stage,module=module,payload=data,
                    status='produced' if module in enabled else 'not_applied',producer_source=catalogue_source)
                return event
            prepared=prepare(cell=cell,task=task,package=package,transition=transition,predictions=workflow.predictions,reviews=workflow.reviews,
                invoke=lambda slot,instruction,context:session.invoke(slot,model,instruction=instruction,module_context=context),
                record=record,retrieve=lambda:execute_retrieval(session,task,material,provider,'M6' in workflow.enabled),phase_material=phase_material)
            session.record_artifact(kind='retrieval_result',module='M6',payload=prepared.data()['retrieval'],
                status='produced' if 'M6' in enabled else 'not_applied',producer_source=catalogue_source)
            phase=run_phase(material=phase_material,cell=cell,objective=plan.objective(stage),root=root/'phase',broker=broker,inputs=inputs,
                image=plan.data()['image'],timeout_seconds=plan.data()['timeout_seconds'],selected_job_id=prepared.data()['choice']['job_id'])
            session._record('c4_phase',{'phase_digest':phase.content_hash})
            for module in ('M7','M8'):
                session.record_artifact(kind='exploration_phase_receipt',module=module,payload=phase,
                    status='produced' if module in enabled else 'not_applied',producer_source=catalogue_source)
        joined=joint(prepared,phase,cell,task,package)
        session._record('c4_joint',{'joint':joined.data(),'joint_digest':joined.content_hash})
        if stage=='history_build':
            slot=slots(recipe,stage)[-1];instruction=PROPOSAL_INSTRUCTION if recipe['history_build_levels']['M9'] else REVISION_INSTRUCTION
            response=session.invoke(slot,model,instruction=instruction,module_context=joined)
            selected=select_builder(response,recipe,plan.fixed_builder)
            session._record('c4_builder_request',{'builder':selected.record.data(),'parent':package.digest,'search_cost':1})
            manifest=TrainingManifest(FrozenRecord.from_dict(package.record.data()['training_manifest']))
            candidate,receipt=RestrictedBuilderPort().execute(selected,manifest,package,expected_builder_digest=selected.digest,
                expected_entrypoint=selected.entrypoint,search_cost=1)
            _checked_build(candidate,receipt,selected,package)
            _exclusive(root/'candidate.json',candidate.record);_exclusive(root/'builder.json',selected.record)
            _exclusive(root/'builder-receipt.json',receipt.record)
            session._record('c4_builder_result',{'candidate_digest':candidate.digest,'receipt':receipt.record.data()})
            session.record_artifact(kind='training_limited_candidate',module='M9',payload=candidate.record,
                status='produced' if 'M9' in enabled else 'not_applied',producer_source=catalogue_source)
            session._record('c4_build_terminal',{'candidate_digest':candidate.digest});session._terminal=True
        else:
            solver=run_benchmark_solve_in_session(session=session,workflow=workflow,public_inputs=inputs,image=plan.data()['image'],broker=broker,
                model=model,analysis_slot='analysis_program',final_slot='final_answer',joint_mechanism=joined,
                panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)),driver_id=OBLIGATION,timeout_seconds=plan.data()['timeout_seconds'])
    except Exception as exc:
        reason=type(exc).__name__+': '+str(exc)
        if session is not None and not session._terminal:
            try:
                session.controller_failure(driver_id=OBLIGATION,error_type=type(exc).__name__,panel_cell=opaque_panel_cell_binding(cell))
            except Exception as journal_error:
                reason+='; failure_journal:'+type(journal_error).__name__
                _exclusive(root/'artifact-journal-failure.json',FrozenRecord.from_dict({
                    'schema':'artifact-journal-failure-v1','original_error_type':type(exc).__name__,
                    'journal_error_type':type(journal_error).__name__,'trace_path':'runtime/trace.jsonl'}))
                session._terminal=True
    # Explicit separate success predicates prevent an auxiliary success from
    # promoting a missing common solve or missing restricted build.
    status='succeeded' if (candidate is not None if stage=='history_build' else solver is not None and solver.status=='execution_succeeded') and reason is None else 'failed'
    seal=None
    if session is not None:
        try:
            seal=session.artifacts.seal()
        except Exception as exc:
            reason=(reason+'; ' if reason else '')+'artifact_catalogue_seal:'+type(exc).__name__
            status='failed'
            _exclusive(root/'artifact-catalogue-failure.json',FrozenRecord.from_dict({'schema':'artifact-catalogue-seal-failure-v1',
                'error_type':type(exc).__name__,'trace_path':'runtime/trace.jsonl'}))
    record=FrozenRecord.from_dict({'schema':'c4-stage-receipt-v2','plan_digest':plan.record.content_hash,'recipe':recipe,'stage':stage,
        'cell':cell.data(),'status':status,'reason':reason,'candidate_digest':candidate.digest if status=='succeeded' and candidate else None,
        'artifact_catalogue_seal':seal.data() if seal else None,'files':files(root)})
    _exclusive(root/'receipt.json',record)
    return FullLooResult(root,record,cell,_runtime(cell,session,joined,status) if session else None,solver,joined,phase)


def verify_stage(result, *, plan, recipe, stage, task, package, material, phase_material, source_verifier, corpus_verifier, broker, inputs, ledger,
                 provider_scope_id=None, require_provider_eligible=True):
    """Replay a C4 stage against its original provider evidence.

    The legacy route supplies ``FrozenProviderLedger``.  The separately
    versioned native C4 route supplies a sealed ``PhaseProviderLedger`` and a
    mandatory globally unique scope identifier.  Keeping that dispatch here
    lets both routes replay the same actual builder, Docker and solver trace
    without treating a native ledger as a Codex ledger.
    """
    native = provider_scope_id is not None
    if (type(result) is not FullLooResult or (not native and type(ledger) is not FrozenProviderLedger)
            or (native and (type(provider_scope_id) is not str or not provider_scope_id
                           or type(require_provider_eligible) is not bool))):
        raise ContractError('C4 exact original stage and provider ledger required')
    if type(source_verifier) is not AdmissionMaterialVerifier or type(corpus_verifier) is not DualMaterialVerifier:
        raise ContractError('C4 replay requires exact source authority verifiers')
    root=result.root;cell=result.cell;b=result.record.data()
    if (set(b)!={'schema','plan_digest','recipe','stage','cell','status','reason','candidate_digest','artifact_catalogue_seal','files'} or b['schema']!='c4-stage-receipt-v2'
            or _read_record(root/'receipt.json')!=result.record or b!={**b,'plan_digest':plan.record.content_hash,'recipe':recipe,'stage':stage,'cell':cell.data()}
            or b['status']!='succeeded' or b['files']!=files(root) or cell.task_digest!=task.content_hash or cell.identity!=task.identity
            or cell.package_digest!=package.digest or cell.runtime_arm!=runtime_arm(plan.composition,recipe,stage)):
        raise ContractError('C4 original bytes, recipe, task, package or runtime activation drift')
    check_material_inputs(material.state(),task,broker,inputs);check_inputs(phase_material,task,broker,inputs)
    if stage=='history_build':check_history(plan.history,material.state(),broker,inputs)
    path=root/'runtime'/'trace.jsonl';verify_trace(path);events=_read_events(path);lock=events[0]['data']
    catalogue_seal=FrozenRecord.from_dict(b['artifact_catalogue_seal'])
    run_id=catalogue_seal.data().get('binding',{}).get('run_id')
    if type(run_id) is not str or len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id):
        raise ContractError('catalogue has no original run identifier')
    catalogue=ArtifactCatalogue(root/'runtime'/'artifacts.jsonl',identity=task.identity,run_id=run_id,
        experiment_id=plan.record.content_hash,lock_digest=FrozenRecord.from_dict(lock).content_hash,producer_source=source_snapshot(Path(__file__)))
    catalogue.verify(catalogue_seal)
    catalogue_trace=[d.data()['payload']['canonical'] for d in catalogue.records() if d.data()['kind']=='trace_event']
    if catalogue_trace!=events:
        raise ContractError('trace and catalogue journal transaction differs')
    from research_loop.modular.evidence_artifacts import verify_evidence_artifacts
    evidence_replay = verify_evidence_artifacts(catalogue, root/'runtime').data()
    invocation_snapshots = {request_digest: {'evidence': FrozenRecord.from_dict(snapshots['evidence_snapshot']),
        'claims': FrozenRecord.from_dict(snapshots['claims_snapshot'])}
        for request_digest, snapshots in evidence_replay['model_inputs'].items()}
    verify_session_context_artifacts(task=task, lock=FrozenRecord.from_dict(lock), events=events,
        catalogue=catalogue, invocation_snapshots=invocation_snapshots)
    from research_loop.modular.m4_m5_artifacts import verify_m4_m5_artifacts
    from research_loop.modular.retrieval_artifacts import verify_retrieval_event_stream, verify_retrieval_artifacts
    verify_m4_m5_artifacts(catalogue, root/'runtime')
    verify_retrieval_event_stream(catalogue, trace_path=path, task=task)
    if (lock['task_digest']!=task.content_hash or lock['identity']!=task.identity.data() or lock['package_digest']!=package.digest
            or lock['arm']!=cell.runtime_arm.data() or lock['objective']!=plan.objective(stage).data() or lock['slots']!=list(slots(recipe,stage))
            or lock['execution_limit']!=int(stage=='target') or lock['required_audit']!=['measurement'] or lock['context_budget']!=material.state().data()['context_budget_bytes']):
        raise ContractError('C4 lock allocation drift')
    if native:
        from research_loop.modular.phase_provider import PhaseProviderLedger
        if type(ledger) is not PhaseProviderLedger:
            raise ContractError('C4 native replay requires a sealed phase provider ledger')
        ledger.bind_events(events, scope_id=provider_scope_id, require_eligible=require_provider_eligible)
    else:
        ledger.bind_events(events)
    binding=_source_binding(cell);source=source_verifier.replay(material.state(),root/'source/source.json',cell_binding=binding)
    q=source_verifier.assessments(material.state(),root/'source/source.json',cell_binding=binding)
    nonbaseline=stage=='history_build' or recipe['procedure']!='baseline_b0'
    corpus=corpus_verifier.replay(material,root/'corpus/source.json',cell_binding=binding) if nonbaseline else None
    for filename in ('source/source.json','corpus/source.json') if nonbaseline else ('source/source.json',):
        if any(c['cost_unknown'] for c in json.loads((root/filename).read_bytes())['calls']):raise ContractError('unknown qualification cost')
    evidence=EvidenceLedger(task.identity);claims=ClaimLedger(evidence);cache=ContextCache()
    evidence._log=_MemoryLog();claims._log=_MemoryLog()
    transition=_transition(evidence,claims,cache,material.state(),set(cell.runtime_arm.data()['enabled']),q)
    expected=[]
    def record(name,data):expected.append((name,data))
    record('c4_state',{'transition':transition.data(),'source_sha256':source,'corpus_sha256':corpus})
    requests=[e for e in events if e['stage']=='model_request']; responses=[e for e in events if e['stage']=='model_response'];cursor=0
    context=ContextBuilder(task.identity,budget_bytes=lock['context_budget']).build(canonical(task.payload.data()),evidence,claims,
        mode='candidate' if 'M3' in cell.runtime_arm.data()['enabled'] else 'baseline',baseline_summary='').public_data()
    def invoke(slot,instruction,module):
        nonlocal cursor
        request=requests[cursor];response=responses[cursor];cursor+=1
        body=request['data']['request']
        wanted={'schema':'public-model-request-v1','task':task.data(),'lock_digest':FrozenRecord.from_dict(lock).content_hash,
            'objective':plan.objective(stage).data(),'slot':slot,'instruction':instruction,'context':context,'module_context':module.data(),'execution_feedback':[]}
        if body!=wanted or response['data']['request_digest']!=request['data']['request_digest']:
            raise ContractError('C4 original model instruction/context differs from reconstructed native pipeline')
        return FrozenRecord.from_dict(response['data']['response'])
    predictions=PredictionRegistry(task.identity);reviews=ReviewEngine(task.identity)
    predictions._log=_MemoryLog();reviews._log=_MemoryLog()
    prepared=phase=None
    if nonbaseline:
        verify_retrieval_artifacts(catalogue, trace_path=path, task=task, material=material.retrieval(),
            enabled='M6' in cell.runtime_arm.data()['enabled'])
        # The older retrieval-first verifier owns the retrieval transaction,
        # while C4 owns its later placement after both sealed critiques.
        retrieval_events=[e for e in events if e['stage'].startswith('q8_') or e['stage']=='retrieval_review_sources']
        retrieval=_verify_sources(retrieval_events,task,material.retrieval(),'M6' in cell.runtime_arm.data()['enabled'])
        prepared=prepare(cell=cell,task=task,package=package,transition=transition,predictions=predictions,reviews=reviews,
            invoke=invoke,record=record,retrieve=lambda:public_retrieval(retrieval),phase_material=phase_material)
        phase=verify_phase(material=phase_material,cell=cell,objective=plan.objective(stage),root=root/'phase',image=plan.data()['image'],
            timeout_seconds=plan.data()['timeout_seconds'],inputs=inputs,selected_job_id=prepared.data()['choice']['job_id'])
        if result.phase!=phase:raise ContractError('C4 phase result changed')
        record('c4_phase',{'phase_digest':phase.content_hash})
    joined=joint(prepared,phase,cell,task,package);record('c4_joint',{'joint':joined.data(),'joint_digest':joined.content_hash})
    if result.joint_mechanism!=joined:raise ContractError('C4 common solve dropped an actual module output')
    if stage=='history_build':
        response=invoke(slots(recipe,stage)[-1],PROPOSAL_INSTRUCTION if recipe['history_build_levels']['M9'] else REVISION_INSTRUCTION,joined)
        selected=select_builder(response,recipe,plan.fixed_builder)
        candidate=CandidatePackage(_read_record(root/'candidate.json'));receipt=BuilderRunReceipt(_read_record(root/'builder-receipt.json'))
        _checked_build(candidate,receipt,selected,package)
        if _read_record(root/'builder.json')!=selected.record or candidate.digest!=b['candidate_digest']:raise ContractError('C4 selected builder differs')
        record('c4_builder_request',{'builder':selected.record.data(),'parent':package.digest,'search_cost':1})
        record('c4_builder_result',{'candidate_digest':candidate.digest,'receipt':receipt.record.data()})
        record('c4_build_terminal',{'candidate_digest':candidate.digest})
    else:
        PanelReceiptVerifier()._verify_runtime(result.runtime,cell)
        state=_solver_journal_state(events);_compare_solver_result(result.solver,state);_verify_solver_files(state,events,path,material.state())
        decision=result.solver.decision.data()
        if decision['decision']!='unknown' or decision['scientific_validated'] is not False or decision['programme_complete'] is not False:
            raise ContractError('C4 engineering solve cannot claim P0-qualified scientific execution')
        execution=state['execution']
        if execution is None:raise ContractError('C4 target lacks actual restricted solver execution')
        argv=execution.record.data().get('argv')
        if not isinstance(argv,list) or len(argv)<6 or not re.fullmatch('research-loop-[0-9a-f]{20}',argv[5]):
            raise ContractError('C4 solver requires the actual bounded Docker invocation')
        expected_argv=['docker','run','--pull','never','--name',argv[5],'--rm','--network','none','--read-only',
            '--user','1000:1000','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--pids-limit','128','--memory','1g',
            '--cpus','1.0','--cap-drop','ALL','--security-opt','no-new-privileges']
        for key in sorted(inputs):expected_argv.extend(['-v',DockerExecutionBroker._mount_source(inputs[key].absolute())+':/input/'+key+':ro'])
        expected_argv.extend(['-v',DockerExecutionBroker._mount_source((path.parent/'analysis-1.py').absolute())+':/task/analysis.py:ro',
            plan.data()['image'],'python3','/task/analysis.py'])
        if argv!=expected_argv:raise ContractError('C4 solver Docker limits or exact program/input mounts drift')
        for e in requests[cursor:]:
            r=e['data']['request'];m=r['module_context']
            if (r['instruction']!=_INSTRUCTIONS[r['slot']] or r['context']!=context or m.get('joint_mechanism')!=joined.data()
                    or m.get('joint_mechanism_digest')!=joined.content_hash or m.get('panel_cell')!=opaque_panel_cell_binding(cell)):
                raise ContractError('C4 solve omitted reconstructed composition')
    for name,log in [('evidence',evidence._log),('claims',claims._log),('predictions',predictions._log),('reviews',reviews._log)]:
        if _read_events(root/'runtime'/(name+'.jsonl'))!=log.rows:raise ContractError('C4 native '+name+' journal drift')
    if ([(e['stage'],e['data']) for e in events if e['stage'].startswith('c4_')]!=expected
            or tuple(e['data']['request']['slot'] for e in requests)!=slots(recipe,stage)
            or any(_private_arm_marker(e['data']['request']) for e in requests)):
        raise ContractError('C4 operation sequence or public label isolation drift')
    if nonbaseline:
        positions={name:next(i for i,e in enumerate(events) if e['stage']==name) for name in ('c4_state','c4_prediction_frozen','c4_review_reveal','q8_retrieval_request','c4_choice_frozen','c4_phase','c4_joint')}
        if list(positions.values())!=sorted(positions.values()):raise ContractError('C4 prospective freeze/reveal/execution order drift')
        for slot,earlier in [('m4_plan','c4_state'),('review_first','c4_prediction_frozen'),('bounded_choice','c4_review_reveal'),(slots(recipe,stage)[-2 if stage=='target' else -1],'c4_joint')]:
            if next(i for i,e in enumerate(events) if e['stage']=='model_request' and e['data']['request']['slot']==slot)<=positions[earlier]:
                raise ContractError('C4 invocation precedes its prerequisite')
    return FrozenRecord.from_dict({'schema':'c4-stage-verified-v1','stage_digest':result.record.content_hash,'engineering_verified':True,'scientific_effect':'not_measured'})
