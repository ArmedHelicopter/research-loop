"""Predeclare -> history build -> freeze all candidates -> target solve -> score.

This version binds eight arms to two shared builds and 16 target opportunities.
A missing canonical build blocks the global candidate barrier;
it never silently substitutes a package or drops a denominator.
"""
from dataclasses import dataclass
from contextlib import nullcontext
import json
from pathlib import Path
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.combination_scoring import verify_combination_adapted_receipt
from evaluation.modular.lineage_retrieval_improvement_scoring import issue_lineage_retrieval_improvement_score_input
from research_loop.modular.lineage_retrieval_improvement_panel import LineageRetrievalImprovementPanel, DESIGNS, registered_design
from research_loop.modular.lineage_retrieval_improvement_modules import model_schemas, slots
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.state_retrieval_combination_driver import FrozenStateRetrievalMaterial, check_retrieval
from research_loop.modular.lineage_combination_material import DualMaterialVerifier
from research_loop.modular.state_improvement_build import (BuildResult, FrozenProviderLedger, material_class, qualifier_check,
    check_history, build_binding, qualification_semantics, run_build, verify_build)
from research_loop.modular.lineage_retrieval_improvement_combination_driver import run_lineage_retrieval_improvement_cell, verify_lineage_retrieval_improvement_cell
from research_loop.modular.metaprogram_training import (FrozenTrainHistory, model_configuration, metaprogram_schemas,
    _builder, _path, _exclusive, _read_record, _sha, _Journal, _phase_rows, _atomic)
from research_loop.modular.combination_train_source import CombinationTrainSource, packet_index
from research_loop.modular.combination_train_controller import _ANALYSIS, _usage
from research_loop.modular.lineage_combination_material import check_material_inputs
from research_loop.modular.state_retrieval_combination_controller import _validate_source_binding
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.combination_panels import CombinationPanelVerifier
from research_loop.modular.lineage_retrieval_improvement_contrasts import estimate_components, component_policy
from research_loop.ontology import ContractError, canonical
from research_loop.modular.phase_provider import (PROVIDERS, PhaseProviderSession, PhaseProviderLedger, PhaseProviderAbort,
    provider_configuration, validate_configuration)

ALLOCATION={'arm_recipe_bindings':8,'build_recipes':2,'builder_proposals':2,'builder_executions':2,
    'target_cells':16,'structural_exclusions':0,'target_model_calls':32,'model_calls':34,
    'source_calls':68,'retrieval_operations':16,'retrieval_calls':48,'docker_attempts':16,'scorer_calls':16}
ESTIMAND='target_lineage_retrieval_by_shared_history_candidate_conditional_interaction'



def arm_recipes(baseline):
    return [{'pair':pair,'arm_id':c['id'],'arm':c['arm']} for pair in DESIGNS
        for c in registered_design(pair,baseline).data()['cells'] if c['status']=='executable']


def recipes(baseline):
    return [{'pair':pair,'arm_id':arm_id,'arm':default_compatibility(baseline).arm(enabled).data()}
        for pair in DESIGNS for arm_id,enabled in [('000',['M2']),('001',['M2','M9'])]]


def selections(baseline):
    return [{'pair':r['pair'],'arm_id':r['arm_id'],'canonical_build_arm_id':'00'+r['arm_id'][2]}
        for r in arm_recipes(baseline)]


def target_recipes(body):
    return [{'pair':r['pair'],'arm_id':r['arm_id'],'task_digest':body['task_bindings'][token]['task_digest'],'replicate':'r1'}
        for r in arm_recipes(body['baseline_digest']) for token in body['item_ids']]


