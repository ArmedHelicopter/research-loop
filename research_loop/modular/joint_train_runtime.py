"""C5 common-procedure runtime admission and original stage execution.

The reused inner pipeline does not complete C4 or any original Q experiment.
This module does not issue scoring authority, selection or validation receipts.
"""
from dataclasses import dataclass
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.full_loo_driver import FullLooResult, run_stage, verify_stage
from research_loop.modular.full_loo_modules import model_schemas, slots
from research_loop.modular.full_loo_panel import runtime_arm
from research_loop.modular.joint_train_protocol import FrozenJointTrainProtocol, OBLIGATION, _binding
from research_loop.modular.joint_train_panel import JointTrainPanel, history_build_id, target_arm
from research_loop.modular.joint_deployment import JointComponentVersion, _hash
from research_loop.modular.metaprogram_training import FrozenTrainHistory, _builder, _sha, _exclusive, _read_record
from research_loop.modular.modules.improvement import CandidatePackage, FrozenBuilderVersion, TrainingManifest
from research_loop.modular.state_retrieval_combination_driver import FrozenStateRetrievalMaterial
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial, check_inputs
from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
from research_loop.modular.lineage_combination_material import DualMaterialVerifier, check_material_inputs
from research_loop.modular.state_improvement_build import check_history
from research_loop.modular.combination_train_source import packet_index
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.phase_provider import PhaseProviderSession, PhaseProviderLedger, provider_configuration, validate_configuration
from research_loop.modular.phase_provider import PROVIDERS
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
ROOT = Path(__file__).resolve().parents[2]
CONSUMERS = {
    'M1': 'research_loop/modular/admission_combination.py',
    'M2': 'research_loop/modular/modules/evidence.py',
    'M3': 'research_loop/modular/modules/context.py',
    'M4': 'research_loop/modular/modules/predictions.py',
    'M5': 'research_loop/modular/modules/review.py',
    'M6': 'research_loop/modular/mechanism_improvement_modules.py',
    'M7': 'research_loop/modular/exploration_scheduler_combination.py',
    'M8': 'research_loop/modular/modules/scheduling.py',
    'M9': 'research_loop/modular/modules/improvement.py',
}


def runtime_sources():
    """Pin the implementation tree, including all transitive local consumers."""
    return {p.relative_to(ROOT).as_posix(): _sha(p.read_bytes())
            for folder in ('research_loop', 'evaluation') for p in sorted((ROOT / folder).rglob('*.py'))}


def component_templates(*, history, parent, fixed_builder, history_material):
    """Only this fixed, actually imported pipeline is admitted in runtime v1."""
    if (type(history) is not FrozenTrainHistory or type(parent) is not CandidatePackage
            or type(fixed_builder) is not FrozenBuilderVersion or type(history_material) is not FrozenStateRetrievalMaterial):
        raise ContractError('typed actual history and consumer inputs required')
    state = R({'history_binding_digest': history.binding.content_hash, 'parent_digest': parent.digest,
               'fixed_builder_digest': fixed_builder.digest, 'history_material_digest': history_material.record.content_hash})
    manifest = TrainingManifest.freeze([history.task.identity])
    return {name: JointComponentVersion.capture(name, source_root=ROOT,
        source_files=[path, 'research_loop/modular/full_loo_modules.py', 'research_loop/modular/full_loo_driver.py'],
        config=R({'schema': 'c5-fixed-stage-consumer-v1', 'module_id': name, 'consumer': path,
                  'pipeline': 'full_loo_modules-v1'}), state=state, training_manifest=manifest)
        for name, path in CONSUMERS.items()}


