"""Prospective C4: reserve all work, build history candidates, seal, solve, seal, score.

The controller has no validation or live model credential surface. Model ports
and independent scorer processes are injected, and their original ledgers are
part of the replay boundary. Synthetic completion is engineering evidence only.
"""
from dataclasses import dataclass
from pathlib import Path
import json
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.full_loo_composition import FrozenFullLooPlan, candidate_build_key
from research_loop.modular.full_loo_panel import FullLooPanel, OBLIGATION, runtime_arm
from research_loop.modular.full_loo_modules import model_schemas
from research_loop.modular.full_loo_driver import run_stage, verify_stage, files
from research_loop.modular.metaprogram_training import FrozenTrainHistory, _path, _sha, _exclusive, _read_record, _Journal, _phase_rows, _atomic, model_configuration, _builder
from research_loop.modular.modules.improvement import CandidatePackage, FrozenBuilderVersion, TrainingManifest
from research_loop.modular.state_improvement_build import FrozenProviderLedger, check_history
from research_loop.modular.state_retrieval_combination_driver import FrozenStateRetrievalMaterial
from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
from research_loop.modular.lineage_combination_material import DualMaterialVerifier, check_material_inputs
from research_loop.modular.exploration_scheduler_combination import FrozenExplorationSchedulerMaterial, check_inputs
from research_loop.modular.combination_train_source import CombinationTrainSource, packet_index
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.combination_train_controller import _usage
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig, FrozenBenchmarkRubricEndpoint
from evaluation.modular.combination_scoring import _score_input_payload, verify_combination_adapted_receipt
from research_loop.ontology import ContractError