@dataclass(frozen=True)
class FrozenLineageRetrievalImprovementPlan:
    record: FrozenRecord
    history: FrozenTrainHistory
    history_inputs: tuple

    def __post_init__(self):
        b=self.data()
        required={'schema','export_mode','stage','domain','item_ids','task_bindings','baseline_digest','history_binding','history_inputs',
            'parent','fixed_builder','history_materials','target_materials','source_verifier_bindings','model_config',
            'scorer','scorer_handle_bindings','acceptance_criteria','objective','image','timeout_seconds','allocation','pipeline_estimand','candidate_selections','retrieval_materials','retrieval_verifier_binding'}
        if (type(self) is not FrozenLineageRetrievalImprovementPlan or set(b)!=required or b['schema'] not in {'lineage-retrieval-improvement-train-plan-v1','lineage-retrieval-improvement-train-plan-v2'}
                or b['export_mode']!='primary_prospective' or b['domain']!='train' or b['allocation']!=ALLOCATION
                or b['pipeline_estimand']!=ESTIMAND or b['candidate_selections']!=selections(b['baseline_digest'])
                or not isinstance(b['stage'],str) or not b['stage'].strip() or type(self.history) is not FrozenTrainHistory
                or b['history_binding']!=self.history.binding.data() or not isinstance(self.history_inputs,tuple)):
            raise ContractError('exact versioned history/target TRAIN plan required')
        if len(self.history_inputs)!=1 or self.history_inputs[0][0]!='public_csv': raise ContractError('one exact history CSV required')
        path=_path(self.history_inputs[0][1]);raw=path.read_bytes()
        if b['history_inputs']!={'public_csv':{'sha256':_sha(raw),'byte_count':len(raw)}}: raise ContractError('history CSV drift')
        self.history.verify()
        if not isinstance(b['item_ids'],list) or len(b['item_ids'])!=2 or len(set(b['item_ids']))!=2 or set(b['task_bindings'])!=set(b['item_ids']):
            raise ContractError('exact two target tokens required')
        identities=[]
        for token,row in b['task_bindings'].items():
            if (len(token)!=64 or any(c not in '0123456789abcdef' for c in token)
                    or set(row)!={'identity','task_digest','csv_sha256','csv_byte_count'}): raise ContractError('target source binding fields differ')
            identity=DataIdentity.parse(row['identity']);identity.require_train();identities.append(identity)
            if (identity.benchmark,identity.task_id,identity.group_id)==(self.history.task.identity.benchmark,self.history.task.identity.task_id,self.history.task.identity.group_id):
                raise ContractError('optimizer history overlaps target subject')
            for key in ('task_digest','csv_sha256'):
                v=row[key]
                if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v): raise ContractError('target digest malformed')
            if type(row['csv_byte_count']) is not int or row['csv_byte_count']<0: raise ContractError('target byte budget invalid')
        if {i.benchmark for i in identities}!={'blade','discoverybench'} or len({i.split_id for i in identities})!=1:
            raise ContractError('two core benchmark targets in one train split required')
        if set(TrainingManifest(FrozenRecord.from_dict(self.parent.record.data()['training_manifest'])).identities())!={self.history.task.identity}:
            raise ContractError('candidate training manifest must contain only the history')
        _builder(self.fixed_builder)
        if (set(b['history_materials'])!=set(DESIGNS) or set(b['target_materials'])!=set(DESIGNS)
                or set(b['source_verifier_bindings'])!=set(DESIGNS)): raise ContractError('exact M3/M6/M9 triple material inventory required')
        budgets=set()
        for pair in DESIGNS:
            _validate_source_binding(b['source_verifier_bindings'][pair])
            m=self.history_material(pair);budgets.add(m.data()['context_budget_bytes'])
            if m.data()['task_digest']!=self.history.task.content_hash: raise ContractError('foreign optimizer state')
            entries=b['target_materials'][pair]
            if set(entries)!={r['task_digest'] for r in b['task_bindings'].values()}: raise ContractError('exact target state coverage required')
            for row in b['task_bindings'].values():
                m=self.target_material(pair,row['task_digest']);budgets.add(m.data()['context_budget_bytes'])
                if (m.data()['identity']!=row['identity'] or m.data()['task_digest']!=row['task_digest']
                        or m.data()['public_artifacts']!=[{'artifact':{'artifact_id':'public_csv','sha256':row['csv_sha256'],
                            'byte_count':row['csv_byte_count']},'container_path':'/input/public_csv'}]):
                    raise ContractError('target material and original custody CSV differ')
        if len(budgets)!=1 or len({v['cost_limit_per_call'] for v in b['source_verifier_bindings'].values()})!=1:
            raise ContractError('state context/source cost allocation must match')
        config=b['model_config']
        if b['schema']=='lineage-retrieval-improvement-train-plan-v2':
            validate_configuration(FrozenRecord.from_dict(config),schemas=model_schemas(),main_opportunities=34)
        else:
            if (set(config)!={'model','effort','max_calls','max_tokens','schemas','context_policy_sha256'}
                    or config['model']!='gpt-5.6-luna' or config['effort']!='low' or config['max_calls']!=34
                    or type(config['max_tokens']) is not int or config['max_tokens']<1 or config['schemas']!=model_schemas()):
                raise ContractError('matched exact proposal and target model opportunities required')
        scorer=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
        if (scorer.record.data()['rubric_digest']!=FrozenBenchmarkRubricEndpoint.rubric_digest()
                or b['acceptance_criteria']!={'contrast_analysis':_ANALYSIS,'factorial_components':component_policy().data()}
                or set(b['scorer_handle_bindings'])!={FrozenRecord.from_dict(i.data()).content_hash for i in identities}
                or not isinstance(b['objective'],dict) or not b['objective'] or type(b['timeout_seconds']) is not int or not 1<=b['timeout_seconds']<=120):
            raise ContractError('frozen primary scorer, estimand, objective and timeout required')
        for identity in identities: ExecutionRequest(identity,b['image'],Path('planned.py'),{'public_csv':Path('planned.csv')},b['timeout_seconds'])
        if len(recipes(b['baseline_digest']))!=2 or len(arm_recipes(b['baseline_digest']))!=8: raise ContractError('registered legal build inventory changed')

        _validate_source_binding(b['retrieval_verifier_binding'])
        if set(b['retrieval_materials'])!={r['task_digest'] for r in b['task_bindings'].values()}:
            raise ContractError('exact target retrieval inventory required')
        for task_hash,value in b['retrieval_materials'].items():
            composite=FrozenStateRetrievalMaterial(FrozenRecord.from_dict(value))
            if composite.state()!=self.target_material('triple:M3+M6+M9',task_hash):
                raise ContractError('corpus provenance differs from exact fixed target state')

    def data(self): return self.record.data()
    @property
    def parent(self): return CandidatePackage(FrozenRecord.from_dict(self.data()['parent']))
    @property
    def fixed_builder(self): return FrozenBuilderVersion(FrozenRecord.from_dict(self.data()['fixed_builder']))
    def history_material(self,pair): return material_class(pair)(FrozenRecord.from_dict(self.data()['history_materials'][pair]))
    def target_material(self,pair,task): return material_class(pair)(FrozenRecord.from_dict(self.data()['target_materials'][pair][task]))

    def check_packets(self,packets):
        self.__post_init__();by_item=packet_index(self.data(),packets)
        for token,p in by_item.items():
            b=self.data()['task_bindings'][token]
            if (p.task.identity.data()!=b['identity'] or p.task.content_hash!=b['task_digest']
                    or _sha(p.csv_path.read_bytes())!=b['csv_sha256'] or p.csv_path.stat().st_size!=b['csv_byte_count']):
                raise ContractError('prospective target source differs from frozen plan')