@dataclass(frozen=True)
class FrozenJointTrainRuntimePlan:
    record: FrozenRecord
    protocol: FrozenJointTrainProtocol
    history: FrozenTrainHistory
    history_inputs: tuple
    packets: tuple

    def data(self): return self.record.data()
    @property
    def composition(self): return self.protocol.record  # Existing stage arm helper reads only baseline_digest.
    @property
    def parent(self): return CandidatePackage(R(self.data()['parent']))
    @property
    def fixed_builder(self): return FrozenBuilderVersion(R(self.data()['fixed_builder']))
    def material(self, task): return FrozenStateRetrievalMaterial(R(self.data()['materials'][task]))
    def phase_material(self, task): return FrozenExplorationSchedulerMaterial(R(self.data()['phase_materials'][task]))
    def objective(self, stage):
        if stage not in ('history_build', 'target'): raise ContractError('unknown common runtime stage')
        return R(self.history.binding.data()['lock']['objective'] if stage == 'history_build' else self.data()['objective'])
    @property
    def recipes(self): return tuple(row['recipe'] for row in self.protocol.record.data()['catalogue']['recipes'])
    @property
    def builds(self):
        unique = {}
        for recipe in self.recipes: unique.setdefault(history_build_id(self.protocol, recipe), recipe)
        return tuple(unique.values())

    def __post_init__(self):
        if (type(self) is not FrozenJointTrainRuntimePlan or type(self.record) is not FrozenRecord
                or type(self.protocol) is not FrozenJointTrainProtocol or type(self.history) is not FrozenTrainHistory
                or type(self.packets) is not tuple or type(self.history_inputs) is not tuple):
            raise ContractError('exact common runtime plan, protocol and originals required')
        b = self.data(); p = self.protocol.record.data()
        required = {'schema', 'protocol_digest', 'stage', 'domain', 'export_mode', 'item_ids', 'task_bindings',
                    'history_binding', 'parent', 'fixed_builder', 'materials', 'phase_materials',
                    'source_verifier_binding', 'corpus_verifier_binding', 'scorer_handle_bindings',
                    'objective', 'image', 'timeout_seconds'}
        if (set(b) != required or b['schema'] != 'c5-common-train-runtime-plan-v1'
                or b['protocol_digest'] != self.protocol.digest or b['domain'] != 'train'
                or b['export_mode'] != 'primary_prospective' or type(b['stage']) is not str or not b['stage'].strip()
                or b['history_binding'] != self.history.binding.data()):
            raise ContractError('common runtime scope or original protocol drift')
        self.protocol.__post_init__(); self.history.verify(); _builder(self.fixed_builder)
        if (p['history_binding_digest'] != self.history.binding.content_hash or p['builder_digest'] != self.fixed_builder.digest
                or set(TrainingManifest(R(self.parent.record.data()['training_manifest'])).identities()) != {self.history.task.identity}
                or len(self.history_inputs) != 1 or self.history_inputs[0][0] != 'public_csv'):
            raise ContractError('common fixed history, parent or builder drift')
        indexed = packet_index(b, self.packets)
        bindings = {token: _binding(packet.task, packet.csv_path) for token, packet in indexed.items()}
        if bindings != b['task_bindings'] or set(map(lambda r: R(r).content_hash, bindings.values())) != {R(r).content_hash for r in p['targets']}:
            raise ContractError('common original target inventory differs from protocol')
        tasks = {packet.task.content_hash: packet.task for packet in self.packets}
        tasks[self.history.task.content_hash] = self.history.task
        csv = {packet.task.content_hash: packet.csv_path for packet in self.packets}
        csv[self.history.task.content_hash] = Path(self.history_inputs[0][1])
        self.protocol.verify_original_inputs(tasks=tasks, public_csv=csv,
            component_roots={name: ROOT for name in CONSUMERS}, runtime_root=ROOT)
        if p['runtime_sources'] != runtime_sources():
            raise ContractError('common runtime must pin the complete actual implementation tree')
        if set(b['materials']) != set(tasks) or set(b['phase_materials']) != set(tasks):
            raise ContractError('common full history and target material inventory required')
        for digest, task in tasks.items():
            m = self.material(digest); phase = self.phase_material(digest); state = m.state()
            if (type(state) is not FrozenAdmissionMaterial or state.data()['identity'] != task.identity.data()
                    or state.data()['task_digest'] != digest or state.data()['context_budget_bytes'] != p['context_bytes']
                    or any(phase.data()[key] != state.data()[key] for key in ('identity', 'task_digest', 'public_artifacts', 'context_budget_bytes'))):
                raise ContractError('common material subject or context allocation drift')
            broker = DockerExecutionBroker([Path(csv[digest]).parent])
            check_material_inputs(state, task, broker, {'public_csv': csv[digest]})
            check_inputs(phase, task, broker, {'public_csv': csv[digest]})
            ExecutionRequest(task.identity, b['image'], Path('planned.py'), {'public_csv': Path('planned.csv')}, b['timeout_seconds'])
        expected_templates = component_templates(history=self.history, parent=self.parent, fixed_builder=self.fixed_builder,
                                                 history_material=self.material(self.history.task.content_hash))
        if p['component_templates'] != {k: v.record.data() for k, v in expected_templates.items()}:
            raise ContractError('component templates do not bind the actual fixed consumers and history inputs')
        validate_configuration(R(p['provider_config']), schemas=model_schemas(), main_opportunities=p['allocation']['model_calls'])
        config = p['provider_config']
        if config['provider_kind'] == 'grok-acp-public-train-v1':
            native = config['native_config']
            if (native['slot_output_caps'] != {s: 8192 if s == 'analysis_program' else 2048 for s in model_schemas()}
                    or native['slot_input_byte_caps'] != {s: 262144 for s in model_schemas()}
                    or native['observed_main_token_cap'] != 131072):
                raise ContractError('common native slot resource policy differs')
        scorer = ScorerConfig(R(p['scorer']))
        expected_handles = {R(packet.task.identity.data()).content_hash for packet in self.packets}
        if (scorer.record.data()['rubric_digest'] != FrozenBenchmarkRubricEndpoint.rubric_digest()
                or set(b['scorer_handle_bindings']) != expected_handles):
            raise ContractError('common scorer or original handle inventory differs')
        for value in b['scorer_handle_bindings'].values(): _hash(value, 'scorer handle')
        if type(b['objective']) is not dict or not b['objective']: raise ContractError('target objective required')

    def verify_dependencies(self, *, provider, source_verifier, corpus_verifier, scorer_handle_bindings):
        self.__post_init__()
        if type(provider) not in PROVIDERS or provider_configuration(provider).data() != self.protocol.record.data()['provider_config']:
            raise ContractError('actual common provider differs')
        if type(source_verifier) is not AdmissionMaterialVerifier or type(corpus_verifier) is not DualMaterialVerifier:
            raise ContractError('exact common qualification authorities required')
        if (source_verifier.binding().data() != self.data()['source_verifier_binding']
                or corpus_verifier.binding().data() != self.data()['corpus_verifier_binding']
                or dict(scorer_handle_bindings) != self.data()['scorer_handle_bindings']):
            raise ContractError('common qualification or scorer handle binding differs')


