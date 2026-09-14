"""C4 native Grok provider route, deliberately separate from the Codex v1 route.

This module consumes the closed public TRAIN provider and phase scope ledger.
It does not open validation inputs, activate a candidate, or call an API route.
The native provider owns one fresh ACP context per MAIN opportunity; the phase
session owns the global 45-history plus 124-target partition.
"""
from dataclasses import dataclass
from pathlib import Path
import json

from evaluation.modular.combination_scoring import _score_input_payload, verify_combination_adapted_receipt
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.admission_combination import AdmissionMaterialVerifier
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combination_train_controller import _usage
from research_loop.modular.combination_train_source import CombinationTrainSource
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_composition import candidate_build_key
from research_loop.modular.full_loo_controller import FullLooRun, compile_panel, recipes
from research_loop.modular.full_loo_driver import run_stage, verify_stage
from research_loop.modular.full_loo_modules import model_schemas, slots
from research_loop.modular.full_loo_panel import OBLIGATION, runtime_arm
from research_loop.modular.lineage_combination_material import DualMaterialVerifier
from research_loop.modular.metaprogram_training import _Journal, _exclusive, _path, _read_record
from research_loop.modular.state_improvement_build import check_history
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.phase_provider import (PhaseProviderAbort, PhaseProviderLedger, PhaseProviderSession, call_accounting,
    provider_configuration, validate_configuration)
from research_loop.modular.train_provider import GrokTrainProvider
from research_loop.ontology import ContractError


NATIVE_SCHEMA = 'c4-full-loo-native-provider-plan-v2'
NATIVE_LEDGER_SCHEMA = 'c4-native-candidate-barrier-v2'


def _scope(stage, recipe_id, task_digest):
    return 'c4-native-v2:' + stage + ':' + recipe_id + ':' + task_digest


def _native_caps():
    return {slot: 8192 if slot == 'analysis_program' else 2048 for slot in model_schemas()}


@dataclass(frozen=True)
class FrozenNativeFullLooRuntimePlan:
    """Native-only attachment to an already frozen C4 v1 composition plan."""
    record: FrozenRecord
    legacy: object

    def native_data(self): return self.record.data()
    def data(self): return {**self.legacy.data(), **self.native_data()}
    @property
    def composition(self): return self.legacy.composition
    @property
    def history(self): return self.legacy.history
    @property
    def history_inputs(self): return self.legacy.history_inputs
    @property
    def parent(self): return self.legacy.parent
    @property
    def fixed_builder(self): return self.legacy.fixed_builder
    def material(self, task): return self.legacy.material(task)
    def phase_material(self, task): return self.legacy.phase_material(task)
    def objective(self, stage): return self.legacy.objective(stage)
    def check_packets(self, packets): return self.legacy.check_packets(packets)

    def __post_init__(self):
        from research_loop.modular.full_loo_controller import FrozenFullLooRuntimePlan
        if (type(self) is not FrozenNativeFullLooRuntimePlan or type(self.record) is not FrozenRecord
                or type(self.legacy) is not FrozenFullLooRuntimePlan):
            raise ContractError('exact native C4 plan and original C4 freeze required')
        self.legacy.__post_init__()
        b = self.native_data()
        if set(b) != {'schema', 'legacy_plan_digest', 'provider_configuration', 'provider_scope_schema'} or b['schema'] != NATIVE_SCHEMA:
            raise ContractError('exact versioned native C4 plan required')
        if b['legacy_plan_digest'] != self.legacy.record.content_hash or b['provider_scope_schema'] != 'train-phase-provider-ledger-v2':
            raise ContractError('native C4 plan must bind the original C4 plan and scope ledger')
        config = FrozenRecord.from_dict(b['provider_configuration'])
        expected = self.composition.data()['allocation']['model_calls']
        validate_configuration(config, schemas=model_schemas(), main_opportunities=expected)
        native = config.data()['native_config']
        if (config.data()['provider_kind'] != 'grok-acp-public-train-v1' or expected != 169
                or native['slot_output_caps'] != _native_caps() or native['slot_input_byte_caps'] != {s: 262144 for s in model_schemas()}
                or native['observed_main_token_cap'] != 131072):
            raise ContractError('native C4 requires exactly the frozen Grok MAIN allocation and per-slot bounds')