@dataclass(frozen=True)
class CandidateBarrier:
    root: Path
    record: FrozenRecord
    plan: FrozenLineageRetrievalImprovementPlan
    builds: tuple
    ledger: FrozenProviderLedger | PhaseProviderLedger
    qualifiers: dict
    broker: object
    packets: tuple
    prefix: tuple

    def _order(self,actual):
        b=self.plan.data()
        structural=[{'pair':p,'arm_id':c['id'],'reason':c['reason'],'task_digest':row['task_digest']}
            for p in DESIGNS for c in registered_design(p,b['baseline_digest']).data()['cells'] if c['status']!='executable'
            for row in b['task_bindings'].values()]
        expected=[('phase_lock',{'plan_digest':self.plan.record.content_hash,'build_recipes':recipes(b['baseline_digest']),
            'target_recipes':target_recipes(b),'structural_exclusions':structural,'allocation':ALLOCATION})]
        for result in self.builds:
            expected.extend([('build_reserved',{'recipe':result.record.data()['recipe']}),
                ('build_completed',{'receipt_digest':result.record.content_hash,'status':'succeeded'})])
        expected.append(('build_ledger_sealed',{'digest':self.ledger.record.content_hash}))
        if [(r.data()['stage'],r.data()['data']) for r in self.prefix]!=expected:
            raise ContractError('candidate barrier requires the exact complete original build order')
        suffix=actual[len(self.prefix):]
        if not suffix:return
        if (suffix[0]['stage']!='candidate_barrier' or suffix[0]['data'].get('digest')!=self.record.content_hash
                or set(suffix[0]['data'])!={'digest','panels'} or len(suffix[0]['data']['panels'])!=1):
            raise ContractError('target I/O precedes the immutable candidate barrier')
        cursor=0;active=None;sealed=False;scorer=None;scored=set();completed={};planned=target_recipes(b)
        for event in suffix[1:]:
            stage=event['stage'];data=event['data']
            if stage in {'target_reserved','target_blocked'}:
                if sealed or active is not None or cursor>=len(planned):raise ContractError('target opportunity order drift')
                row=data['cell'] if stage=='target_reserved' else data
                binding={'pair':row.get('coverage_id',row.get('pair')),'arm_id':row['arm_id'],'task_digest':row['task_digest'],'replicate':row['replicate']}
                if binding!=planned[cursor]:raise ContractError('target reservation differs from original recipe order')
                if stage=='target_reserved':
                    active=(row['coverage_id'],row['identity']['benchmark'],row['identity']['task_id'],row['identity']['group_id'],row['replicate'],row['variant'],row['arm_id'])
                else:cursor+=1
            elif stage=='target_completed':
                if active is None or tuple(data['cell_key'])!=active or data['status'] not in {'executed','failed'}:
                    raise ContractError('target completion lacks its original reservation')
                completed[active]=data['status'];active=None;cursor+=1
            elif stage=='target_ledger_sealed':
                if sealed or active is not None or cursor!=16:raise ContractError('provider seal precedes complete target denominator')
                sealed=True
            elif stage=='scorer_reserved':
                key=tuple(data['cell_key'])
                if not sealed or scorer is not None or key in scored or completed.get(key)!='executed':
                    raise ContractError('scorer lacks a unique completed target after provider seal')
                scorer=key;scored.add(key)
            elif stage=='scorer_completed':
                if scorer is None or tuple(data['cell_key'])!=scorer or data['status'] not in {'succeeded','failed'}:
                    raise ContractError('scorer completion differs from reservation')
                scorer=None
            else:raise ContractError('unknown side effect in state improvement controller journal')

    def verify(self):
        if (type(self) is not CandidateBarrier or type(self.plan) is not FrozenLineageRetrievalImprovementPlan
                or type(self.ledger) is not (PhaseProviderLedger if self.plan.data()['schema'].endswith('-v2') else FrozenProviderLedger) or type(self.builds) is not tuple
                or any(type(result) is not BuildResult for result in self.builds)):
            raise ContractError('exact barrier plan, builds and original provider ledger required')
        self.plan.check_packets(self.packets);self.ledger.verify()
        if (_path(self.root/'candidate-barrier.json').read_bytes()!=(self.record.encoded+'\n').encode('utf-8')
                or _path(self.root/'plan.json').read_bytes()!=(self.plan.record.encoded+'\n').encode('utf-8')): raise ContractError('original plan or global candidate barrier drift')
        actual=_phase_rows(self.root/'controller.jsonl')
        if tuple(FrozenRecord.from_dict(r) for r in actual[:len(self.prefix)])!=self.prefix:
            raise ContractError('global build order/reservations changed before barrier')
        self._order(actual)
        expected={'schema':('lineage-retrieval-improvement-candidate-barrier-v2' if self.plan.data()['schema'].endswith('-v2') else 'lineage-retrieval-improvement-candidate-barrier-v1'),'plan_digest':self.plan.record.content_hash,
            'build_receipts':[r.record.content_hash for r in self.builds], 'provider_ledger_digest':self.ledger.record.content_hash,
            'candidate_selections':selections(self.plan.data()['baseline_digest']),
            'controller_prefix_digest':FrozenRecord.from_dict({'rows':[r.data() for r in self.prefix]}).content_hash}
        if (self.record.data()!=expected or len(self.builds)!=2
                or [r.record.data()['recipe'] for r in self.builds]!=recipes(self.plan.data()['baseline_digest'])):
            raise ContractError('barrier requires all predeclared original builds')
        for result in self.builds:
            recipe=result.record.data()['recipe'];pair=recipe['pair'];qualifier=self.qualifiers[pair]
            if qualifier.binding().data()!=self.plan.data()['source_verifier_bindings'][pair]: raise ContractError('build source keys drift')
            verify_build(result,recipe=recipe,plan_digest=self.plan.record.content_hash,history=self.plan.history,
                material=self.plan.history_material(pair),qualifier=qualifier,parent=self.plan.parent,fixed_builder=self.plan.fixed_builder,
                broker=self.broker,inputs=dict(self.plan.history_inputs),ledger=self.ledger)

    def package(self,pair,arm_id):
        row=next(r for r in self.builds if r.record.data()['recipe']['pair']==pair and r.record.data()['recipe']['arm_id']=='00'+arm_id[2])
        return CandidatePackage(_read_record(row.root/'candidate.json'))

    def provenance(self):
        return FrozenRecord.from_dict({'schema':'lineage-retrieval-improvement-exposure-v1','history_identity':self.plan.history.task.identity.data(),
            'history_binding_digest':self.plan.history.binding.content_hash,
            'target_identities':[self.plan.data()['task_bindings'][t]['identity'] for t in self.plan.data()['item_ids']],
            'barrier_digest':self.record.content_hash,'outer_plan_digest':self.plan.record.content_hash,
            'candidate_selection_digest':FrozenRecord.from_dict({'selections':selections(self.plan.data()['baseline_digest'])}).content_hash})