@dataclass(frozen=True)
class FrozenFullLooRuntimePlan:
    record: FrozenRecord
    history: FrozenTrainHistory
    history_inputs: tuple

    def data(self): return self.record.data()
    @property
    def composition(self): return FrozenFullLooPlan(FrozenRecord.from_dict(self.data()['composition']))
    @property
    def parent(self): return CandidatePackage(FrozenRecord.from_dict(self.data()['parent']))
    @property
    def fixed_builder(self): return FrozenBuilderVersion(FrozenRecord.from_dict(self.data()['fixed_builder']))
    def material(self,task): return FrozenStateRetrievalMaterial(FrozenRecord.from_dict(self.data()['materials'][task]))
    def phase_material(self,task): return FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(self.data()['phase_materials'][task]))
    def objective(self,stage):
        return FrozenRecord.from_dict(self.history.binding.data()['lock']['objective'] if stage=='history_build' else self.data()['objective'])

    def __post_init__(self):
        b=self.data()
        required={'schema','composition','export_mode','stage','domain','item_ids','task_bindings','history_binding','history_inputs',
            'parent','fixed_builder','materials','phase_materials','source_verifier_binding','corpus_verifier_binding',
            'model_config','scorer','scorer_handle_bindings','objective','image','timeout_seconds'}
        if (type(self) is not FrozenFullLooRuntimePlan or set(b)!=required or b['schema']!='c4-full-loo-runtime-plan-v1'
                or b['domain']!='train' or b['export_mode']!='primary_prospective' or not b['stage']
                or type(self.history) is not FrozenTrainHistory or b['history_binding']!=self.history.binding.data()):
            raise ContractError('exact C4 prospective TRAIN runtime plan required')
        self.history.verify();c=self.composition.data();_builder(self.fixed_builder)
        if (c['cells'][0]['history_binding_digest']!=self.history.binding.content_hash or c['cells'][0]['builder_digest']!=self.fixed_builder.digest
                or set(TrainingManifest(FrozenRecord.from_dict(self.parent.record.data()['training_manifest'])).identities())!={self.history.task.identity}):
            raise ContractError('C4 candidate recipe must bind only the original fixed history')
        if not isinstance(self.history_inputs,tuple) or len(self.history_inputs)!=1 or self.history_inputs[0][0]!='public_csv':
            raise ContractError('one original history CSV required')
        raw=_path(self.history_inputs[0][1]).read_bytes()
        if b['history_inputs']!={'public_csv':{'sha256':_sha(raw),'byte_count':len(raw)}}:raise ContractError('original history input drift')
        if len(b['item_ids'])!=2 or len(set(b['item_ids']))!=2 or set(b['task_bindings'])!=set(b['item_ids']):raise ContractError('exact two TRAIN target tokens required')
        identities=[]
        for token,row in b['task_bindings'].items():
            if len(token)!=64 or set(row)!={'identity','task_digest','csv_sha256','csv_byte_count'}:raise ContractError('C4 target binding malformed')
            identity=DataIdentity.parse(row['identity']);identity.require_train();identities.append(identity)
            h=self.history.task.identity
            if (identity.benchmark,identity.task_id,identity.group_id)==(h.benchmark,h.task_id,h.group_id):raise ContractError('history overlaps target')
        tasks={r['task_digest'] for r in b['task_bindings'].values()};alltasks=tasks|{self.history.task.content_hash}
        if tasks!=set(c['train_task_digests']) or {i.benchmark for i in identities}!={'blade','discoverybench'} or len({i.split_id for i in identities})!=1:
            raise ContractError('C4 exact primary TRAIN target inventory required')
        if set(b['materials'])!=alltasks or set(b['phase_materials'])!=alltasks:raise ContractError('C4 material inventory differs')
        budgets=set()
        for digest in alltasks:
            m=self.material(digest);p=self.phase_material(digest);s=m.state()
            if type(s) is not FrozenAdmissionMaterial or s.data()['task_digest']!=digest or any(p.data()[k]!=s.data()[k] for k in ('identity','task_digest','public_artifacts','context_budget_bytes')):
                raise ContractError('C4 material/auxiliary public subject mismatch')
            budgets.add(s.data()['context_budget_bytes'])
        if budgets!={c['cells'][0]['history_input_budget']}:raise ContractError('C4 matched context allocation drift')
        config=b['model_config']
        if (config['max_calls']!=c['allocation']['model_calls'] or config['schemas']!=model_schemas() or config['model']!='gpt-5.6-luna'
                or config['effort']!='low' or config['max_tokens']<1):raise ContractError('C4 frozen actual model opportunity allocation differs')
        scorer=ScorerConfig(FrozenRecord.from_dict(b['scorer']))
        if scorer.record.data()['rubric_digest']!=FrozenBenchmarkRubricEndpoint.rubric_digest() or set(b['scorer_handle_bindings'])!={FrozenRecord.from_dict(i.data()).content_hash for i in identities}:
            raise ContractError('C4 scorer or handle inventory drift')
        if not isinstance(b['objective'],dict) or not b['objective']:raise ContractError('C4 frozen target objective required')
        for identity in identities:ExecutionRequest(identity,b['image'],Path('planned.py'),{'public_csv':Path('planned.csv')},b['timeout_seconds'])

    def check_packets(self,packets):
        self.__post_init__();indexed=packet_index(self.data(),packets)
        for token,p in indexed.items():
            r=self.data()['task_bindings'][token]
            if r!={'identity':p.task.identity.data(),'task_digest':p.task.content_hash,'csv_sha256':_sha(p.csv_path.read_bytes()),'csv_byte_count':p.csv_path.stat().st_size}:
                raise ContractError('C4 original target export drift')


def recipes(plan):
    result={}
    for row in plan.composition.data()['cells']:
        if row['status']=='executable':result.setdefault(candidate_build_key(row),row)
    return tuple(result.values())