@dataclass(frozen=True)
class JointTrainStage:
    record: FrozenRecord
    inner: FullLooResult
    ledger: PhaseProviderLedger
    barrier: object = None


def _stage_record(plan, inner, ledger, barrier, *, status):
    """Derive every outer binding from originals, never from a supplied outer body."""
    data=inner.record.data();stage=data['stage'];recipe=data['recipe']
    if recipe not in plan.recipes or stage not in ('history_build','target'):
        raise ContractError('inner stage is outside the frozen common protocol')
    trial=(history_build_id(plan.protocol,recipe) if stage=='history_build' else
           plan.protocol.trial_binding(recipe['id'],inner.cell.task_digest).content_hash)
    return R({'schema':'c5-common-stage-original-v1','plan_digest':plan.record.content_hash,'protocol_digest':plan.protocol.digest,
        'trial_id':trial,'build_id':history_build_id(plan.protocol,recipe),'scope_id':'c5-stage-v1:'+stage+':'+trial,
        'stage':stage,'recipe_id':recipe['id'],'status':status,'inner_pipeline_receipt_digest':inner.record.content_hash,
        'provider_seal_digest':ledger.record.content_hash,
        'component_digests':{k:JointComponentVersion(R(v)).digest for k,v in plan.protocol.record.data()['component_templates'].items()},
        'target_binding_mode':'common_panel' if barrier is not None else 'stage_checkpoint',
        'history_barrier_digest':None if barrier is None else barrier.record.content_hash,
        'score_eligible':False,'original_experiments_completed':False})