def compile_panels(barrier):
    barrier.verify();b=barrier.plan.data();panels=[];scenarios={}
    for pair in DESIGNS:
        design=registered_design(pair,b['baseline_digest']);cells=[];packages={}
        for recipe in [r for r in arm_recipes(b['baseline_digest']) if r['pair']==pair]:
            arm=FrozenRecord.from_dict(recipe['arm']);package=barrier.package(pair,recipe['arm_id']);packages[arm.content_hash]=package.record.data()
            for packet in barrier.packets:
                task=packet.task;material=barrier.plan.target_material(pair,task.content_hash)
                scenario=FrozenRecord.from_dict({'schema':'lineage-retrieval-improvement-scenario-v1','pair':pair,'design_digest':design.content_hash,
                    'task_digest':task.content_hash,'material_digest':material.record.content_hash,'replicate':'r1',
                    'source_verifier_binding':b['source_verifier_bindings'][pair],'barrier_digest':barrier.record.content_hash,
                    'objective':b['objective'],'image':b['image'],'timeout_seconds':b['timeout_seconds'],
                    'retrieval_material_digest':FrozenRecord.from_dict(b['retrieval_materials'][task.content_hash]).content_hash if pair=='triple:M3+M6+M9' else None,
                    'retrieval_verifier_binding':b['retrieval_verifier_binding'] if pair=='triple:M3+M6+M9' else None})
                cell=PanelCell(pair,task.identity,'r1','combination',recipe['arm_id'],arm,task.content_hash,scenario.content_hash,
                    package.digest,FrozenRecord.from_dict(b['scorer']).content_hash)
                cells.append(cell);scenarios[cell.key]=scenario
        panels.append(LineageRetrievalImprovementPanel(b['stage'],'train',barrier.packets[0].task.identity.split_id,pair,'interaction_on_scale',design,
            FrozenRecord.from_dict({'schema':'combination-package-bundle-v1','packages':packages}),
            FrozenRecord.from_dict(b['acceptance_criteria']),tuple(cells),training_provenance=barrier.provenance()))
    return tuple(panels),scenarios