@dataclass(frozen=True)
class FullLooBarrier:
    root: Path
    record: FrozenRecord
    plan: FrozenFullLooRuntimePlan
    builds: tuple
    ledger: FrozenProviderLedger
    source_verifier: object
    corpus_verifier: object
    broker: object
    packets: tuple

    def package(self,recipe):
        match=next(r for r in self.builds if candidate_build_key(r.record.data()['recipe'])==candidate_build_key(recipe))
        return CandidatePackage(_read_record(match.root/'candidate.json'))

    def verify(self):
        if type(self) is not FullLooBarrier or len(self.builds)!=len(recipes(self.plan)):raise ContractError('complete original C4 candidate barrier required')
        self.plan.check_packets(self.packets);self.ledger.verify()
        if _read_record(self.root/'plan.json')!=self.plan.record or _read_record(self.root/'candidate-barrier.json')!=self.record:
            raise ContractError('original C4 plan/barrier replaced')
        expected={'schema':'c4-candidate-barrier-v1','plan_digest':self.plan.record.content_hash,
            'build_receipts':[r.record.content_hash for r in self.builds],'provider_ledger_digest':self.ledger.record.content_hash,
            'candidate_selections':{r['id']:self.package(r).digest for r in self.plan.composition.data()['cells'] if r['status']=='executable'}}
        if self.record.data()!=expected:raise ContractError('C4 barrier candidate sharing drift')
        events=_phase_rows(self.root/'controller.jsonl')
        prefix=[('phase_lock',{'plan_digest':self.plan.record.content_hash,'allocation':self.plan.composition.data()['allocation']})]
        for recipe,r in zip(recipes(self.plan),self.builds,strict=True):
            prefix.extend([('build_reserved',{'recipe':recipe}),('build_completed',{'digest':r.record.content_hash,'status':'succeeded'})])
        prefix.append(('build_ledger_sealed',{'digest':self.ledger.record.content_hash}))
        if [(e['stage'],e['data']) for e in events[:len(prefix)]]!=prefix:raise ContractError('C4 builds must precede all target work')
        suffix=events[len(prefix):]
        if suffix and (suffix[0]['stage']!='candidate_barrier' or suffix[0]['data']!={'digest':self.record.content_hash}):
            raise ContractError('C4 target work precedes candidate barrier')
        planned=[(r['id'],p.task.content_hash) for r in self.plan.composition.data()['cells'] if r['status']=='executable' for p in self.packets]
        reserved=[];active=None;sealed=False;scorer=None;scored=set();completed={}
        for e in suffix[1:]:
            d=e['data'];stage=e['stage']
            if stage in {'target_reserved','target_blocked'}:
                key=(d['arm_id'],d['task_digest'])
                if sealed or active is not None or len(reserved)>=len(planned) or key!=planned[len(reserved)]:raise ContractError('C4 target reservation order drift')
                reserved.append(key)
                if stage=='target_reserved':active=key
            elif stage=='target_completed':
                if active!=(d['arm_id'],d['task_digest']) or d['status'] not in {'succeeded','failed'}:raise ContractError('C4 unmatched target completion')
                completed[active]=d;active=None
            elif stage=='target_ledger_sealed':
                if sealed or active is not None or len(reserved)!=22:raise ContractError('C4 premature target provider seal')
                sealed=True
            elif stage=='scorer_reserved':
                key=(d['arm_id'],d['task_digest'])
                if not sealed or scorer is not None or key in scored or completed.get(key,{}).get('status')!='succeeded':raise ContractError('C4 scorer before all targets sealed')
                scored.add(key);scorer=key
            elif stage=='scorer_completed':
                if scorer!=(d['arm_id'],d['task_digest']):raise ContractError('C4 unmatched scorer completion')
                scorer=None
            else:raise ContractError('unknown C4 controller side effect')
        for r,recipe in zip(self.builds,recipes(self.plan),strict=True):
            verify_stage(r,plan=self.plan,recipe=recipe,stage='history_build',task=self.plan.history.task,package=self.plan.parent,
                material=self.plan.material(self.plan.history.task.content_hash),phase_material=self.plan.phase_material(self.plan.history.task.content_hash),
                source_verifier=self.source_verifier,corpus_verifier=self.corpus_verifier,broker=self.broker,inputs=dict(self.plan.history_inputs),ledger=self.ledger)


