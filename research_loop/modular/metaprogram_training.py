"""Q6.3 train-only proposal -> restricted builder -> actual benchmark solve.

This separate phase never activates BuilderRegistry, creates a problem, calls a
scorer, or manufactures validation acceptance. Historical journals authenticate
structure against caller-frozen bytes, not provider or scientific truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from research_loop.modular.benchmark_solver import (run_benchmark_solve, verify_benchmark_solve_trace,
    _program_from, _candidate_from)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, ExecutionRequest, validate_artifact
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.model_port import CodexModelPort
from research_loop.modular.modules.improvement import (CandidatePackage, FrozenBuilderVersion, RestrictedBuilderPort,
    BuilderRunReceipt, TrainingManifest)
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier, RunSession, verify_trace
from research_loop.modular.train_controller import _reviewed_model_policy
from research_loop.ontology import ContractError, canonical, digest
from research_loop.modular.phase_provider import (PROVIDERS,PhaseProviderSession,PhaseProviderScope,PhaseProviderLedger,PhaseProviderAbort,
    provider_configuration,validate_configuration,call_accounting)


_ALLOCATION={'builder_proposals':1,'builder_executions':1,'analysis_program_calls':1,'docker_attempts':1,'final_answer_calls':1}
_MAX_TEXT=16000


def _sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()


def _digest(value, name):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ContractError(name+' must be a SHA256 digest')
    return value


def _path(path: Path, *, exists=True):
    if not isinstance(path,Path) or not path.is_absolute() or '..' in path.parts or DockerExecutionBroker._has_link_component(path):
        raise ContractError('phase paths must be absolute and exclude links')
    if any((a/'data'/'labels').exists() or (a.name=='labels' and a.parent.name=='data') for a in (path,*path.parents)):
        raise ContractError('phase paths cannot enter label-containing ancestors')
    if exists and not path.is_file(): raise ContractError('frozen source is not a regular file')
    return path


def _read_record(path):
    _path(path)
    return FrozenRecord(path.read_text(encoding='utf-8').strip())


def _events(path):
    _path(path)
    return [FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]


def _history_material(task, path, expected_sha256, source_notes):
    if not isinstance(task,PublicTask): raise ContractError('history needs its prepared public task')
    task.identity.require_train(); _path(path)
    if _sha(path.read_bytes())!=_digest(expected_sha256,'history full byte hash'):
        raise ContractError('frozen history byte hash drift')
    if not isinstance(source_notes,FrozenRecord): raise ContractError('history qualification notes must be frozen')
    # Notes never substitute for this real source journal or qualify its truth.
    verified=verify_benchmark_solve_trace(path,task).data(); rows=_events(path);lock=rows[0]['data']
    if (lock.get('schema')!='run-lock-v1' or lock.get('slots')!=['analysis_program','final_answer']
            or lock.get('execution_limit')!=1 or rows[0]['lock_digest']!=FrozenRecord.from_dict(lock).content_hash):
        raise ContractError('history must be an original bounded benchmark-solver lock')
    _digest(lock.get('package_digest'),'history package')
    objective=FrozenRecord.from_dict(lock['objective']); requests=[];responses=[];analysis=None;answer=None;execution=None
    response_contract_valid=True
    for row in rows:
        if row['stage']=='model_request':
            request=row['data']['request']
            if request.get('task')!=task.data() or request.get('objective')!=objective.data() or request.get('lock_digest')!=rows[0]['lock_digest']:
                raise ContractError('history model request is foreign to original task and lock')
            requests.append(FrozenRecord.from_dict(request).content_hash)
        elif row['stage']=='model_response':
            response=FrozenRecord.from_dict(row['data']['response']);responses.append(response.content_hash)
            if analysis is None:
                analysis=response
                try: _program_from(response)
                except ContractError:
                    if rows[-1]['stage']!='driver_failure' or row!=rows[-2]: raise
                    response_contract_valid=False
            else:
                answer=response
                try: _candidate_from(response,objective)
                except ContractError:
                    if rows[-1]['stage']!='driver_failure' or row!=rows[-2]: raise
                    response_contract_valid=False
        elif row['stage']=='execution_result':
            execution=ExecutionReceipt.parse(row['data']['receipt'])
            if analysis is None or not response_contract_valid or (execution.artifact is not None and execution.artifact.sha256!=_sha(
                    analysis.data()['program'].replace('\n',os.linesep).encode('utf-8'))):
                raise ContractError('history execution does not bind its actual model program')
    if rows[-1]['stage'] not in {'final_decision','model_failure','driver_failure','controller_failure','execution_terminal','execution_failure'}:
        raise ContractError('history is unfinished; it cannot optimize a running source')
    if rows[-1]['stage']=='final_decision' and answer is None:
        raise ContractError('history final lacks its original model response')
    def public_text(response,key):
        value=response.data().get(key) if response is not None else None
        return value if isinstance(value,str) and value.strip() and len(value.encode())<=_MAX_TEXT else None
    observations={'analysis':public_text(analysis,'analysis'),
        'conclusion':public_text(answer,'conclusion'),
        'response_contract_valid':response_contract_valid if responses else None,
        'execution_status':execution.status if execution else None,
        'stdout':execution.record.data().get('stdout','') if execution else None,
        'terminal':rows[-1]['stage']}
    if len(canonical(observations).encode())>64000: raise ContractError('history public observation budget exceeded')
    return FrozenRecord.from_dict({'schema':'q63-frozen-train-history-v1','sha256':expected_sha256,
        'trace_digest':verified['trace_digest'],'lock':lock,'task_digest':task.content_hash,
        'request_digests':requests,'response_digests':responses,'source_notes':source_notes.data(),
        'public':{'task':task.data(),'observations':observations},
        'qualification':'caller-frozen journal structure only; provider authenticity and scientific validity not established'})


@dataclass(frozen=True)
class FrozenTrainHistory:
    task: PublicTask
    trace_path: Path
    binding: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.binding,FrozenRecord): raise ContractError('history binding must be frozen')
        row=self.binding.data()
        actual=_history_material(self.task,self.trace_path,row.get('sha256'),FrozenRecord.from_dict(row.get('source_notes',{})))
        if actual!=self.binding: raise ContractError('history metadata is not the actual source binding')

    @classmethod
    def freeze(cls,task,trace_path,*,expected_sha256,source_notes=None):
        notes=source_notes if source_notes is not None else FrozenRecord.from_dict({'qualification':'unspecified caller history'})
        return cls(task,trace_path,_history_material(task,trace_path,expected_sha256,notes))

    def verify(self): self.__post_init__()


def _target_binding(task,inputs,objective):
    if not isinstance(task,PublicTask) or not isinstance(objective,FrozenRecord) or not objective.data():
        raise ContractError('target requires a public task and nonempty frozen objective')
    task.identity.require_train()
    if not inputs or len({name for name,_ in inputs})!=len(inputs): raise ContractError('target needs exact named inputs')
    artifacts={}
    for name,path in inputs:
        _path(path); artifact=validate_artifact(task.identity,name,path)
        artifacts[name]=artifact.record.data()
    return FrozenRecord.from_dict({'schema':'q63-frozen-train-target-v1','task_digest':task.content_hash,
        'identity':task.identity.data(),'objective':objective.data(),'input_artifacts':artifacts})


@dataclass(frozen=True)
class FrozenMetaTarget:
    task: PublicTask
    inputs: tuple[tuple[str,Path],...]
    objective: FrozenRecord
    binding: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.inputs,tuple) or any(not isinstance(p,tuple) or len(p)!=2 for p in self.inputs):
            raise ContractError('target input paths must be frozen tuples')
        if _target_binding(self.task,self.inputs,self.objective)!=self.binding: raise ContractError('target actual input drift')

    @property
    def public_inputs(self): return MappingProxyType(dict(self.inputs))

    @classmethod
    def freeze(cls,task,*,public_inputs,objective):
        if not isinstance(public_inputs,Mapping): raise ContractError('named public inputs required')
        inputs=tuple(sorted(public_inputs.items()))
        return cls(task,inputs,objective,_target_binding(task,inputs,objective))

    def verify(self): self.__post_init__()


def metaprogram_schemas():
    text={'type':'string'}
    proposal={'type':'object','properties':{'entrypoint':{'type':'string','enum':['emit_literal_change_v1']},
        'surface':{'type':'string','enum':['prompt','memory']},'key':{'type':'string','enum':['instructions','lesson']},'value':text},
        'required':['entrypoint','surface','key','value'],'additionalProperties':False}
    analysis={'type':'object','properties':{'analysis':text,'program':text},'required':['analysis','program'],'additionalProperties':False}
    final={'type':'object','properties':{'objective_digest':text,'outcome':{'type':'string','enum':['unknown']},
        'evidence_ids':{'type':'array','items':text},'conclusion':text,'programme_complete':{'type':'boolean'}},
        'required':['objective_digest','outcome','evidence_ids','conclusion','programme_complete'],'additionalProperties':False}
    return json.loads(canonical({'builder_proposal':proposal,'analysis_program':analysis,'final_answer':final}))


def model_configuration(model):
    if not isinstance(model,CodexModelPort): raise ContractError('the actual CodexModelPort is required')
    _reviewed_model_policy(model)
    return FrozenRecord.from_dict({'model':model.model,'effort':model.effort,'max_calls':model.max_calls,'max_tokens':model.max_tokens,
        'schemas':model.schemas,'context_policy_sha256':model.frozen_base_context.sha256})


def _builder(builder):
    if not isinstance(builder,FrozenBuilderVersion): raise ContractError('typed restricted builder required')
    source=builder.record.data()
    if (source['key']!={'prompt':'instructions','memory':'lesson'}[source['surface']]
            or not source['value'].strip() or len(source['value'].encode())>_MAX_TEXT):
        raise ContractError('builder must emit bounded consumed instructions or memory lesson')
    return builder


def _plan_material(targets,histories,parent,fixed_builder,baseline_digest,p0_control,image,model_config,timeout_seconds,
                   experiment_id='Q6.3',manual_builder=None,manual_source=None):
    if experiment_id not in {'Q6.2','Q6.3'}: raise ContractError('unsupported candidate training phase')
    variants=('fixed','train_proposed') if experiment_id=='Q6.3' else ('fixed','manual_train','automatic_train')
    if experiment_id=='Q6.2':
        _builder(manual_builder)
        if not isinstance(manual_source,FrozenRecord) or manual_source.data()!= {
                'history_bindings':[h.binding.content_hash for h in histories],
                'builder_digest':manual_builder.digest,'origin':'caller_frozen_manual_training'}:
            raise ContractError('manual training material must bind the complete history and builder')
    elif manual_builder is not None or manual_source is not None: raise ContractError('meta training has no manual intervention')
    if (not isinstance(targets,tuple) or not targets or any(not isinstance(t,FrozenMetaTarget) for t in targets)
            or len({t.task.content_hash for t in targets})!=len(targets)
            or {t.task.identity.benchmark for t in targets}!={'blade','discoverybench'}):
        raise ContractError('Q6.3 requires unique train targets from both registered benchmarks')
    if (not isinstance(histories,tuple) or not histories or len(histories)>128
            or any(not isinstance(h,FrozenTrainHistory) for h in histories)
            or len({h.binding.content_hash for h in histories})!=len(histories)
            or len({h.trace_path.resolve() for h in histories})!=len(histories)):
        raise ContractError('history must be a nonempty frozen whitelist without duplicates')
    if len(canonical([h.binding.data()['public'] for h in histories]).encode())>1048576:
        raise ContractError('frozen history public context budget exceeded')
    if not isinstance(parent,CandidatePackage) or not isinstance(p0_control,FrozenRecord): raise ContractError('frozen parent and control required')
    manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
    subjects={canonical(t.task.identity.data()) for t in targets}|{canonical(h.task.identity.data()) for h in histories}
    if {canonical(i.data()) for i in manifest.identities()}!=subjects: raise ContractError('parent manifest must cover exactly the frozen training subjects')
    _builder(fixed_builder);_digest(baseline_digest,'baseline')
    if type(timeout_seconds)is not int or not 1<=timeout_seconds<=60: raise ContractError('bounded integer Docker timeout required')
    for target in targets: ExecutionRequest(target.task.identity,image,Path('planned.py'),target.public_inputs,timeout_seconds)
    if not isinstance(model_config,FrozenRecord): raise ContractError('model configuration must be frozen')
    config=model_config.data()
    native=config.get('schema')=='public-train-provider-config-v1'
    if native:
        validate_configuration(model_config,schemas=metaprogram_schemas(),main_opportunities=len(targets)*len(variants)*6,exact=False)
    else:
        if (set(config)!={'model','effort','max_calls','max_tokens','schemas','context_policy_sha256'} or config['model']!='gpt-5.6-luna'
                or config['effort']!='low' or config['schemas']!=metaprogram_schemas()
                or type(config['max_calls'])is not int or config['max_calls']<len(targets)*len(variants)*6
                or type(config['max_tokens'])is not int or config['max_tokens']<1): raise ContractError('matched complete model budget and exact schemas required')
        _digest(config['context_policy_sha256'],'reviewed model policy')
    grid=obligation_grids((experiment_id,),baseline_digest=baseline_digest,p0_control=p0_control)[experiment_id]
    cells=[]
    for target in sorted(targets,key=lambda t:t.task.content_hash):
        for variant in variants:
            for arm_id,arm in executable_arms(grid).items():
                row={'task_digest':target.task.content_hash,'variant':variant,'arm_id':arm_id,'arm':arm.data(),'replicate':'r1'}
                cells.append({**row,'cell_id':digest(row)})
    extra={} if experiment_id=='Q6.3' else {'experiment_id':experiment_id,'manual_builder':manual_builder.record.data(),'manual_source':manual_source.data()}
    return FrozenRecord.from_dict({**extra,'schema':'q63-train-phase-plan-v2' if native else 'q63-train-phase-plan-v1','scope':'train_only_engineering','cells':cells,
        'targets':[t.binding.data() for t in targets],'histories':[h.binding.data() for h in histories],
        'parent_package':parent.record.data(),'fixed_builder':fixed_builder.record.data(),'baseline_digest':baseline_digest,
        'p0_control':p0_control.data(),'arm_grid':grid.data(),'image':image,'timeout_seconds':timeout_seconds,
        'model_config':config,'allocation_per_cell':_ALLOCATION,'builder_search_cost':1,
        'scientific_effect':'not_measured','history_acquisition_cost':'inherited; not measurable from runtime journal alone'})


@dataclass(frozen=True)
class FrozenMetaTrainingPlan:
    record: FrozenRecord
    targets: tuple[FrozenMetaTarget,...]
    histories: tuple[FrozenTrainHistory,...]
    parent: CandidatePackage
    fixed_builder: FrozenBuilderVersion
    experiment_id: str = 'Q6.3'
    manual_builder: FrozenBuilderVersion | None = None
    manual_source: FrozenRecord | None = None

    def __post_init__(self):
        if not isinstance(self.record,FrozenRecord): raise ContractError('phase plan must be immutable')
        r=self.record.data()
        try:
            actual=_plan_material(self.targets,self.histories,self.parent,self.fixed_builder,r['baseline_digest'],
                FrozenRecord.from_dict(r['p0_control']),r['image'],FrozenRecord.from_dict(r['model_config']),r['timeout_seconds'],
                self.experiment_id,self.manual_builder,self.manual_source)
        except (KeyError,TypeError,AttributeError) as exc: raise ContractError('phase plan is not a closed typed reconstruction') from exc
        if actual!=self.record: raise ContractError('phase plan drifted from its frozen subjects')

    @classmethod
    def freeze(cls,*,targets,histories,parent,fixed_builder,baseline_digest,p0_control,image,model_config,timeout_seconds=20,
               experiment_id='Q6.3',manual_builder=None,manual_source=None):
        targets=tuple(targets);histories=tuple(histories)
        for item in (*targets,*histories): item.verify()
        return cls(_plan_material(targets,histories,parent,fixed_builder,baseline_digest,p0_control,image,model_config,timeout_seconds,
                   experiment_id,manual_builder,manual_source),targets,histories,parent,fixed_builder,experiment_id,manual_builder,manual_source)

    def verify_sources(self):
        self.__post_init__()
        for item in (*self.targets,*self.histories): item.verify()

    def selected_builder(self,proposed,cell):
        if 'M9' not in cell['arm']['enabled']: return self.fixed_builder
        if self.experiment_id=='Q6.2' and cell['variant']=='manual_train': return self.manual_builder
        if cell['variant'] in {'train_proposed','automatic_train'}: return proposed
        return self.fixed_builder

    def execution_material(self,candidate,cell,root,phase,*,replay=False):
        """Default generated package consumed by the actual successor solver."""
        return candidate,_projection(candidate)


def _exclusive(path,record):
    _path(path,exists=False)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(record.encoded+'\n');stream.flush();os.fsync(stream.fileno())


def _atomic(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(canonical(value),encoding='utf-8');os.replace(temporary,path)


class _Journal:
    def __init__(self,path): self.path=path;self.rows=[]
    def append(self,stage,data):
        record=FrozenRecord.from_dict({'sequence':len(self.rows),'previous':self.rows[-1].content_hash if self.rows else None,'stage':stage,'data':data})
        with self.path.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(record.encoded+'\n');stream.flush();os.fsync(stream.fileno())
        self.rows.append(record)


def _phase_rows(path):
    rows=_events(path);prior=None
    for index,row in enumerate(rows):
        if set(row)!={'sequence','previous','stage','data'} or row['sequence']!=index or row['previous']!=prior:
            raise ContractError('phase journal chain drift')
        prior=FrozenRecord.from_dict(row).content_hash
    if not rows or rows[0]['stage']!='phase_lock': raise ContractError('phase lock missing')
    return rows


def _proof(path):
    _path(path)
    return {'path':str(path.name),'sha256':_sha(path.read_bytes()),'tail':FrozenRecord(path.read_text(encoding='utf-8').splitlines()[-1]).content_hash}


def _safe_call(row):
    return {key:row.get(key) for key in ('id','slot','request_hash','status','usage','output_hash','error_type')}


def _actual(rows,solver_rows=()):
    charges=[e['data'] for e in rows if e['stage']=='model_charge']
    calls=[c for charge in charges for c in charge['provider_calls']]
    return {'model_requests':len([e for e in rows if e['stage']=='model_reservation']),
        'provider_calls':len(calls),'reported_tokens':sum(c['usage']['total_tokens'] for c in calls if c['usage'] is not None),
        'unknown_cost':any(c['usage'] is None for c in calls),
        'provider_usage_incomplete':any(c['status']!='succeeded' for c in calls),
        'builder_attempts':sum(e['stage']=='builder_request' for e in rows),
        'docker_attempts':sum(e['stage']=='execution_request' for e in solver_rows)}


def _total(cells):
    counts={key:0 for key in ('model_requests','provider_calls','reported_tokens','builder_attempts','docker_attempts')}
    counts.update(unknown_cost=False,provider_usage_incomplete=False)
    for cell in cells:
        actual=cell.record.data()['actual']
        for key in counts:
            counts[key]=(counts[key] or actual[key]) if type(counts[key])is bool else counts[key]+actual[key]
    return counts



def _phase_actual(rows,solver_rows=(),*,native=False):
    if not native:return _actual(rows,solver_rows)
    calls=[c for row in rows if row['stage']=='model_charge' for c in row['data']['provider_calls']]
    return {**call_accounting(calls),
        'model_requests':sum(r['stage']=='model_reservation' for r in rows),
        'builder_attempts':sum(r['stage']=='builder_request' for r in rows),
        'docker_attempts':sum(r['stage']=='execution_request' for r in solver_rows)}


def _phase_total(cells):
    if not cells or cells[0].record.data()['schema']=='q63-training-cell-receipt-v1':return _total(cells)
    rows=[c.record.data()['actual'] for c in cells]
    scopes={r['known_usage_scope'] for r in rows if r['known_usage_scope'] is not None}
    if len(scopes)>1:raise ContractError('phase mixed provider accounting scopes')
    keys=('provider_calls','known_reported_tokens','unknown_main_opportunities','unsuccessful_opportunities',
        'possible_initial_title_opportunities','model_requests','builder_attempts','docker_attempts')
    return {'schema':'train-phase-call-accounting-v2',**{k:sum(r[k] for r in rows) for k in keys},
        'known_usage_scope':next(iter(scopes),None),'title_tokens':None,'all_opportunity_tokens':None,
        'settled_additional_charge_usd':None}


def _phase_ledger(result,expected):
    ledger=result.provider_ledger
    if (type(ledger) is not PhaseProviderLedger or result.model_ledger_path!=ledger.path
            or ledger.original.record.data()['configuration']!=expected):
        raise ContractError('original typed phase provider seal/configuration differs')
    ledger.verify();return ledger


def _ledger_ids(ledger):
    return ([c['view']['id'] for c in ledger.original.record.data()['calls']]
        if type(ledger) is PhaseProviderLedger else [c['id'] for c in ledger['calls']])


def _aborted_phase_record(plan,root,cells,abort,*,operation=False):
    """Keep all planned rows without claiming a replay-valid failed suffix."""
    if type(abort) is not PhaseProviderAbort:raise ContractError('typed terminal phase accounting required')
    abort.verify();body=plan.record.data();config=body['common']['model_config'] if operation else body['model_config']
    if abort.record.data()['completed_scope_prefix']['configuration_digest']!=FrozenRecord.from_dict(config).content_hash:
        raise ContractError('terminal phase belongs to another provider allocation')
    declared=body['cells'];ids=[c['cell_id'] for c in declared]
    actual={c.record.data()['cell_id']:c for c in cells}
    if len(actual)!=len(cells) or list(actual)!=ids[:len(cells)]:raise ContractError('aborted phase observed prefix differs')
    attempts=[]
    for cell in declared:
        path=root/'cells'/cell['cell_id'];observed=actual.get(cell['cell_id'])
        if observed is not None and observed.root!=path:raise ContractError('aborted cell source path differs')
        files={str(p.relative_to(path)).replace('\\','/'):_sha(_path(p).read_bytes())
            for p in path.rglob('*') if p.is_file()} if path.exists() else {}
        if observed is not None and _read_record(path/'cell-receipt.json')!=observed.record:
            raise ContractError('aborted original cell receipt differs')
        attempts.append({'cell':cell,'status':'executed_unverified' if observed is not None
            else 'interrupted' if path.exists() else 'blocked','reason':'provider_provenance_fault',
            'original_cell_receipt_digest':observed.record.content_hash if observed else None,'files':files})
    schema='train-operation-aborted-phase-receipt-v2' if operation else 'q63-training-aborted-phase-receipt-v2'
    return FrozenRecord.from_dict({'schema':schema,'plan_digest':plan.record.content_hash,'status':'engineering_incomplete',
        'expected_cells':len(declared),'observed_cell_receipts':len(cells),'attempts':attempts,
        'allocation':body['budget'] if operation else {'cells':len(declared),'per_cell':_ALLOCATION,'model_calls':len(declared)*3},
        'provider_snapshot':abort.snapshot.data(),'provider_abort_digest':abort.record.content_hash,
        'provisional_phase_receipt':_proof(root/'provisional-phase-receipt.json') if (root/'provisional-phase-receipt.json').exists() else None,
        'exact_unused_main_opportunities':None,'current_originals_verified':False,'provider_scope_partition_complete':False,
        'scientific_effect':'not_measured','builder_activation':'not_performed','production_promotion':'not_authorized',
        'scoring':'not_configured','accounting_status':'historical_lower_bounds_only'})


def _finish_aborted_phase(plan,root,cells,abort,*,operation=False):
    record=_aborted_phase_record(plan,root,cells,abort,operation=operation)
    _exclusive(root/('receipt.json' if operation else 'training-receipt.json'),record)
    return MetaTrainingRun(root,abort.path,tuple(cells),record,abort)


def _close_native_phase(result,plan,scopes,verify,*,operation=False):
    """Retain a provisional receipt if final replay discovers original drift."""
    try:
        verify(result)
        result.provider_ledger.verify()
        return result
    except ContractError:
        scopes.abort()  # Unrelated errors have no durable provider snapshot.
    original=result.root/('receipt.json' if operation else 'training-receipt.json')
    raw=original.read_bytes()
    with (result.root/'provisional-phase-receipt.json').open('xb') as stream:stream.write(raw)
    abort=scopes.finish(result.root/'final-provider-abort.json')
    record=_aborted_phase_record(plan,result.root,result.cells,abort,operation=operation)
    _atomic(original,record.data())
    closed=MetaTrainingRun(result.root,abort.path,result.cells,record,abort)
    _verify_aborted_phase(closed,plan,operation=operation)
    attempt=result.root/('attempt.json' if operation else 'training-attempt.json')
    _atomic(attempt,{'plan_digest':plan.record.content_hash,'status':'provider_provenance_failed','attempts':record.data()['attempts']})
    return closed


def _verify_aborted_phase(result,plan,*,operation=False):
    if _read_record(result.root/'plan.json')!=plan.record:raise ContractError('aborted phase plan differs')
    if _read_record(result.root/('receipt.json' if operation else 'training-receipt.json'))!=result.receipt:
        raise ContractError('aborted phase receipt differs')
    if result.model_ledger_path!=result.provider_ledger.path:raise ContractError('aborted phase ledger path differs')
    expected=_aborted_phase_record(plan,result.root,result.cells,result.provider_ledger,operation=operation)
    if result.receipt!=expected:raise ContractError('terminal phase denominator or retained evidence differs')
    return FrozenRecord.from_dict({'schema':'train-phase-abort-verification-v2','status':'terminal_accounting_only',
        'expected_cells':expected.data()['expected_cells'],'observed_cell_receipts':len(result.cells),
        'engineering_verified':False,'current_originals_verified':False,'score_eligible':False,
        'scientific_effect':'not_measured','builder_activation':'not_performed','production_promotion':'not_authorized'})

def _projection(candidate):
    changes=candidate.record.data()['changes']
    if len(changes)!=1: raise ContractError('generated package has an unsupported public change set')
    surface=next(iter(changes));key={'prompt':'instructions','memory':'lesson'}.get(surface)
    if key is None or set(changes[surface])!={key}: raise ContractError('generated package changes are not consumed by this phase')
    value=changes[surface][key]
    if not isinstance(value,str) or not value.strip() or len(value.encode())>_MAX_TEXT:
        raise ContractError('generated public change is unbounded')
    return FrozenRecord.from_dict({'schema':'q63-public-candidate-context-v1',
        'instructions':value if surface=='prompt' else None,'memory_lesson':value if surface=='memory' else None,
        'binding':candidate.digest})


def _checked_build(candidate,receipt,builder,parent):
    source=builder.record.data();manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
    if not isinstance(candidate,CandidatePackage) or not isinstance(receipt,BuilderRunReceipt):
        raise ContractError('restricted builder returned untyped artifacts')
    expected=CandidatePackage.create(parent_digest=parent.digest,manifest=manifest,
        changes={source['surface']:{source['key']:source['value']}},search_cost=1)
    data=receipt.record.data()
    if (candidate!=expected or data!={'builder_digest':builder.digest,'builder_source':source,'builder_entrypoint':builder.entrypoint,
            'parent_package_digest':parent.digest,'training_manifest_digest':manifest.content_hash,
            'output_candidate_digest':candidate.digest,'search_cost':1}):
        raise ContractError('actual builder output does not bind its DSL and training subjects')
    return _projection(candidate)


@dataclass(frozen=True)
class MetaTrainingCell:
    root: Path
    record: FrozenRecord


@dataclass(frozen=True)
class MetaTrainingRun:
    root: Path
    model_ledger_path: Path
    cells: tuple[MetaTrainingCell,...]
    receipt: FrozenRecord
    provider_ledger: PhaseProviderLedger | PhaseProviderAbort | None = None


def _artifact_inputs(plan, cell, target):
    import inspect
    from research_loop.modular.artifact_catalogue import source_snapshot
    return FrozenRecord.from_dict({'task': target.task.data(), 'plan': plan.record.data(),
        'cell': cell, 'target': target.binding.data(), 'histories': [h.binding.data() for h in plan.histories],
        'selection_source': source_snapshot(Path(inspect.getfile(type(plan))))})


def _builder_applied(plan, cell):
    if 'M9' not in cell['arm']['enabled']: return False
    if plan.experiment_id=='Q6.5': return True  # Shared proposal use alone does not enable M9.
    if plan.experiment_id=='Q6.3': return cell['variant']=='train_proposed'
    if plan.experiment_id=='Q6.2': return cell['variant'] in {'manual_train','automatic_train'}
    if plan.experiment_id in {'Q6.1','Q6.6'}: return True
    raise ContractError('builder artifact activation has no declared study policy')


def _run_cell(plan,cell,target,root,model,broker,audit_verifier):
    native=type(model) is PhaseProviderScope
    root.mkdir(parents=True,exist_ok=False)
    phase=_Journal(root/'phase.jsonl');phase.append('phase_lock',{'plan_digest':plan.record.content_hash,'cell':cell,'allocation':_ALLOCATION})
    proposal=None;solver=None;candidate=None;selected=None;build_receipt=None;stage='preflight';status='failed';reason=None
    def charged_model(request):
        phase.append('model_reservation',{'request_digest':request.content_hash,'slot':request.data()['slot'],
            'limits':plan.record.data()['model_config'],'cost':'reported_or_unknown'})
        before=model.cursor() if native else len(model.ledger['calls'])
        try: return model(request)
        finally:
            phase.append('model_charge',{'request_digest':request.content_hash,'provider_calls':([c.data() for c in model.calls_since(before)] if native else [_safe_call(c) for c in model.ledger['calls'][before:]])})
    try:
        plan.verify_sources()
        stage='builder_proposal'
        proposal=RunSession(target.task,package_digest=plan.parent.digest,arm=FrozenRecord.from_dict(cell['arm']),
            objective=target.objective,slots=('builder_proposal',),execution_limit=0,sidecar=root/'proposal',
            verifier=audit_verifier,required_audit=('measurement',))
        response=proposal.invoke('builder_proposal',charged_model,evidence_only=True,
            instruction='Propose a bounded emit_literal_change_v1 builder using the supplied existing public training observations. Return exactly entrypoint, surface, key and value. Use prompt/instructions or memory/lesson; propose no task, scorer, tool, source path, validation or activation operation.',
            module_context=FrozenRecord.from_dict({'public_history':[h.binding.data()['public'] for h in plan.histories],
                'public_inputs':target.binding.data()['input_artifacts'],'binding':digest({'plan':plan.record.content_hash,'target':target.task.content_hash})}))
        try:
            proposed=_builder(FrozenBuilderVersion(response))
        except Exception as exc:
            proposal.driver_failure(driver_id='q63_builder_proposal',response=response,error_type=type(exc).__name__)
            raise
        proposal._record('metaprogram_proposal_terminal',{'schema':'q63-proposal-terminal-v1',
            'response_digest':response.content_hash,'builder_digest':proposed.digest,'model_calls':1})
        proposal._terminal=True
        stage='post_proposal_preflight';plan.verify_sources()
        selected=plan.selected_builder(proposed,cell)
        stage='builder_execution'
        phase.append('builder_request',{'builder_digest':selected.digest,'entrypoint':selected.entrypoint,
            'parent_digest':plan.parent.digest,'search_cost':1,'allocation':1})
        from research_loop.modular.proposal_builder_artifacts import execute_proposal_builder
        candidate,build_receipt=execute_proposal_builder(proposal,root=root,host='metaprogram-training',
            inputs=_artifact_inputs(plan,cell,target),selected=selected,parent=plan.parent,response=response,
            enabled=_builder_applied(plan,cell),on_return=lambda c,r: phase.append('builder_returned',{
                'candidate':c.record.data() if isinstance(c,CandidatePackage) else None,
                'receipt':r.record.data() if isinstance(r,BuilderRunReceipt) else None,
                'candidate_type':type(c).__name__,'receipt_type':type(r).__name__}))
        projection=_checked_build(candidate,build_receipt,selected,plan.parent)
        phase.append('builder_result',{'candidate_digest':candidate.digest,'receipt_digest':build_receipt.record.content_hash,
            'public_projection':projection.data()})
        stage='train_operation'
        execution_material=plan.execution_material(candidate,cell,root,phase)
        if execution_material is None: raise ContractError('train operation blocks successor execution')
        execution_candidate,projection=execution_material
        stage='solver_preflight';plan.verify_sources()
        stage='benchmark_solve'
        phase.append('solver_request',{'candidate_digest':execution_candidate.digest,'projection':projection.data(),
            'allocation':{'model_calls':2,'docker_attempts':1}})
        solver=run_benchmark_solve(task=target.task,public_inputs=target.public_inputs,image=plan.record.data()['image'],
            package_digest=execution_candidate.digest,arm=FrozenRecord.from_dict(cell['arm']),objective=target.objective,sidecar=root/'solver',
            broker=broker,model=charged_model,audit_verifier=audit_verifier,timeout_seconds=plan.record.data()['timeout_seconds'],
            predecessor_context=projection)
        phase.append('solver_result',{'status':solver.status,'record':solver.record.data()})
        status='succeeded' if solver.status=='execution_succeeded' else 'failed'
        reason=None if status=='succeeded' else 'solver_'+solver.status
    except Exception as exc:
        reason=type(exc).__name__+'_'+stage
        phase.append('phase_failure',{'stage':stage,'error_type':type(exc).__name__})
    phase.append('stage_result',{'status':status,'stage':stage,'reason':reason})
    solver_path=root/'solver'/'trace.jsonl';proposal_path=root/'proposal'/'trace.jsonl'
    rows=[r.data() for r in phase.rows];solver_rows=_events(solver_path) if solver_path.exists() else []
    record=FrozenRecord.from_dict({'schema':'q63-training-cell-receipt-v2' if native else 'q63-training-cell-receipt-v1','cell_id':cell['cell_id'],'plan_digest':plan.record.content_hash,
        'status':status,'stage':stage,'reason':reason,'allocation':_ALLOCATION,'actual':_phase_actual(rows,solver_rows,native=native),
        'selected_builder_digest':selected.digest if selected else None,'candidate_digest':candidate.digest if isinstance(candidate,CandidatePackage) else None,
        'builder_receipt_digest':build_receipt.record.content_hash if isinstance(build_receipt,BuilderRunReceipt) else None,
        'phase_trace':_proof(root/'phase.jsonl'),'proposal_trace':_proof(proposal_path) if proposal_path.exists() else None,
        'solver_trace':_proof(solver_path) if solver_path.exists() else None})
    _exclusive(root/'cell-receipt.json',record)
    return MetaTrainingCell(root,record)


def run_metaprogram_training(plan,*,run_root,model,audit_verifier):
    if not isinstance(plan,FrozenMetaTrainingPlan) or not isinstance(audit_verifier,AuditVerifier):
        raise ContractError('typed train phase plan and verifier required')
    plan.verify_sources()
    native=plan.record.data()['schema']=='q63-train-phase-plan-v2'
    configuration=provider_configuration(model) if native else model_configuration(model)
    if configuration.data()!=plan.record.data()['model_config']:
        raise ContractError('live model schema or budget differs from frozen phase')
    if (bool(model.inspect()) or model.terminal()) if native else (model.ledger['calls'] or model.ledger['tokens']!=0 or model.ledger['usage_incomplete']is not False):
        raise ContractError('training phase requires a fresh independent model ledger')
    root=_path(run_root,exists=False)
    if root.exists(): raise ContractError('phase root is already used; no retry or overwrite')
    model_root=model.root.resolve()
    if root==model_root or root in model_root.parents or model_root in root.parents: raise ContractError('phase and model roots must be separate')
    for path in [h.trace_path for h in plan.histories]+[p for t in plan.targets for _,p in t.inputs]:
        if root==path or root in path.parents: raise ContractError('phase root may not contain frozen source inputs')
    root.mkdir(parents=True,exist_ok=False);_exclusive(root/'plan.json',plan.record)
    scopes=PhaseProviderSession(model,root/'provider-scopes.json') if native else None
    attempt={'schema':'q63-training-attempt-v2' if native else 'q63-training-attempt-v1','plan_digest':plan.record.content_hash,'status':'allocating',
        'expected_cells':len(plan.record.data()['cells']),'cell_receipts':[]}
    _atomic(root/'training-attempt.json',attempt)
    try:
        broker=DockerExecutionBroker([root,*sorted({p.parent for t in plan.targets for _,p in t.inputs})])
        cells=[];targets={t.task.content_hash:t for t in plan.targets}
        for cell in plan.record.data()['cells']:
            result=None
            try:
                with (scopes.scope(cell['cell_id']) if native else nullcontext(model)) as scoped:
                    result=_run_cell(plan,cell,targets[cell['task_digest']],root/'cells'/cell['cell_id'],scoped,broker,audit_verifier)
            except ContractError:
                if not native:raise
                scopes.abort()  # Rejects unrelated errors without a durable core fault.
            if native and scopes.aborted is not None:
                if result is not None:cells.append(result)
                abort=scopes.finish(root/'provider-ledger.json')
                result=_finish_aborted_phase(plan,root,cells,abort)
                attempt.update(status='provider_provenance_failed',attempts=result.receipt.data()['attempts'])
                _atomic(root/'training-attempt.json',attempt)
                _verify_aborted_phase(result,plan);return result
            cells.append(result);attempt.update(status='executing',cell_receipts=[c.record.data() for c in cells])
            _atomic(root/'training-attempt.json',attempt)
    except Exception as exc:
        attempt.update(status='interrupted',error_type=type(exc).__name__);_atomic(root/'training-attempt.json',attempt);raise
    provider_ledger=scopes.finish(root/'provider-ledger.json') if native else None
    if type(provider_ledger) is PhaseProviderAbort:
        result=_finish_aborted_phase(plan,root,cells,provider_ledger)
        _verify_aborted_phase(result,plan);return result
    ledger_path=provider_ledger.path if native else model.ledger_path
    complete=all(c.record.data()['status']=='succeeded' for c in cells)
    receipt=FrozenRecord.from_dict({'schema':'q63-training-phase-receipt-v2' if native else 'q63-training-phase-receipt-v1','plan_digest':plan.record.content_hash,
        'status':'engineering_complete' if complete else 'engineering_incomplete','observed_cells':len(cells),
        'cell_receipt_digests':[c.record.content_hash for c in cells],'actual':_phase_total(cells),
        'allocated':{'cells':len(cells),'per_cell':_ALLOCATION,'model_calls':len(cells)*3},
        'model_ledger_sha256':_sha(ledger_path.read_bytes()),'scientific_effect':'not_measured',
        'builder_activation':'not_performed','scoring':'not_configured','history_acquisition_cost':'inherited; not included in phase calls'})
    _exclusive(root/'training-receipt.json',receipt)
    attempt.update(status=receipt.data()['status']);_atomic(root/'training-attempt.json',attempt)
    result=MetaTrainingRun(root,ledger_path,tuple(cells),receipt,provider_ledger)
    if native:
        return _close_native_phase(result,plan,scopes,lambda candidate:verify_metaprogram_training(candidate,plan=plan))
    verify_metaprogram_training(result,plan=plan)
    return result


def _check_trace_proof(path,proof):
    if proof is None or _proof(path)!=proof: raise ContractError('actual phase source trace differs from its frozen receipt')


def _verify_proposal(path,proof,plan,cell,target):
    _check_trace_proof(path,proof);verify_trace(path);rows=_events(path);lock=rows[0]['data']
    if (lock.get('task_digest')!=target.task.content_hash or lock.get('identity')!=target.task.identity.data()
            or lock.get('package_digest')!=plan.parent.digest or lock.get('arm')!=cell['arm']
            or lock.get('objective')!=target.objective.data() or lock.get('slots')!=['builder_proposal']
            or lock.get('execution_limit')!=0 or rows[0]['lock_digest']!=FrozenRecord.from_dict(lock).content_hash):
        raise ContractError('proposal original lock or task binding drift')
    requests=[e['data']['request'] for e in rows if e['stage']=='model_request']
    if len(requests)!=1: raise ContractError('proposal must retain exactly one model opportunity')
    request=FrozenRecord.from_dict(requests[0]);raw=request.data()
    expected_context={'public_history':[h.binding.data()['public'] for h in plan.histories],
        'public_inputs':target.binding.data()['input_artifacts'],'binding':digest({'plan':plan.record.content_hash,'target':target.task.content_hash})}
    if (raw.get('task')!=target.task.data() or raw.get('objective')!=target.objective.data()
            or raw.get('module_context')!=expected_context or raw.get('lock_digest')!=rows[0]['lock_digest']
            or raw.get('slot')!='builder_proposal' or rows[1]['data'].get('request_digest')!=request.content_hash):
        raise ContractError('actual builder model request lacks frozen public historical context')
    stages=[e['stage'] for e in rows]
    if stages[-1]=='metaprogram_proposal_terminal':
        if stages!=['objective_lock','model_request','model_response','metaprogram_proposal_terminal']:
            raise ContractError('proposal has an unexpected phase schedule')
        response=FrozenRecord.from_dict(rows[2]['data']['response']);builder=_builder(FrozenBuilderVersion(response))
        if (rows[2]['data']['request_digest']!=request.content_hash or rows[-1]['data']!={
                'schema':'q63-proposal-terminal-v1','response_digest':response.content_hash,'builder_digest':builder.digest,'model_calls':1}):
            raise ContractError('proposal terminal does not bind the actual model DSL')
        return builder,rows
    from research_loop.modular.protocol_trace import verify_protocol_trace
    verify_protocol_trace(path)
    if stages[-1] not in {'model_failure','driver_failure','controller_failure'}:
        raise ContractError('proposal phase has no real terminal')
    return None,rows


def _verify_cell(result,plan,cell,target,ledger):
    root=result.root;record=result.record;row=record.data();native=type(ledger) is PhaseProviderLedger
    _path(root/'cell-receipt.json')
    if _read_record(root/'cell-receipt.json')!=record:
        raise ContractError('cell receipt differs from immutable sidecar')
    if (row.get('schema')!=('q63-training-cell-receipt-v2' if native else 'q63-training-cell-receipt-v1') or row.get('cell_id')!=cell['cell_id']
            or row.get('plan_digest')!=plan.record.content_hash or row.get('allocation')!=_ALLOCATION):
        raise ContractError('foreign meta-training cell receipt')
    _check_trace_proof(root/'phase.jsonl',row['phase_trace']);phase=_phase_rows(root/'phase.jsonl')
    if phase[0]['data']!={'plan_digest':plan.record.content_hash,'cell':cell,'allocation':_ALLOCATION}:
        raise ContractError('phase original lock differs from complete allocated cell')
    if phase[-1]['stage']!='stage_result' or phase[-1]['data']!={k:row[k] for k in ('status','stage','reason')}:
        raise ContractError('phase status contradicts actual terminal')
    if row['status'] not in {'succeeded','failed'} or (row['status']=='succeeded')!=(row['reason'] is None):
        raise ContractError('invalid phase completion status')
    proposed=None;proposal_rows=[];solver_rows=[]
    if row['proposal_trace'] is not None:
        proposed,proposal_rows=_verify_proposal(root/'proposal'/'trace.jsonl',row['proposal_trace'],plan,cell,target)
    elif row['stage']!='preflight' or row['status']=='succeeded': raise ContractError('phase lacks its actual proposal source')
    builder_requests=[e for e in phase if e['stage']=='builder_request'];builder_results=[e for e in phase if e['stage']=='builder_result']
    candidate=None;projection=None
    if builder_requests:
        if proposed is None or len(builder_requests)!=1: raise ContractError('builder execution lacks valid original proposal')
        selected=plan.selected_builder(proposed,cell)
        if (_read_record(root/'builder.json')!=selected.record
                or row['selected_builder_digest']!=selected.digest or builder_requests[0]['data']!={
                    'builder_digest':selected.digest,'entrypoint':selected.entrypoint,'parent_digest':plan.parent.digest,'search_cost':1,'allocation':1}):
            raise ContractError('selected builder does not follow the frozen M9 intervention')
        from research_loop.modular.proposal_builder_artifacts import verify_proposal_builder
        audited=verify_proposal_builder(root=root,host='metaprogram-training',inputs=_artifact_inputs(plan,cell,target),
            selected=selected,parent=plan.parent,response=proposed.record,enabled=_builder_applied(plan,cell))
        if builder_results:
            if len(builder_results)!=1: raise ContractError('builder was executed more than once')
            if audited.data()['status']!='succeeded': raise ContractError('successful training build requires successful audited builder')
            candidate=CandidatePackage(_read_record(root/'candidate.json'))
            receipt=BuilderRunReceipt(_read_record(root/'builder-receipt.json'))
            projection=_checked_build(candidate,receipt,selected,plan.parent)
            returned=[e['data'] for e in phase if e['stage']=='builder_returned']
            if returned!=[{'candidate':candidate.record.data(),'receipt':receipt.record.data(),
                    'candidate_type':'CandidatePackage','receipt_type':'BuilderRunReceipt'}]:
                raise ContractError('checked builder output differs from its original returned artifacts')
            if (row['candidate_digest']!=candidate.digest or row['builder_receipt_digest']!=receipt.record.content_hash
                    or builder_results[0]['data']!={'candidate_digest':candidate.digest,'receipt_digest':receipt.record.content_hash,'public_projection':projection.data()}):
                raise ContractError('generated candidate receipt is not actual restricted builder output')
    elif row['selected_builder_digest'] is not None or builder_results: raise ContractError('unexecuted builder cannot produce a candidate')
    if candidate is not None:
        execution_material=plan.execution_material(candidate,cell,root,phase,replay=True)
        if execution_material is None:
            if row['solver_trace'] is not None or row['status']!='failed':
                raise ContractError('blocked train operation cannot execute a successor')
            candidate=None
        else: candidate,projection=execution_material
    if row['solver_trace'] is not None:
        if candidate is None: raise ContractError('solver lacks actual generated package')
        path=root/'solver'/'trace.jsonl';_check_trace_proof(path,row['solver_trace']);verify_benchmark_solve_trace(path,target.task)
        solver_rows=_events(path);lock=solver_rows[0]['data'];analysis=None;execution=None;slot=None
        if (lock.get('package_digest')!=candidate.digest or lock.get('arm')!=cell['arm'] or lock.get('objective')!=target.objective.data()):
            raise ContractError('successor solver does not lock the generated candidate')
        for event in solver_rows:
            if event['stage']=='model_request':
                request=event['data']['request']
                slot=request['slot']
                if request.get('task')!=target.task.data() or request.get('module_context',{}).get('predecessor_context')!=projection.data():
                    raise ContractError('actual solver prompt did not consume generated public changes')
            elif event['stage']=='model_response':
                response=FrozenRecord.from_dict(event['data']['response'])
                try:
                    if slot=='analysis_program': _program_from(response);analysis=response
                    elif slot=='final_answer': _candidate_from(response,target.objective)
                    else: raise ContractError('successor response has an unexpected slot')
                except ContractError:
                    terminal=solver_rows[-1]
                    expected_reason={'analysis_program':'solver_analysis_rejected','final_answer':'solver_answer_rejected'}.get(slot)
                    if (expected_reason is None or event!=solver_rows[-2] or terminal['stage']!='driver_failure'
                            or terminal['data'].get('response_digest')!=response.content_hash
                            or terminal['data'].get('request_digest')!=event['data']['request_digest']
                            or row['status']!='failed' or row['reason']!=expected_reason):
                        raise
            elif event['stage']=='execution_result':
                execution=ExecutionReceipt.parse(event['data']['receipt'])
                if analysis is None: raise ContractError('solver execution lacks the actual analysis response')
                program=analysis.data()['program'].replace('\n',os.linesep).encode('utf-8')
                source=root/'solver'/'analysis-1.py';_path(source)
                if (source.read_bytes()!=program or (execution.artifact is None and execution.status!='rejected')
                        or (execution.artifact is not None and (execution.artifact.sha256!=_sha(program)
                            or execution.artifact.byte_count!=len(program) or Path(execution.artifact.path).resolve()!=source.resolve()))):
                    raise ContractError('actual Docker program differs from the original model response')
                if execution.status not in {'unavailable','rejected'} and execution.record.data()['input_artifacts']!=target.binding.data()['input_artifacts']:
                    raise ContractError('actual successor execution used different frozen public inputs')
        if row['status']=='succeeded' and (solver_rows[-1]['stage']!='final_decision' or execution is None or execution.status!='succeeded'):
            raise ContractError('successful phase lacks a completed actual Docker solve')
    elif row['status']=='succeeded': raise ContractError('successful phase cannot omit its solver')
    requests=[e['data']['request_digest'] for e in (*proposal_rows,*solver_rows) if e['stage']=='model_request']
    source_slots={e['data']['request_digest']:e['data']['request']['slot'] for e in (*proposal_rows,*solver_rows) if e['stage']=='model_request'}
    reservations=[e['data'] for e in phase if e['stage']=='model_reservation'];charges=[e['data'] for e in phase if e['stage']=='model_charge']
    if ([r['request_digest'] for r in reservations]!=requests or [r['request_digest'] for r in charges]!=requests
            or any(r['limits']!=plan.record.data()['model_config'] or r['cost']!='reported_or_unknown'
                or r['slot']!=source_slots[r['request_digest']] for r in reservations)):
        raise ContractError('model charge schedule differs from actual source requests')
    outputs={e['data']['request_digest']:FrozenRecord.from_dict(e['data']['response']).content_hash
        for e in (*proposal_rows,*solver_rows) if e['stage']=='model_response'}
    used=[]
    native_calls=ledger.calls_for_scope(cell['cell_id']) if native else ()
    for charge in charges:
        recorded=charge['provider_calls']
        if len(recorded)>1: raise ContractError('one request cannot consume multiple provider attempts')
        ids=[r['id'] for r in recorded]
        actual=([c.data() for c in native_calls if c.data()['id'] in ids] if native
            else [_safe_call(c) for c in ledger['calls'] if c['id'] in ids])
        request_key='request_digest' if native else 'request_hash'
        response_key='response_digest' if native else 'output_hash'
        status_key='native_status' if native else 'status'
        if recorded!=actual or any(c[request_key]!=charge['request_digest'] or c['slot']!=source_slots[charge['request_digest']] for c in actual):
            raise ContractError('actual provider ledger differs from retained costs')
        response_hash=outputs.get(charge['request_digest'])
        if response_hash is not None and (len(actual)!=1 or actual[0][status_key]!='succeeded' or actual[0][response_key]!=response_hash):
            raise ContractError('actual model response differs from provider output binding')
        if response_hash is None and any(c[status_key]=='succeeded' for c in actual):
            raise ContractError('provider response is absent from its original runtime source')
        used.extend(c['id'] for c in actual)
    if native:
        consumed={c.data()['request_digest'] for c in native_calls}
        events=[e for e in (*proposal_rows,*solver_rows) if e['stage'] not in {'model_request','model_response'}
            or (FrozenRecord.from_dict(e['data']['request']).content_hash if e['stage']=='model_request'
                else e['data']['request_digest']) in consumed]
        bound=ledger.bind_events(events,scope_id=cell['cell_id'],require_eligible=False)
        if list(bound)!=used:raise ContractError('cell charge order omits or reuses a native original')
    actual=_phase_actual(phase,solver_rows,native=native)
    if actual!=row['actual'] or actual['model_requests']>3 or actual['builder_attempts']>1 or actual['docker_attempts']>1:
        raise ContractError('phase actual usage exceeds or contradicts frozen allocation')
    if row['status']=='succeeded' and (actual['model_requests']!=3 or actual['provider_calls']!=3
            or (bool(actual['unknown_main_opportunities'] or actual['unsuccessful_opportunities']) if native else (actual['unknown_cost'] or actual['provider_usage_incomplete'])) or actual['builder_attempts']!=1 or actual['docker_attempts']!=1):
        raise ContractError('successful phase lacks its matched actual opportunities')
    return used


def verify_metaprogram_training(result,*,plan):
    """Read actual immutable artifacts and model costs; never create or resume work."""
    if not isinstance(result,MetaTrainingRun) or not isinstance(plan,FrozenMetaTrainingPlan):
        raise ContractError('typed phase result and frozen plan required')
    if type(result.provider_ledger) is PhaseProviderAbort:
        plan.verify_sources();return _verify_aborted_phase(result,plan)
    plan.verify_sources();root=result.root;_path(result.model_ledger_path)
    if _read_record(root/'plan.json')!=plan.record:
        raise ContractError('actual phase plan differs from expected caller plan')
    if _read_record(root/'training-receipt.json')!=result.receipt:
        raise ContractError('actual phase receipt differs from returned record')
    native=plan.record.data()['schema']=='q63-train-phase-plan-v2'
    row=result.receipt.data();ledger_raw=result.model_ledger_path.read_bytes()
    if _sha(ledger_raw)!=row['model_ledger_sha256']:raise ContractError('model ledger bytes changed after phase freeze')
    expected=plan.record.data()['model_config']
    if native:ledger=_phase_ledger(result,expected)
    else:
        ledger=json.loads(ledger_raw);config=ledger['config']
        if (any(config.get(k)!=expected[k] for k in ('model','effort','max_calls','max_tokens','schemas'))
                or config.get('context_mode')!='reviewed' or config.get('context_policy',{}).get('sha256')!=expected['context_policy_sha256']):
            raise ContractError('provider ledger does not bind frozen model and reviewed context')
    declared=plan.record.data()['cells'];expected_ids=[c['cell_id'] for c in declared]
    if ([c.record.data()['cell_id'] for c in result.cells]!=expected_ids
            or len({c.root.resolve() for c in result.cells})!=len(expected_ids)
            or any(c.root!=root/'cells'/c.record.data()['cell_id'] for c in result.cells)):
        raise ContractError('full frozen meta-training denominator or paths changed')
    targets={t.task.content_hash:t for t in plan.targets};used=[]
    for cell,actual in zip(declared,result.cells): used.extend(_verify_cell(actual,plan,cell,targets[cell['task_digest']],ledger))
    if (used if native else sorted(used))!=_ledger_ids(ledger): raise ContractError('phase costs omit or duplicate a real provider call')
    complete=all(c.record.data()['status']=='succeeded' for c in result.cells)
    expected_record=FrozenRecord.from_dict({'schema':'q63-training-phase-receipt-v2' if native else 'q63-training-phase-receipt-v1','plan_digest':plan.record.content_hash,
        'status':'engineering_complete' if complete else 'engineering_incomplete','observed_cells':len(result.cells),
        'cell_receipt_digests':[c.record.content_hash for c in result.cells],'actual':_phase_total(result.cells),
        'allocated':{'cells':len(result.cells),'per_cell':_ALLOCATION,'model_calls':len(result.cells)*3},
        'model_ledger_sha256':_sha(ledger_raw),'scientific_effect':'not_measured','builder_activation':'not_performed',
        'scoring':'not_configured','history_acquisition_cost':'inherited; not included in phase calls'})
    if result.receipt!=expected_record: raise ContractError('phase totals or evidence claims contradict actual complete denominator')
    return FrozenRecord.from_dict({'schema':'q63-training-verification-v2' if native else 'q63-training-verification-v1','observed_cells':len(result.cells),
        'status':row['status'],'plan_digest':plan.record.content_hash,'actual':row['actual'],
        'scientific_effect':'not_measured','builder_activation':'not_performed'})