class JointTrainStageExecutor:
    """Bounded stage kernel; partial execution never grants scoring eligibility."""
    def __init__(self, plan, *, root, provider, source_verifier, corpus_verifier, retrieval_provider,
                 audit_verifier, scorer_handle_bindings):
        if type(plan) is not FrozenJointTrainRuntimePlan: raise ContractError('exact common plan required')
        plan.verify_dependencies(provider=provider, source_verifier=source_verifier, corpus_verifier=corpus_verifier,
                                 scorer_handle_bindings=scorer_handle_bindings)
        self.plan=plan; self.root=Path(root); self.root.mkdir(parents=True, exist_ok=False)
        _exclusive(self.root/'plan.json',plan.record)
        self.session=PhaseProviderSession(provider,self.root/'provider-scopes.json')
        self.source=source_verifier; self.corpus=corpus_verifier; self.retrieval=retrieval_provider; self.audit=audit_verifier
        self.handles=dict(scorer_handle_bindings); self.stages=[]; self.poisoned=False; self.attempts={}
        self.broker=DockerExecutionBroker([self.root, *{p.csv_path.parent for p in plan.packets}, Path(plan.history_inputs[0][1]).parent])
        self._persist()

    def _persist(self):
        from research_loop.modular.metaprogram_training import _atomic
        completed={**self.attempts, **{(s.record.data()['stage'],s.record.data()['trial_id']):s.record.data() for s in self.stages}}
        planned=[('history_build',history_build_id(self.plan.protocol,r)) for r in self.plan.builds]
        planned += [('target',self.plan.protocol.trial_binding(r['id'],p.task.content_hash).content_hash)
                    for r in self.plan.recipes for p in self.plan.packets]
        rows=[{'stage':stage,'trial_id':key,'status':completed.get((stage,key),{}).get('status','blocked' if self.poisoned else 'not_executed')}
              for stage,key in planned]
        _atomic(self.root/'checkpoint.json',R({'schema':'c5-common-stage-checkpoint-v1','plan_digest':self.plan.record.content_hash,
            'rows':rows,'allocation':self.plan.protocol.record.data()['allocation'],'provider_usage':self.session.usage().data(),
            'complete_grid_executed':False,'score_eligible':False,'original_experiments_completed':False}).data())

    def execute(self, *, recipe_id, stage, target_digest=None, build=None, barrier=None):
        if self.poisoned or self.session.terminal(): raise ContractError('common stage allocation is terminal')
        plan=self.plan; trial=None
        try:
            plan.verify_dependencies(provider=self.session.provider,source_verifier=self.source,corpus_verifier=self.corpus,
                                     scorer_handle_bindings=self.handles)
            if _read_record(self.root/'plan.json') != plan.record: raise ContractError('original runtime plan drift')
            for previous in self.stages:
                if previous.record.data()['status']=='succeeded': self.verify(previous)
            recipe=next((r for r in plan.recipes if r['id']==recipe_id),None)
            if recipe is None or stage not in ('history_build','target'): raise ContractError('unregistered common stage')
            if stage=='history_build':
                if target_digest is not None or build is not None or barrier is not None: raise ContractError('history stage cannot receive target evidence')
                task=plan.history.task; package=plan.parent; inputs=dict(plan.history_inputs)
                trial=history_build_id(plan.protocol,recipe)
            else:
                packet=next((p for p in plan.packets if p.task.content_hash==target_digest),None)
                if packet is None or type(build) is not JointTrainStage or build not in self.stages:
                    raise ContractError('target requires original bound history stage')
                self.verify(build)
                if build.record.data()['stage']!='history_build' or build.record.data()['build_id']!=history_build_id(plan.protocol,recipe):
                    raise ContractError('target package belongs to a different history procedure')
                task=packet.task; package=CandidatePackage(_read_record(build.inner.root/'candidate.json')); inputs={'public_csv':packet.csv_path}
                trial=plan.protocol.trial_binding(recipe_id,target_digest).content_hash
            scope='c5-stage-v1:'+stage+':'+trial
            if any(s.record.data()['scope_id']==scope for s in self.stages): raise ContractError('common stage opportunity already used')
            scenario=R({'schema':'c5-stage-scenario-v1','plan_digest':plan.record.content_hash,'trial_id':trial})
            cell=PanelCell(OBLIGATION,task.identity,'r1','combination',recipe_id,runtime_arm(plan.composition,recipe,stage),
                task.content_hash,scenario.content_hash,package.digest,ScorerConfig(R(plan.protocol.record.data()['scorer'])).digest)
            if barrier is not None:
                if type(barrier) is not JointTrainBarrier or barrier.executor is not self:
                    raise ContractError('formal target requires this exact executor history barrier')
                panel,_=compile_panel(barrier)
                cell=next(c for c in panel.cells if c.arm_id==recipe_id and c.task_digest==task.content_hash)
                if cell.package_digest!=package.digest:raise ContractError('formal target package differs from its barrier')
            if stage=='history_build':check_history(plan.history,plan.material(task.content_hash).state(),self.broker,inputs)
            self.attempts[(stage,trial)]={'status':'reserved'};self._persist()
            with self.session.scope(scope) as scoped:
                def model(request):
                    plan.verify_dependencies(provider=self.session.provider,source_verifier=self.source,corpus_verifier=self.corpus,
                                             scorer_handle_bindings=self.handles)
                    if _read_record(self.root/'plan.json')!=plan.record:raise ContractError('runtime plan changed before dispatch')
                    return scoped(request)
                inner=run_stage(plan=plan,recipe=recipe,stage=stage,cell=cell,task=task,package=package,
                    material=plan.material(task.content_hash),phase_material=plan.phase_material(task.content_hash),
                    source_verifier=self.source,corpus_verifier=self.corpus,provider=self.retrieval,broker=self.broker,
                    inputs=inputs,model=model,audit_verifier=self.audit,root=self.root/'stages'/trial)
            ledger=self.session.finish(self.root/(trial+'-provider.json'))
            status=inner.record.data()['status']
            try:
                plan.verify_dependencies(provider=self.session.provider,source_verifier=self.source,corpus_verifier=self.corpus,
                                         scorer_handle_bindings=self.handles)
            except ContractError:
                status='failed'
            if type(ledger) is not PhaseProviderLedger or self.session.terminal(): status='failed'
            record=_stage_record(plan,inner,ledger,barrier,status=status)
            _exclusive(self.root/(trial+'-stage.json'),record)
            # The outer record is outside the inner pipeline's original file inventory.
            self.stages.append(JointTrainStage(record,inner,ledger,barrier))
            if status!='succeeded': self.poisoned=True
            return self.stages[-1]
        except Exception:
            if trial is not None:self.attempts[(stage,trial)]={'status':'failed'}
            self.poisoned=True; raise
        finally:
            self._persist()

    def verify(self, result):
        if type(result) is not JointTrainStage or result not in self.stages or type(result.ledger) is not PhaseProviderLedger:
            raise ContractError('original common stage and eligible provider seal required')
        if result.barrier is not None and (type(result.barrier) is not JointTrainBarrier or result.barrier.executor is not self):
            raise ContractError('common stage barrier origin differs')
        expected=_stage_record(self.plan,result.inner,result.ledger,result.barrier,status='succeeded')
        if result.record!=expected or result.inner.record.data()['status']!='succeeded':
            raise ContractError('common outer receipt differs from complete original cross-binding')
        self.plan.verify_dependencies(provider=self.session.provider,source_verifier=self.source,corpus_verifier=self.corpus,
                                      scorer_handle_bindings=self.handles)
        b=expected.data(); recipe=result.inner.record.data()['recipe']
        if _read_record(self.root/(b['trial_id']+'-stage.json')) != result.record or b['status']!='succeeded':
            raise ContractError('original common stage unavailable')
        calls=result.ledger.calls_for_scope(b['scope_id'])
        if tuple(c.data()['slot'] for c in calls)!=slots(recipe,b['stage']): raise ContractError('common provider slot order differs')
        task=self.plan.history.task if b['stage']=='history_build' else next(p.task for p in self.plan.packets if p.task.content_hash==result.inner.cell.task_digest)
        if b['stage']=='history_build': package=self.plan.parent; inputs=dict(self.plan.history_inputs)
        else:
            build=next(s for s in self.stages if s.record.data()['stage']=='history_build' and s.record.data()['build_id']==b['build_id'])
            self.verify(build); package=CandidatePackage(_read_record(build.inner.root/'candidate.json'))
            inputs={'public_csv':next(p.csv_path for p in self.plan.packets if p.task==task)}
        if result.barrier is not None:
            if type(result.barrier) is not JointTrainBarrier or result.barrier.executor is not self or b['stage']!='target':
                raise ContractError('common target barrier origin differs')
            panel,_=compile_panel(result.barrier)
            if result.inner.cell not in panel.cells:raise ContractError('formal target did not execute its exact common panel cell')
        else:
            scenario=R({'schema':'c5-stage-scenario-v1','plan_digest':self.plan.record.content_hash,'trial_id':b['trial_id']})
            if result.inner.cell.scenario_digest!=scenario.content_hash:
                raise ContractError('checkpoint stage scenario drift')
        return verify_stage(result.inner,plan=self.plan,recipe=recipe,stage=b['stage'],task=task,package=package,
            material=self.plan.material(task.content_hash),phase_material=self.plan.phase_material(task.content_hash),
            source_verifier=self.source,corpus_verifier=self.corpus,broker=self.broker,inputs=inputs,ledger=result.ledger,
            provider_scope_id=b['scope_id'],require_provider_eligible=True)