def compile_panel(barrier):
    plan=barrier.plan;b=plan.data();scenarios={};cells=[]
    packages=barrier.record.data()['candidate_selections'];recipes_by_id={r['id']:r for r in plan.composition.data()['cells'] if r['status']=='executable'}
    for recipe in recipes_by_id.values():
        for p in barrier.packets:
            scenario=FrozenRecord.from_dict({'schema':'c4-target-scenario-v1','plan_digest':plan.record.content_hash,'barrier_digest':barrier.record.content_hash,
                'task_digest':p.task.content_hash,'material_digest':plan.material(p.task.content_hash).record.content_hash,
                'phase_material_digest':plan.phase_material(p.task.content_hash).record.content_hash})
            c=PanelCell(OBLIGATION,p.task.identity,'r1','combination',recipe['id'],runtime_arm(plan.composition,recipe),p.task.content_hash,
                scenario.content_hash,packages[recipe['id']],ScorerConfig(FrozenRecord.from_dict(b['scorer'])).digest)
            cells.append(c);scenarios[c.key]=scenario
    panel=FullLooPanel(b['stage'],'train',barrier.packets[0].task.identity.split_id,OBLIGATION,'joint_bundle',plan.composition.record,
        FrozenRecord.from_dict({'schema':'c4-procedure-package-bundle-v1','packages':{k:barrier.package(r).record.data() for k,r in recipes_by_id.items()}}),
        FrozenRecord.from_dict({'engineering_only':True,'confidence_interval':None,'unrestricted_interactions':'not_identified'}),tuple(cells),
        training_provenance=FrozenRecord.from_dict({'schema':'c4-history-build-exposure-v1','history_identity':plan.history.task.identity.data(),
            'history_binding_digest':plan.history.binding.content_hash,'barrier_digest':barrier.record.content_hash,
            'outer_plan_digest':plan.record.content_hash,'candidate_selections':packages}))
    return panel,scenarios


def verify_full_loo_cell(result, *, barrier, panel, ledger):
    if type(panel) is not FullLooPanel:raise ContractError('exact C4 scorer panel required')
    barrier.verify();expected,scenarios=compile_panel(barrier)
    if panel!=expected or result.cell not in panel.cells:raise ContractError('C4 target panel drift')
    recipe=next(r for r in barrier.plan.composition.data()['cells'] if r['id']==result.cell.arm_id)
    p=next(p for p in barrier.packets if p.task.content_hash==result.cell.task_digest)
    events=_phase_rows(barrier.root/'controller.jsonl')
    if [e['data'] for e in events if e['stage']=='target_ledger_sealed']!=[{'digest':ledger.record.content_hash}] or ledger.path!=barrier.root/'target-provider-ledger.json':
        raise ContractError('C4 scorer requires original target ledger seal')
    matches=[e['data'] for e in events if e['stage']=='target_completed' and e['data']['arm_id']==recipe['id'] and e['data']['task_digest']==p.task.content_hash]
    if len(matches)!=1 or matches[0]['digest']!=result.record.content_hash:raise ContractError('C4 result differs from sealed controller completion')
    return verify_stage(result,plan=barrier.plan,recipe=recipe,stage='target',task=p.task,package=barrier.package(recipe),
        material=barrier.plan.material(p.task.content_hash),phase_material=barrier.plan.phase_material(p.task.content_hash),
        source_verifier=barrier.source_verifier,corpus_verifier=barrier.corpus_verifier,broker=barrier.broker,inputs={'public_csv':p.csv_path},ledger=ledger)


@dataclass(frozen=True)
class FullLooRun:
    root: Path
    barrier: FullLooBarrier | None
    panel: FullLooPanel | None
    builds: tuple
    results: tuple
    ledger: FrozenProviderLedger
    scores: tuple
    receipt: FrozenRecord