@dataclass(frozen=True)
class NativeFullLooBarrier:
    root: Path
    record: FrozenRecord
    plan: FrozenNativeFullLooRuntimePlan
    builds: tuple
    ledger: PhaseProviderLedger
    source_verifier: object
    corpus_verifier: object
    broker: object
    packets: tuple

    def package(self, recipe):
        match = next(r for r in self.builds if candidate_build_key(r.record.data()['recipe']) == candidate_build_key(recipe))
        return CandidatePackage(_read_record(match.root / 'candidate.json'))

    def verify(self):
        if (type(self) is not NativeFullLooBarrier or type(self.plan) is not FrozenNativeFullLooRuntimePlan
                or type(self.ledger) is not PhaseProviderLedger or len(self.builds) != 9):
            raise ContractError('complete native C4 candidate barrier required')
        self.plan.__post_init__(); self.plan.check_packets(self.packets); self.ledger.verify()
        if _read_record(self.root / 'native-plan.json') != self.plan.record or _read_record(self.root / 'native-candidate-barrier.json') != self.record:
            raise ContractError('native C4 plan or candidate barrier was replaced')
        expected = {'schema': NATIVE_LEDGER_SCHEMA, 'plan_digest': self.plan.record.content_hash,
            'build_receipts': [r.record.content_hash for r in self.builds],
            'provider_ledger_digest': self.ledger.record.content_hash,
            'candidate_selections': {r['id']: self.package(r).digest for r in self.plan.composition.data()['cells'] if r['status'] == 'executable'}}
        if self.record.data() != expected:
            raise ContractError('native C4 candidate sharing or sealed history evidence drift')
        for result, recipe in zip(self.builds, recipes(self.plan), strict=True):
            scope_id = _scope('history_build', recipe['id'], self.plan.history.task.content_hash)
            _check_scope(self.ledger, scope_id, slots(recipe, 'history_build'))
            verify_stage(result, plan=self.plan, recipe=recipe, stage='history_build', task=self.plan.history.task,
                package=self.plan.parent, material=self.plan.material(self.plan.history.task.content_hash),
                phase_material=self.plan.phase_material(self.plan.history.task.content_hash), source_verifier=self.source_verifier,
                corpus_verifier=self.corpus_verifier, broker=self.broker, inputs=dict(self.plan.history_inputs), ledger=self.ledger,
                provider_scope_id=scope_id, require_provider_eligible=False)


def _check_scope(ledger, scope_id, expected_slots):
    calls = ledger.calls_for_scope(scope_id)
    if tuple(c.data()['slot'] for c in calls) != tuple(expected_slots):
        raise ContractError('native C4 scope has a missing, foreign, or reordered slot')


def verify_native_full_loo_cell(result, *, barrier, panel, ledger):
    if type(barrier) is not NativeFullLooBarrier or type(ledger) is not PhaseProviderLedger:
        raise ContractError('native C4 requires typed barrier and target seal')
    barrier.verify(); expected, _ = compile_panel(barrier)
    if panel != expected or result.cell not in panel.cells:
        raise ContractError('native C4 scorer panel drift')
    recipe = next(r for r in barrier.plan.composition.data()['cells'] if r['id'] == result.cell.arm_id)
    scope_id = _scope('target', recipe['id'], result.cell.task_digest)
    _check_scope(ledger, scope_id, slots(recipe, 'target'))
    return verify_stage(result, plan=barrier.plan, recipe=recipe, stage='target', task=next(p.task for p in barrier.packets if p.task.content_hash == result.cell.task_digest),
        package=barrier.package(recipe), material=barrier.plan.material(result.cell.task_digest),
        phase_material=barrier.plan.phase_material(result.cell.task_digest), source_verifier=barrier.source_verifier,
        corpus_verifier=barrier.corpus_verifier, broker=barrier.broker,
        inputs={'public_csv': next(p.csv_path for p in barrier.packets if p.task.content_hash == result.cell.task_digest)}, ledger=ledger,
        provider_scope_id=scope_id, require_provider_eligible=True)