@dataclass(frozen=True)
class JointTrainBarrier:
    record: FrozenRecord
    executor: JointTrainStageExecutor
    builds: tuple

    @classmethod
    def seal(cls, executor):
        if type(executor) is not JointTrainStageExecutor or executor.poisoned or executor.session.terminal():
            raise ContractError('healthy original common stage executor required')
        plan=executor.plan
        if (len(executor.stages)!=len(plan.builds) or any(s.record.data()['stage']!='history_build' for s in executor.stages)
                or {s.record.data()['build_id'] for s in executor.stages}!={history_build_id(plan.protocol,r) for r in plan.builds}):
            raise ContractError('complete canonical history grid required before common target panel')
        for stage in executor.stages: executor.verify(stage)
        record=R({'schema':'c5-common-history-barrier-v1','runtime_plan_digest':plan.record.content_hash,
            'protocol_digest':plan.protocol.digest,'build_receipts':{s.record.data()['build_id']:s.record.content_hash for s in executor.stages},
            'component_digests':{k:JointComponentVersion(R(v)).digest for k,v in plan.protocol.record.data()['component_templates'].items()},
            'original_experiments_completed':False,'score_eligible':False})
        _exclusive(executor.root/'common-history-barrier.json',record)
        return cls(record,executor,tuple(executor.stages))

    def verify(self):
        if type(self) is not JointTrainBarrier or type(self.executor) is not JointTrainStageExecutor:
            raise ContractError('exact original common history barrier required')
        plan=self.executor.plan
        if (self.executor.poisoned or self.executor.session.terminal()
                or _read_record(self.executor.root/'common-history-barrier.json')!=self.record
                or len(self.builds)!=len(plan.builds)
                or tuple(self.executor.stages[:len(self.builds)])!=self.builds
                or any(s.record.data()['stage']!='history_build' for s in self.builds)
                or self.record.data()['build_receipts']!={s.record.data()['build_id']:s.record.content_hash for s in self.builds}
                or set(self.record.data()['build_receipts'])!={history_build_id(plan.protocol,r) for r in plan.builds}):
            raise ContractError('common barrier lost complete original history evidence')
        for stage in self.builds: self.executor.verify(stage)

    def package(self, recipe):
        self.verify()
        build=next(s for s in self.builds if s.record.data()['build_id']==history_build_id(self.executor.plan.protocol,recipe))
        return CandidatePackage(_read_record(build.inner.root/'candidate.json'))