def run_full_loo_train(plan, *, prospective_exporter, snapshot_root, export_root, run_root, model, audit_verifier,
                       source_verifier, corpus_verifier, provider, scorer_factory, execution_authority, scorer_authority_keys):
    if type(plan) is not FrozenFullLooRuntimePlan:raise ContractError('exact C4 runtime plan required')
    plan.__post_init__();b=plan.data();allocation=plan.composition.data()['allocation']
    if model_configuration(model).data()!=b['model_config'] or model.ledger['calls'] or model.ledger['usage_incomplete']:raise ContractError('fresh C4 matched model port required')
    if type(source_verifier) is not AdmissionMaterialVerifier or type(corpus_verifier) is not DualMaterialVerifier:raise ContractError('C4 exact independent state and corpus verification required')
    for verifier,key in [(source_verifier,'source_verifier_binding'),(corpus_verifier,'corpus_verifier_binding')]:
        if verifier.binding().data()!=b[key]:raise ContractError('C4 source authority drift')
        if any(a.authority.key in {execution_authority.key,*scorer_authority_keys.values()} for a in verifier.authorities):raise ContractError('source/scorer authority overlap')
    root=_path(run_root,exists=False);root.mkdir(parents=True,exist_ok=False)
    _exclusive(root/'plan.json',plan.record);journal=_Journal(root/'controller.jsonl')
    journal.append('phase_lock',{'plan_digest':plan.record.content_hash,'allocation':allocation})
    armrows=[r for r in plan.composition.data()['cells'] if r['status']=='executable']
    builds=[];results=[];scores=[];barrier=panel=None;service=None;poison=False
    rows=[{'arm_id':r['id'],'task_digest':t,'status':'not_started','scorer_calls':0} for r in armrows for t in plan.composition.data()['train_task_digests']]
    buildrows=[{'recipe':r,'status':'not_started'} for r in recipes(plan)]
    structural=[{'arm_id':r['id'],'task_digest':t,'status':r['status'],'reason':r['reason']} for r in plan.composition.data()['cells'] if r['status']!='executable' for t in plan.composition.data()['train_task_digests']]
    def persist():_atomic(root/'attempts.json',{'builds':buildrows,'targets':rows,'structural':structural,'model_usage':_usage(model)})
    persist()
    source=CombinationTrainSource(b,custody=None,prospective_exporter=prospective_exporter,snapshot=_path(snapshot_root,exists=False),exported=_path(export_root,exists=False))
    try:
        packets=tuple(source.export());plan.check_packets(packets)
        packets=tuple(next(p for p in packets if p.task.content_hash==d) for d in plan.composition.data()['train_task_digests'])
        broker=DockerExecutionBroker([root,Path(export_root),plan.history_inputs[0][1].parent])
        check_history(plan.history,plan.material(plan.history.task.content_hash).state(),broker,dict(plan.history_inputs))
    except Exception as exc:
        for row in [*buildrows,*rows]:row.update(status='blocked',reason='source_preflight: '+str(exc))
        persist();raise
    def unknown(result):
        for name in ('source/source.json','corpus/source.json'):
            if (result.root/name).exists() and any(c.get('cost_unknown',True) for c in json.loads((result.root/name).read_bytes()).get('calls',[])):return True
        if result.phase is not None and result.phase.data()['unknown_cost_attempts']:return True
        return model.ledger['usage_incomplete']
    for i,row in enumerate(buildrows):
        recipe=row['recipe']
        if poison:row.update(status='blocked',reason='prior_unknown_cost');persist();continue
        journal.append('build_reserved',{'recipe':recipe});persist()
        cell=PanelCell(OBLIGATION,plan.history.task.identity,'r1','combination',recipe['id'],runtime_arm(plan.composition,recipe,'history_build'),
            plan.history.task.content_hash,plan.record.content_hash,plan.parent.digest,ScorerConfig(FrozenRecord.from_dict(b['scorer'])).digest)
        r=run_stage(plan=plan,recipe=recipe,stage='history_build',cell=cell,task=plan.history.task,package=plan.parent,
            material=plan.material(plan.history.task.content_hash),phase_material=plan.phase_material(plan.history.task.content_hash),
            source_verifier=source_verifier,corpus_verifier=corpus_verifier,provider=provider,broker=broker,inputs=dict(plan.history_inputs),model=model,audit_verifier=audit_verifier,root=root/'builds'/str(i))
        builds.append(r);row.update(status=r.record.data()['status'],reason=r.record.data()['reason']);poison=poison or unknown(r)
        journal.append('build_completed',{'digest':r.record.content_hash,'status':row['status']});persist()
    buildledger=FrozenProviderLedger.freeze(model,root/'build-provider-ledger.json');journal.append('build_ledger_sealed',{'digest':buildledger.record.content_hash})
    if len(builds)==len(buildrows) and all(r.record.data()['status']=='succeeded' for r in builds):
        packages={r['id']:CandidatePackage(_read_record(next(x.root for x in builds if candidate_build_key(x.record.data()['recipe'])==candidate_build_key(r))/'candidate.json')).digest for r in armrows}
        record=FrozenRecord.from_dict({'schema':'c4-candidate-barrier-v1','plan_digest':plan.record.content_hash,'build_receipts':[r.record.content_hash for r in builds],
            'provider_ledger_digest':buildledger.record.content_hash,'candidate_selections':packages})
        _exclusive(root/'candidate-barrier.json',record)
        barrier=FullLooBarrier(root,record,plan,tuple(builds),buildledger,source_verifier,corpus_verifier,broker,packets)
        try:
            barrier.verify();panel,_=compile_panel(barrier);journal.append('candidate_barrier',{'digest':record.content_hash})
        except Exception as exc:poison=True;_exclusive(root/'barrier-failure.json',FrozenRecord.from_dict({'error':str(exc)}))
    else:poison=True
    for row in rows:
        key={'arm_id':row['arm_id'],'task_digest':row['task_digest']}
        if poison or panel is None:
            row.update(status='blocked',reason='candidate_barrier_or_unknown_cost');journal.append('target_blocked',key);results.append(None);persist();continue
        recipe=next(r for r in armrows if r['id']==row['arm_id']);p=next(p for p in packets if p.task.content_hash==row['task_digest']);cell=next(c for c in panel.cells if c.arm_id==row['arm_id'] and c.task_digest==p.task.content_hash)
        journal.append('target_reserved',key)
        r=run_stage(plan=plan,recipe=recipe,stage='target',cell=cell,task=p.task,package=barrier.package(recipe),material=plan.material(p.task.content_hash),
            phase_material=plan.phase_material(p.task.content_hash),source_verifier=source_verifier,corpus_verifier=corpus_verifier,provider=provider,
            broker=broker,inputs={'public_csv':p.csv_path},model=model,audit_verifier=audit_verifier,root=root/'targets'/FrozenRecord.from_dict(cell.data()).content_hash)
        results.append(r);row.update(status=r.record.data()['status'],reason=r.record.data()['reason']);poison=poison or unknown(r)
        journal.append('target_completed',{**key,'digest':r.record.content_hash,'status':row['status']});persist()
    ledger=FrozenProviderLedger.freeze(model,root/'target-provider-ledger.json');journal.append('target_ledger_sealed',{'digest':ledger.record.content_hash})
    if panel is not None and not poison:
        service=scorer_factory(panel)
        if type(service) is not CombinationScorerProcessClient or service.full_loo is not True or service.panel!=panel:raise ContractError('exact closed C4 independent process scorer required')
        service.assert_configuration(config=ScorerConfig(FrozenRecord.from_dict(b['scorer'])),task_handle_bindings=b['scorer_handle_bindings'],
            execution_authority_keys={execution_authority.authority_id:execution_authority.key},scorer_authority_keys=scorer_authority_keys)
    for row,r in zip(rows,results,strict=True):
        if r is None or row['status']!='succeeded' or service is None:continue
        key={'arm_id':row['arm_id'],'task_digest':row['task_digest']}
        try:
            verify_full_loo_cell(r,barrier=barrier,panel=panel,ledger=ledger)
            scoreinput=execution_authority.issue(_score_input_payload(panel,r).data())
            row['scorer_calls']=1;journal.append('scorer_reserved',{**key,'input_digest':scoreinput.content_hash})
            score=service.score_combination(panel=panel,cell=r.cell,score_input=scoreinput)
            verify_combination_adapted_receipt(score,authority_keys=scorer_authority_keys,config=service.config,panel=panel,cell=r.cell,
                score_input=scoreinput,execution_authority_keys={execution_authority.authority_id:execution_authority.key})
            scores.append(score);row.update(status='scored',score=score.receipt.data())
        except Exception as exc:row.update(status='failed',reason=type(exc).__name__+': '+str(exc))
        if row['scorer_calls']:journal.append('scorer_completed',{**key,'status':row['status']})
        persist()
    stages=[*builds,*[r for r in results if r is not None]]
    sourcecalls=[];corpuscalls=[];aux=solvercalls=retrievalcalls=buildercalls=0
    for r in stages:
        for filename,dest in [('source/source.json',sourcecalls),('corpus/source.json',corpuscalls)]:
            if (r.root/filename).exists():dest.extend(json.loads((r.root/filename).read_bytes())['calls'])
        events=[]
        if (r.root/'runtime/trace.jsonl').exists():events=[json.loads(line) for line in (r.root/'runtime/trace.jsonl').read_bytes().splitlines()]
        solvercalls+=sum(e['stage']=='execution_request' for e in events);retrievalcalls+=sum(e['stage']=='q8_retrieval_request' for e in events);buildercalls+=sum(e['stage']=='c4_builder_request' for e in events)
        if (r.root/'phase/events.jsonl').exists():aux+=sum(json.loads(line)['kind']=='start' for line in (r.root/'phase/events.jsonl').read_bytes().splitlines())
    contrasts=[]
    for recipe in armrows[1:]:
        pairs=[]
        for digest in plan.composition.data()['train_task_digests']:
            a=next(r for r in rows if r['arm_id']=='full' and r['task_digest']==digest);z=next(r for r in rows if r['arm_id']==recipe['id'] and r['task_digest']==digest)
            pairs.append({'task_digest':digest,'difference':a['score']['body']['metric']['value']-z['score']['body']['metric']['value'] if a['status']==z['status']=='scored' else None})
        contrasts.append({'contrast':'F-versus-'+recipe['id'],'changed_modules':[m for m,v in recipe['arm_bits'].items() if not v],
            'estimand':recipe.get('estimand',recipe['comparison']),'matched_model_budget':recipe['procedure']!='baseline_b0',
            'paired_rows':pairs,'confidence_interval':None,'unrestricted_interactions':'not_identified'})
    actual={'model_calls':len(model.ledger['calls']),'builder_executions':buildercalls,'independent_source_qualification_calls':len(sourcecalls),
        'corpus_qualification_calls':len(corpuscalls),'retrieval_requests':retrievalcalls,'auxiliary_docker_attempts':aux,'solver_docker_attempts':solvercalls,
        'docker_attempts':aux+solvercalls,'scorer_calls':sum(r['scorer_calls'] for r in rows)}
    receipt=FrozenRecord.from_dict({'schema':'c4-run-receipt-v1','plan_digest':plan.record.content_hash,'allocation':allocation,'actual':actual,
        'unused':{k:allocation[k]-v for k,v in actual.items()},'builds':buildrows,'targets':rows,'structural':structural,'contrasts':contrasts,
        'model_usage':_usage(model),'source_cost_unknown':any(c.get('cost_unknown',True) for c in sourcecalls+corpuscalls),
        'known_source_cost_units':sum(c.get('cost_units') or 0 for c in sourcecalls+corpuscalls),
        'candidate_activation':'none_offline_experiment','active_package_digest':plan.parent.digest,'validation_opened':False,'scientific_effectiveness_proven':False,
        'status':'complete_train_engineering' if len(scores)==22 else 'inconclusive'})
    _exclusive(root/'controller-receipt.json',receipt)
    return FullLooRun(root,barrier,panel,tuple(builds),tuple(results),ledger,tuple(scores),receipt)