def run_native_full_loo_train(plan, *, prospective_exporter, snapshot_root, export_root, run_root, provider,
                              audit_verifier, source_verifier, corpus_verifier, retrieval_provider, scorer_factory,
                              execution_authority, scorer_authority_keys):
    """Run the entire C4 grid through one bounded, scoped native provider session."""
    if type(plan) is not FrozenNativeFullLooRuntimePlan or type(provider) is not GrokTrainProvider:
        raise ContractError('native C4 requires its versioned plan and closed Grok provider')
    plan.__post_init__()
    if provider_configuration(provider).data() != plan.native_data()['provider_configuration']:
        raise ContractError('live native provider differs from frozen C4 provider configuration')
    allocation = plan.composition.data()['allocation']; root = _path(run_root, exists=False)
    if root.exists(): raise ContractError('native C4 run root is already used')
    root.mkdir(parents=True); _exclusive(root / 'native-plan.json', plan.record)
    journal = _Journal(root / 'native-controller.jsonl'); session = PhaseProviderSession(provider, root / 'provider-scopes.json')
    armrows = [r for r in plan.composition.data()['cells'] if r['status'] == 'executable']
    buildrows = [{'recipe': r, 'status': 'not_started'} for r in recipes(plan)]
    rows = [{'arm_id': r['id'], 'task_digest': digest, 'status': 'not_started', 'scorer_calls': 0}
            for r in armrows for digest in plan.composition.data()['train_task_digests']]
    structural = [{'arm_id': r['id'], 'task_digest': digest, 'status': r['status'], 'reason': r['reason']}
                  for r in plan.composition.data()['cells'] if r['status'] != 'executable'
                  for digest in plan.composition.data()['train_task_digests']]
    def accounting():
        usage=session.usage().data()
        if usage['schema']=='public-train-provider-usage-v1':
            return {'schema':'train-phase-call-accounting-v2','provider_calls':usage['main_opportunities'],
                'known_reported_tokens':usage['known_reported_tokens'],'known_usage_scope':usage['known_usage_scope'],
                'unknown_main_opportunities':usage['unknown_main_opportunities'],
                'unsuccessful_opportunities':0,'possible_initial_title_opportunities':usage['possible_initial_title_opportunities'],
                'title_tokens':None,'all_opportunity_tokens':None,'settled_additional_charge_usd':None}
        return {'schema':'train-phase-terminal-accounting-v2','provider_calls_lower_bound':usage['observed_main_opportunities_lower_bound'],
            'known_reported_tokens_lower_bound':usage['known_reported_tokens_lower_bound'],'known_usage_scope':'native_main',
            'unknown_unobserved_opportunities':True,'title_tokens':None,'all_opportunity_tokens':None,
            'settled_additional_charge_usd':None,'score_eligible':False}
    def persist(captured_accounting=None):
        _exclusive_or_replace(root / 'attempts.json', {'builds': buildrows, 'targets': rows, 'structural': structural,
            'native_accounting': accounting() if captured_accounting is None else captured_accounting})
    journal.append('phase_lock', {'plan_digest': plan.record.content_hash, 'allocation': allocation}); persist()
    source = CombinationTrainSource(plan.legacy.data(), custody=None, prospective_exporter=prospective_exporter,
        snapshot=_path(snapshot_root, exists=False), exported=_path(export_root, exists=False))
    builds=[]; results=[]; scores=[]; barrier=panel=None; poison=False; service=None
    try:
        packets = tuple(source.export()); plan.check_packets(packets)
        packets = tuple(next(p for p in packets if p.task.content_hash == d) for d in plan.composition.data()['train_task_digests'])
        broker = DockerExecutionBroker([root, Path(export_root), plan.history_inputs[0][1].parent])
        check_history(plan.history, plan.material(plan.history.task.content_hash).state(), broker, dict(plan.history_inputs))
    except Exception as exc:
        for row in [*buildrows, *rows]: row.update(status='blocked', reason='source_preflight: ' + str(exc))
        persist(); raise
    for index, row in enumerate(buildrows):
        recipe = row['recipe']; scope_id = _scope('history_build', recipe['id'], plan.history.task.content_hash)
        if poison:
            row.update(status='blocked', reason='prior_native_unknown_or_failure'); persist(); continue
        journal.append('build_reserved', {'recipe': recipe, 'scope_id': scope_id}); persist()
        cell = PanelCell(OBLIGATION, plan.history.task.identity, 'r1', 'combination', recipe['id'], runtime_arm(plan.composition, recipe, 'history_build'),
            plan.history.task.content_hash, plan.record.content_hash, plan.parent.digest, ScorerConfig(FrozenRecord.from_dict(plan.legacy.data()['scorer'])).digest)
        try:
            with session.scope(scope_id) as scoped:
                result = run_stage(plan=plan, recipe=recipe, stage='history_build', cell=cell, task=plan.history.task, package=plan.parent,
                    material=plan.material(plan.history.task.content_hash), phase_material=plan.phase_material(plan.history.task.content_hash),
                    source_verifier=source_verifier, corpus_verifier=corpus_verifier, provider=retrieval_provider, broker=broker,
                    inputs=dict(plan.history_inputs), model=scoped, audit_verifier=audit_verifier, root=root / 'builds' / str(index))
        except ContractError as exc:
            row.update(status='failed',reason='provider_terminal: '+str(exc)); poison=True
            journal.append('build_terminal_abort',{'scope_id':scope_id,'error_type':type(exc).__name__}); persist(); break
        builds.append(result); row.update(status=result.record.data()['status'], reason=result.record.data()['reason'])
        poison = poison or result.record.data()['status'] != 'succeeded' or session.terminal()
        journal.append('build_completed', {'digest': result.record.content_hash, 'status': row['status'], 'scope_id': scope_id}); persist()
    build_ledger = session.finish(root / 'build-provider-ledger.json'); journal.append('build_provider_finished', {'digest': build_ledger.record.content_hash,'eligible':type(build_ledger) is PhaseProviderLedger})
    if type(build_ledger) is PhaseProviderLedger and not poison and len(builds) == len(buildrows) and all(r.record.data()['status'] == 'succeeded' for r in builds):
        packages = {r['id']: CandidatePackage(_read_record(next(x.root for x in builds if candidate_build_key(x.record.data()['recipe']) == candidate_build_key(r)) / 'candidate.json')).digest for r in armrows}
        record = FrozenRecord.from_dict({'schema': NATIVE_LEDGER_SCHEMA, 'plan_digest': plan.record.content_hash,
            'build_receipts': [r.record.content_hash for r in builds], 'provider_ledger_digest': build_ledger.record.content_hash,
            'candidate_selections': packages})
        _exclusive(root / 'native-candidate-barrier.json', record); barrier = NativeFullLooBarrier(root, record, plan, tuple(builds), build_ledger,
            source_verifier, corpus_verifier, broker, packets)
        try:
            barrier.verify(); panel, _ = compile_panel(barrier); journal.append('candidate_barrier', {'digest': record.content_hash})
        except Exception as exc:
            poison=True; _exclusive(root / 'barrier-failure.json', FrozenRecord.from_dict({'error': str(exc)}))
    else: poison=True
    for row in rows:
        recipe = next(r for r in armrows if r['id'] == row['arm_id']); scope_id = _scope('target', recipe['id'], row['task_digest'])
        key={'arm_id':row['arm_id'], 'task_digest':row['task_digest']}
        if poison or panel is None:
            row.update(status='blocked', reason='candidate_barrier_or_native_failure'); journal.append('target_blocked', {**key, 'scope_id':scope_id}); results.append(None); persist(); continue
        packet=next(p for p in packets if p.task.content_hash == row['task_digest']); cell=next(c for c in panel.cells if c.arm_id == row['arm_id'] and c.task_digest == row['task_digest'])
        journal.append('target_reserved', {**key, 'scope_id': scope_id}); persist()
        try:
            with session.scope(scope_id) as scoped:
                result=run_stage(plan=plan, recipe=recipe, stage='target', cell=cell, task=packet.task, package=barrier.package(recipe),
                    material=plan.material(packet.task.content_hash), phase_material=plan.phase_material(packet.task.content_hash), source_verifier=source_verifier,
                    corpus_verifier=corpus_verifier, provider=retrieval_provider, broker=broker, inputs={'public_csv':packet.csv_path}, model=scoped,
                    audit_verifier=audit_verifier, root=root/'targets'/FrozenRecord.from_dict(cell.data()).content_hash)
        except ContractError as exc:
            row.update(status='failed',reason='provider_terminal: '+str(exc)); poison=True
            journal.append('target_terminal_abort',{**key,'scope_id':scope_id,'error_type':type(exc).__name__}); results.append(None); persist(); continue
        results.append(result); row.update(status=result.record.data()['status'], reason=result.record.data()['reason'])
        poison=poison or result.record.data()['status'] != 'succeeded' or session.terminal()
        journal.append('target_completed', {**key, 'digest':result.record.content_hash, 'status':row['status'], 'scope_id':scope_id}); persist()
    target_ledger=session.finish(root/'target-provider-ledger.json'); journal.append('target_provider_finished', {'digest':target_ledger.record.content_hash,'eligible':type(target_ledger) is PhaseProviderLedger}); persist()
    process_state={'startup_attempts':0,'startup_status':'not_started','close_attempts':0,'closed':None,'error':None}; ready=False
    try:
        if panel is not None and not poison and type(target_ledger) is PhaseProviderLedger:
            process_state.update(startup_attempts=1,startup_status='reserved'); journal.append('scorer_startup_reserved', {'panel_digest':panel.digest}); persist()
            try:
                service=scorer_factory(panel)
                if type(service) is not CombinationScorerProcessClient or service.full_loo is not True or service.panel != panel:
                    raise ContractError('exact closed C4 independent process scorer required')
                service.assert_configuration(config=ScorerConfig(FrozenRecord.from_dict(plan.legacy.data()['scorer'])), task_handle_bindings=plan.legacy.data()['scorer_handle_bindings'],
                    execution_authority_keys={execution_authority.authority_id:execution_authority.key}, scorer_authority_keys=scorer_authority_keys)
                process_state['startup_status']='ready'; ready=True
            except Exception as exc:
                process_state.update(startup_status='failed', error=type(exc).__name__+': '+str(exc))
                for row in rows:
                    if row['status']=='succeeded': row.update(execution_status='succeeded',status='scoring_blocked',reason='scorer_startup: '+process_state['error'])
            journal.append('scorer_startup_completed', {'status':process_state['startup_status'],'error':process_state['error']}); persist()
        scorer_provider_terminal=False
        for index,(row,result) in enumerate(zip(rows,results,strict=True)):
            if result is None or row['status']!='succeeded' or not ready: continue
            key={'arm_id':row['arm_id'],'task_digest':row['task_digest']}
            try:
                verify_native_full_loo_cell(result, barrier=barrier, panel=panel, ledger=target_ledger)
            except ContractError as exc:
                scorer_provider_terminal=True
                row.update(status='scoring_ineligible',reason='scorer_provider_replay: '+type(exc).__name__)
                for later in rows[index+1:]:
                    if later['status']=='succeeded': later.update(status='blocked',reason='scorer_provider_terminal: '+type(exc).__name__)
                journal.append('scorer_provider_terminal',{**key,'error_type':type(exc).__name__}); persist()
                break
            try:
                scoreinput=execution_authority.issue(_score_input_payload(panel,result).data()); row['scorer_calls']=1
                journal.append('scorer_reserved',{**key,'input_digest':scoreinput.content_hash})
                score=service.score_combination(panel=panel,cell=result.cell,score_input=scoreinput)
                verify_combination_adapted_receipt(score,authority_keys=scorer_authority_keys,config=service.config,panel=panel,cell=result.cell,
                    score_input=scoreinput,execution_authority_keys={execution_authority.authority_id:execution_authority.key})
                scores.append(score); row.update(status='scored',score=score.receipt.data())
            except Exception as exc: row.update(status='failed',reason=type(exc).__name__+': '+str(exc))
            if row['scorer_calls']: journal.append('scorer_completed',{**key,'status':row['status']})
            persist()
    finally:
        if service is not None:
            process_state['close_attempts']=1
            try: service.close(); process_state['closed']=service.process.poll() is not None
            except Exception as exc: process_state.update(closed=False,close_error=type(exc).__name__+': '+str(exc))
            journal.append('scorer_closed',{'closed':process_state['closed']}); persist()
    # Capture every report input that can inspect originals before the final
    # fresh provenance gate.  No receipt construction below may call usage()
    # or re-read provider evidence after that gate.
    stages=[*builds,*[r for r in results if r is not None]]; sourcecalls=[]; corpuscalls=[]; auxiliary=solver=retrieval=builders=0
    for result in stages:
        for filename,destination in [('source/source.json',sourcecalls),('corpus/source.json',corpuscalls)]:
            if (result.root/filename).exists(): destination.extend(json.loads((result.root/filename).read_bytes())['calls'])
        events=[json.loads(line) for line in (result.root/'runtime/trace.jsonl').read_bytes().splitlines()] if (result.root/'runtime/trace.jsonl').exists() else []
        solver += sum(e['stage']=='execution_request' for e in events); retrieval += sum(e['stage']=='q8_retrieval_request' for e in events); builders += sum(e['stage']=='c4_builder_request' for e in events)
        if (result.root/'phase/events.jsonl').exists(): auxiliary += sum(json.loads(line)['kind']=='start' for line in (result.root/'phase/events.jsonl').read_bytes().splitlines())
    current_accounting=accounting()
    contrasts=[]
    for recipe in armrows[1:]:
        pairs=[]
        for digest in plan.composition.data()['train_task_digests']:
            full=next(r for r in rows if r['arm_id']=='full' and r['task_digest']==digest); other=next(r for r in rows if r['arm_id']==recipe['id'] and r['task_digest']==digest)
            pairs.append({'task_digest':digest,'difference':full['score']['body']['metric']['value']-other['score']['body']['metric']['value'] if full['status']==other['status']=='scored' else None})
        contrasts.append({'contrast':'F-versus-'+recipe['id'],'changed_modules':[m for m,v in recipe['arm_bits'].items() if not v],
            'estimand':recipe.get('estimand',recipe['comparison']),'matched_model_budget':recipe['procedure']!='baseline_b0',
            'paired_rows':pairs,'confidence_interval':None,'unrestricted_interactions':'not_identified','provenance_status':'current'})
    final_provider_eligible=type(target_ledger) is PhaseProviderLedger
    if final_provider_eligible:
        try: target_ledger.verify()
        except ContractError as exc:
            final_provider_eligible=False
            for row in rows:
                if row['status']=='scored': row.update(execution_status='scored',status='scoring_ineligible',reason='final_provider_replay: '+type(exc).__name__)
            journal.append('final_provider_replay_failed',{'error_type':type(exc).__name__}); persist(current_accounting)
    if scorer_provider_terminal:
        final_provider_eligible=False
    if not final_provider_eligible:
        for row in rows:
            if row['status']=='scored':
                row.update(execution_status='scored',status='scoring_ineligible',reason='scorer_provider_terminal' if scorer_provider_terminal else 'final_provider_replay')
        contrasts=[{**contrast,'provenance_status':'historical_ineligible'} for contrast in contrasts]
        persist(current_accounting)
    actual={'model_calls':current_accounting.get('provider_calls'),'builder_executions':builders,'independent_source_qualification_calls':len(sourcecalls),
        'corpus_qualification_calls':len(corpuscalls),'retrieval_requests':retrieval,'auxiliary_docker_attempts':auxiliary,
        'solver_docker_attempts':solver,'docker_attempts':auxiliary+solver,'scorer_calls':sum(r['scorer_calls'] for r in rows)}
    receipt=FrozenRecord.from_dict({'schema':'c4-native-provider-run-receipt-v3','plan_digest':plan.record.content_hash,'allocation':allocation,'actual':actual,
        'unused':{k:(None if v is None else allocation[k]-v) for k,v in actual.items()},'builds':buildrows,'targets':rows,'structural':structural,
        'native_accounting':current_accounting,'contrasts':contrasts,'target_provider_ledger_digest':target_ledger.record.content_hash,
        'target_provider_ledger_kind':type(target_ledger).__name__,'final_provider_eligible':final_provider_eligible,'historical_scorer_calls':len(scores),
        'scorer_process':process_state,'p0':{'required':True,'scientific_execution_qualified':False,'promotion_allowed':False},
        'candidate_activation':'none_offline_experiment','validation_opened':False,'scientific_effectiveness_proven':False,
        'status':'complete_train_engineering' if len(scores)==22 and process_state['closed'] is True and final_provider_eligible else 'inconclusive'})
    _exclusive(root/'native-controller-receipt.json',receipt)
    return FullLooRun(root,barrier,panel,tuple(builds),tuple(results),target_ledger,tuple(scores),receipt)


def _exclusive_or_replace(path, value):
    path=Path(path); raw=FrozenRecord.from_dict(value).encoded.encode('utf-8'); temporary=path.with_suffix('.tmp')
    temporary.write_bytes(raw); temporary.replace(path)