@dataclass(frozen=True)
class LineageRetrievalImprovementRun:
    root: Path
    barrier: CandidateBarrier | None
    panels: tuple
    scenarios: dict
    results: tuple
    scores: tuple
    attempts: tuple
    builds: tuple
    ledger: FrozenProviderLedger | PhaseProviderLedger | PhaseProviderAbort
    receipt: FrozenRecord


def run_lineage_retrieval_improvement_train(plan,*,prospective_exporter,snapshot_root,export_root,run_root,model,audit_verifier,
        source_verifiers,retrieval_verifier,provider_factory,scorer_factory,execution_authority,scorer_authority_keys,custody=None):
    if type(plan) is not FrozenLineageRetrievalImprovementPlan: raise ContractError('exact immutable state improvement plan required')
    plan.__post_init__();b=plan.data()
    native=b['schema']=='lineage-retrieval-improvement-train-plan-v2'
    if native:
        if type(model) not in PROVIDERS or provider_configuration(model).data()!=b['model_config'] or model.inspect() or model.terminal():
            raise ContractError('fresh matched closed TRAIN provider required')
    elif model_configuration(model).data()!=b['model_config'] or model.ledger['calls'] or model.ledger['tokens'] or model.ledger['usage_incomplete']:
        raise ContractError('fresh matched real model port required')
    usage=lambda: scopes.usage().data() if native else _usage(model)
    terminal=lambda: scopes.terminal() if native else model.ledger['usage_incomplete']
    if set(source_verifiers)!=set(DESIGNS) or not callable(scorer_factory): raise ContractError('exact source and scorer factories required')
    for pair,q in source_verifiers.items():
        qualifier_check(pair,plan.history_material(pair),q)
        if q.binding().data()!=b['source_verifier_bindings'][pair]: raise ContractError('frozen source bindings changed')
        if any(a.authority.key in {execution_authority.key,*scorer_authority_keys.values()}
                or a.authority.authority_id in {execution_authority.authority_id,*scorer_authority_keys} for a in q.authorities):
            raise ContractError('source, execution and scorer authorities must be independent')
    if type(retrieval_verifier) is not DualMaterialVerifier or retrieval_verifier.binding().data()!=b['retrieval_verifier_binding'] or not callable(provider_factory):
        raise ContractError('exact independent corpus qualifier and retrieval factory required')
    if any(a.authority.key in {execution_authority.key,*scorer_authority_keys.values(),*[x.authority.key for q in source_verifiers.values() for x in q.authorities]}
            for a in retrieval_verifier.authorities):raise ContractError('corpus qualifier must use independent authority keys')
    root=_path(run_root,exists=False);exported=_path(export_root,exists=False);snapshot=_path(snapshot_root,exists=False)
    roots=[root.resolve(),exported.resolve(),snapshot.resolve(),model.root.resolve()]
    if root.exists() or exported.exists() or any(a==c or a in c.parents or c in a.parents for i,a in enumerate(roots) for c in roots[i+1:]):
        raise ContractError('fresh disjoint controller/source/provider roots required')
    source=CombinationTrainSource(b,custody=custody,prospective_exporter=prospective_exporter,snapshot=snapshot,exported=exported)
    root.mkdir(parents=True);_exclusive(root/'plan.json',plan.record)
    scopes=PhaseProviderSession(model,root/'provider-scopes.json') if native else None
    excluded=[{'pair':p,'arm_id':c['id'],'reason':c['reason'],'task_digest':row['task_digest']}
        for p in DESIGNS for c in registered_design(p,b['baseline_digest']).data()['cells'] if c['status']!='executable'
        for row in b['task_bindings'].values()]
    phase=_Journal(root/'controller.jsonl');phase.append('phase_lock',{'plan_digest':plan.record.content_hash,'build_recipes':recipes(b['baseline_digest']),
        'target_recipes':target_recipes(b),'structural_exclusions':excluded,'allocation':ALLOCATION})
    buildrows=[{'recipe':r,'status':'not_started'} for r in recipes(b['baseline_digest'])]
    targets=[{**r,'status':'not_started','scorer_calls':0,'docker_attempts':0} for r in target_recipes(b)]
    journal={'schema':('lineage-retrieval-improvement-controller-attempt-v2' if b['schema'].endswith('-v2') else 'lineage-retrieval-improvement-controller-attempt-v1'),'plan_digest':plan.record.content_hash,'builds':buildrows,
        'targets':targets,'structural_exclusions':excluded,'allocation':ALLOCATION,'status':'exporting'}
    def persist(checked_usage=None): journal['model_usage']=usage() if checked_usage is None else checked_usage;_atomic(root/'controller-attempt.json',journal)
    persist()
    try:
        packets=tuple(source.export());plan.check_packets(packets)
        for p in packets:check_retrieval(FrozenStateRetrievalMaterial(FrozenRecord.from_dict(b['retrieval_materials'][p.task.content_hash])).retrieval(),p.task)
        broker=DockerExecutionBroker([exported,root,plan.history_inputs[0][1].parent])
        for pair in DESIGNS:
            check_history(plan.history,plan.history_material(pair),broker,dict(plan.history_inputs))
            for p in packets: check_material_inputs(plan.target_material(pair,p.task.content_hash),p.task,broker,{'public_csv':p.csv_path})
    except Exception as exc:
        for row in [*buildrows,*targets]: row.update(status='blocked',reason='source_preflight')
        journal.update(status='blocked_before_execution',error_type=type(exc).__name__);persist();raise
    builds=[];barrier=None;panels=();scenarios={};results=[];scores=[];score_inputs={};services={};poison=False
    try:
        for row in buildrows:
            recipe=row['recipe']
            if poison or terminal():
                row.update(status='blocked',reason='prior_unknown_cost');phase.append('build_blocked',row.copy());persist();continue
            try:plan.check_packets(packets)
            except Exception as exc:
                poison=True;row.update(status='failed',reason='source_drift',error_type=type(exc).__name__)
                phase.append('build_preflight_failed',row.copy());persist();continue
            phase.append('build_reserved',{'recipe':recipe});row['status']='running';persist()
            result=None
            try:
                with (scopes.scope('build:'+FrozenRecord.from_dict(recipe).content_hash) if native else nullcontext(model)) as scoped_model:
                    result=run_build(recipe=recipe,plan_digest=plan.record.content_hash,history=plan.history,material=plan.history_material(recipe['pair']),
                        qualifier=source_verifiers[recipe['pair']],parent=plan.parent,fixed_builder=plan.fixed_builder,broker=broker,
                        inputs=dict(plan.history_inputs),model=scoped_model,audit_verifier=audit_verifier,root=root/'builds'/str(len(builds)))
            except ContractError as exc:
                if not native:raise
                scopes.abort();poison=True
                row.update(status='failed',reason='provider_provenance_fault',error_type=type(exc).__name__)
                if result is None:
                    phase.append('build_preflight_failed',row.copy());persist();continue
            builds.append(result)
            row.update(status='failed' if native and scopes.aborted is not None else result.record.data()['status'],receipt=result.record.data())
            sourcepath=result.root/'source'/'source-verification.json'
            if sourcepath.is_file():
                row['source']=json.loads(sourcepath.read_bytes())
                poison=poison or any(c.get('cost_units') is None for c in row['source'].get('calls',[]))
            phase.append('build_completed',{'receipt_digest':result.record.content_hash,'status':row['status']});persist()
        buildledger=(scopes.finish(root/'build-provider-ledger.json') if native else FrozenProviderLedger.freeze(model,root/'build-provider-ledger.json'))
        phase.append('build_provider_aborted' if type(buildledger) is PhaseProviderAbort else 'build_ledger_sealed',{'digest':buildledger.record.content_hash})
        if not poison and type(buildledger) is not PhaseProviderAbort and len(builds)==2 and all(r.record.data()['status']=='succeeded' for r in builds):
            prefix=tuple(phase.rows)
            record=FrozenRecord.from_dict({'schema':('lineage-retrieval-improvement-candidate-barrier-v2' if b['schema'].endswith('-v2') else 'lineage-retrieval-improvement-candidate-barrier-v1'),'plan_digest':plan.record.content_hash,
                'build_receipts':[r.record.content_hash for r in builds],'provider_ledger_digest':buildledger.record.content_hash,
                'candidate_selections':selections(b['baseline_digest']),
                'controller_prefix_digest':FrozenRecord.from_dict({'rows':[r.data() for r in prefix]}).content_hash})
            _exclusive(root/'candidate-barrier.json',record)
            barrier=CandidateBarrier(root,record,plan,tuple(builds),buildledger,source_verifiers,broker,packets,prefix)
            try:
                panels,scenarios=compile_panels(barrier)
                services=scorer_factory(panels)
                if set(services)!=set(DESIGNS): raise ContractError('scorers must cover the exact frozen target panels')
                for panel in panels:
                    service=services[panel.obligation_id]
                    if type(service) is not CombinationScorerProcessClient or service.lineage_retrieval_improvement is not True or service.panel!=panel:
                        raise ContractError('exact state improvement process scorer required')
                    service.assert_configuration(config=ScorerConfig(FrozenRecord.from_dict(b['scorer'])),task_handle_bindings=b['scorer_handle_bindings'],
                        execution_authority_keys={execution_authority.authority_id:execution_authority.key},scorer_authority_keys=scorer_authority_keys)
                phase.append('candidate_barrier',{'digest':record.content_hash,'panels':[p.digest for p in panels]})
                journal['panels']=[{'digest':p.digest,'cells':[c.data() for c in p.cells]} for p in panels];persist()
            except Exception as exc:
                poison=True;journal['barrier_error']=type(exc).__name__;phase.append('barrier_failed',{'error_type':type(exc).__name__})
        else: poison=True
        lookup={(p.obligation_id,c.arm_id,c.task_digest):(p,c) for p in panels for c in p.cells}
        args_by_key={}
        for row in targets:
            result=None
            if poison or terminal() or not panels:
                row.update(status='blocked',reason='global_barrier_or_unknown_cost');phase.append('target_blocked',row.copy());persist();results.append(None);continue
            panel,cell=lookup[row['pair'],row['arm_id'],row['task_digest']];packet=next(p for p in packets if p.task.content_hash==cell.task_digest)
            args=dict(panel=panel,task=packet.task,scenario=scenarios[cell.key],package=barrier.package(panel.obligation_id,cell.arm_id),
                material=plan.target_material(panel.obligation_id,cell.task_digest),source_verifier=source_verifiers[panel.obligation_id],
                barrier=barrier,public_inputs={'public_csv':packet.csv_path},broker=broker,
                retrieval_material=FrozenStateRetrievalMaterial(FrozenRecord.from_dict(b['retrieval_materials'][cell.task_digest])) if cell.coverage_id=='triple:M3+M6+M9' else None,
                retrieval_verifier=retrieval_verifier if cell.coverage_id=='triple:M3+M6+M9' else None)
            args_by_key[cell.key]=args;cellroot=root/'targets'/FrozenRecord.from_dict(cell.data()).content_hash
            row['cell']=cell.data();row['status']='running';phase.append('target_reserved',{'cell':cell.data()});persist()
            try:
                with (scopes.scope('target:'+FrozenRecord.from_dict(cell.data()).content_hash) if native else nullcontext(model)) as scoped_model:
                    result=run_lineage_retrieval_improvement_cell(cell=cell,**args,sidecar=cellroot,model=scoped_model,audit_verifier=audit_verifier,
                        provider=provider_factory(cell) if cell.coverage_id=='triple:M3+M6+M9' else None)
                row.update(status='executed' if result.runtime.status=='succeeded' else 'failed',runtime_digest=result.runtime.trace_digest)
            except Exception as exc:
                row.update(status='failed',error_type=type(exc).__name__)
                if native and scopes.aborted is not None:poison=True
            sourcepath=cellroot/'source-verification.json'
            if sourcepath.is_file():
                row['source']=json.loads(sourcepath.read_bytes())
                poison=poison or any(c.get('cost_units') is None for c in row['source'].get('calls',[]))
            retrievalpath=cellroot/'retrieval'/'source-verification.json'
            if retrievalpath.is_file():
                row['retrieval_source']=json.loads(retrievalpath.read_bytes())
                poison=poison or any(c.get('cost_units') is None for c in row['retrieval_source'].get('calls',[]))
            if result is not None:
                row['retrieval_calls']=sum(FrozenRecord(line).data()['stage']=='q8_retrieval_request' for line in result.runtime.trace_path.read_text().splitlines())
                row['docker_attempts']=sum(FrozenRecord(line).data()['stage']=='execution_request' for line in result.runtime.trace_path.read_text().splitlines())
            results.append(result);phase.append('target_completed',{'cell_key':list(cell.key),'status':row['status']});persist()
        ledger=(scopes.finish(root/'target-provider-ledger.json') if native else FrozenProviderLedger.freeze(model,root/'target-provider-ledger.json'));phase.append('target_provider_aborted' if type(ledger) is PhaseProviderAbort else 'target_ledger_sealed',{'digest':ledger.record.content_hash})
        for row,result in zip(targets,results,strict=True):
            if type(ledger) is PhaseProviderAbort or (native and scopes.aborted is not None):
                if row['status']=='executed':row.update(status='failed',reason='provider_provenance_fault')
                continue
            if result is None or row['status']!='executed': continue
            cell=result.cell;args=args_by_key[cell.key];service=services[cell.coverage_id]
            try:
                verified=verify_lineage_retrieval_improvement_cell(result,**args,ledger=ledger);row['verification']=verified.data()
                scoreinput=issue_lineage_retrieval_improvement_score_input(authority=execution_authority,result=result,**args,ledger=ledger)
                score_inputs[cell.key]=scoreinput;row['score_input']=scoreinput.data();row['scorer_calls']=1
                phase.append('scorer_reserved',{'cell_key':list(cell.key),'input_digest':scoreinput.content_hash});persist()
                score=service.score_combination(panel=args['panel'],cell=cell,score_input=scoreinput)
                verify_combination_adapted_receipt(score,authority_keys=scorer_authority_keys,config=service.config,panel=args['panel'],cell=cell,
                    score_input=scoreinput,execution_authority_keys={execution_authority.authority_id:execution_authority.key})
                scores.append(score);row.update(status='succeeded',score=score.receipt.data())
            except Exception as exc: row.update(status='failed',error_type=type(exc).__name__)
            phase.append('scorer_completed',{'cell_key':list(cell.key),'status':row['status']});persist()
        contrasts=[]
        for pair in DESIGNS:
            panel=next((p for p in panels if p.obligation_id==pair),None)
            try:
                if panel is None: raise ContractError('candidate barrier unavailable')
                if native and (scopes.aborted is not None or type(ledger) is PhaseProviderAbort):
                    raise ContractError('provider_provenance_fault')
                def verify_score(score,cell,owner):
                    verify_combination_adapted_receipt(score,authority_keys=scorer_authority_keys,config=services[pair].config,panel=owner,cell=cell,
                        score_input=score_inputs[cell.key],execution_authority_keys={execution_authority.authority_id:execution_authority.key})
                contrast=estimate_components(panel,runtime=[r.runtime for r in results if r is not None and r.cell.coverage_id==pair],
                    scorer_receipts=[s for s in scores if s.cell_key in {c.key for c in panel.cells}],verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
            except Exception as exc: contrast=FrozenRecord.from_dict({'pair':pair,'status':'inconclusive','reason':str(exc),'scientific_effect':'not_measured'})
            contrasts.append(contrast)
        sourcecharges=[c for r in [*buildrows,*targets] for source_key in ('source','retrieval_source') for c in r.get(source_key,{}).get('calls',[])]
        sourcecalls=len(sourcecharges)
        buildercalls=sum(sum(x['stage']=='builder_request' for x in _phase_rows(r.root/'phase.jsonl')) for r in builds)
        dockercalls=sum(r['docker_attempts'] for r in targets);scorercalls=sum(r['scorer_calls'] for r in targets)
        # Replay after the last scorer and contrast return, before final eligibility.
        provider_eligible=True
        if native:
            provider_eligible=False
            if scopes.aborted is None and type(ledger) is PhaseProviderLedger:
                try:provider_eligible=ledger.verify().data()['score_eligible']
                except ContractError:scopes.abort()
            final_usage=usage()
            if scopes.aborted is not None:
                if type(ledger) is not PhaseProviderAbort:
                    ledger=scopes.finish(root/'final-provider-abort.json')
                provider_eligible=False
            if not provider_eligible:
                contrasts=[FrozenRecord.from_dict({'pair':pair,'status':'inconclusive',
                    'reason':'provider_provenance_fault' if type(ledger) is PhaseProviderAbort else 'provider_not_score_eligible',
                    'scientific_effect':'not_measured'}) for pair in DESIGNS]
            for row in targets:
                row['score_eligible']=provider_eligible and row['status']=='succeeded'
        else:final_usage=usage()
        receipt=FrozenRecord.from_dict({'schema':('lineage-retrieval-improvement-train-receipt-v2' if b['schema'].endswith('-v2') else 'lineage-retrieval-improvement-train-receipt-v1'),'plan_digest':plan.record.content_hash,'allocation':ALLOCATION,
            'expected_builds':2,'arm_recipe_bindings':selections(b['baseline_digest']),'successful_builds':sum(r['status']=='succeeded' for r in buildrows),'expected_cells':16,
            'failed_builds':sum(r['status']=='failed' for r in buildrows),'blocked_builds':sum(r['status']=='blocked' for r in buildrows),
            'scored_cells':len(scores),'failed_cells':sum(r['status']=='failed' for r in targets),'blocked_cells':sum(r['status']=='blocked' for r in targets),
            'actual_model_usage':final_usage,'source_calls':sourcecalls,'actual_builder_executions':buildercalls,
            'known_source_cost_units':sum(c['cost_units'] for c in sourcecharges if c.get('cost_units') is not None),
            'source_cost_unknown':any(c.get('cost_units') is None for c in sourcecharges),
            'actual_retrieval_calls':sum(r.get('retrieval_calls',0) for r in targets),
            'unused_retrieval_opportunities':48-sum(r.get('retrieval_calls',0) for r in targets),
            'retrieval_cost_unknown':any(r.get('retrieval_calls',0)>0 for r in targets),
            'actual_docker_attempts':dockercalls,'actual_scorer_calls':scorercalls,
            'unused_builder_opportunities':2-buildercalls,'unused_docker_opportunities':16-dockercalls,'unused_scorer_opportunities':16-scorercalls,
            'unused_model_opportunities':None if type(ledger) is PhaseProviderAbort else 34-(final_usage['main_opportunities'] if native else len(model.ledger['calls'])),'unused_source_opportunities':68-sourcecalls,
            'structural_exclusions':excluded,'pruned_cells':[],'contrasts':[c.data() for c in contrasts],
            'history_acquisition':{'model_requests':len(plan.history.binding.data()['request_digests']),'cost':'inherited_unknown_not_in_current_allocation'},
            **({'provider_provenance_failed':type(ledger) is PhaseProviderAbort,
                'provider_final_score_eligible':provider_eligible,'eligible_scored_cells':len(scores) if provider_eligible else 0,
                'provider_abort_digest':ledger.record.content_hash if type(ledger) is PhaseProviderAbort else None} if native else {}),
            'validation_opened':False,'scientific_effectiveness_proven':False,'scorer_usage_unknown':bool(scorercalls),
            'status':'complete_train_engineering' if provider_eligible and len(scores)==16 and all(c.data()['status'] in {'estimated','not_identifiable'} for c in contrasts) else 'inconclusive'})
        _exclusive(root/'controller-receipt.json',receipt);journal['status']=receipt.data()['status'];persist(final_usage)
        return LineageRetrievalImprovementRun(root,barrier,panels,scenarios,tuple(results),tuple(scores),tuple(FrozenRecord.from_dict(r) for r in targets),tuple(builds),ledger,receipt)
    finally:
        if native:
            for service in services.values():
                if type(service) is CombinationScorerProcessClient:service.close()