def compile_panel(barrier):
    if type(barrier) is not JointTrainBarrier: raise ContractError('original common history barrier required')
    barrier.verify(); plan=barrier.executor.plan; protocol=plan.protocol; body=protocol.record.data()
    packages={recipe['id']:barrier.package(recipe) for recipe in plan.recipes}
    scenarios={p.task.content_hash:R({'schema':'c5-common-target-scenario-v1','protocol_digest':protocol.digest,
        'runtime_plan_digest':plan.record.content_hash,'barrier_digest':barrier.record.content_hash,
        'task_digest':p.task.content_hash,'material_digest':plan.material(p.task.content_hash).record.content_hash,
        'phase_material_digest':plan.phase_material(p.task.content_hash).record.content_hash}) for p in plan.packets}
    cells=tuple(PanelCell(OBLIGATION,p.task.identity,'r1','combination',recipe['id'],target_arm(protocol,recipe),
        p.task.content_hash,scenarios[p.task.content_hash].content_hash,packages[recipe['id']].digest,
        ScorerConfig(R(body['scorer'])).digest) for recipe in plan.recipes for p in plan.packets)
    panel=JointTrainPanel(plan.data()['stage'],'train',plan.history.task.identity.split_id,OBLIGATION,'joint_bundle',protocol.record,
        R({'schema':'c5-common-procedure-package-bundle-v1','packages':{k:v.record.data() for k,v in packages.items()}}),
        R({'schema':'c5-common-train-measurement-criteria-v1','train_adapted_selection':body['selection_rule'],
            'scientific_acceptance_authorized':False,'validation_access_authorized':False}),cells,
        training_provenance=R({'schema':'c5-common-history-build-exposure-v1','protocol_digest':protocol.digest,
            'runtime_plan_digest':plan.record.content_hash,'barrier_digest':barrier.record.content_hash,
            'build_receipts':barrier.record.data()['build_receipts'],'candidate_selections':{k:v.digest for k,v in packages.items()}}))
    return panel,scenarios
