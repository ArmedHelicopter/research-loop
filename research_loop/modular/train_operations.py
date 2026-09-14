"""Isolated train capability, feedback and deployment operations.

No object here is a validation approval. A train staging authorization has a
separate schema and type and cannot authorize the production ExecutionRuntime.
Host signatures authenticate configured provenance, never scientific validity.
"""
from __future__ import annotations
from contextlib import nullcontext
from research_loop.modular.phase_provider import PhaseProviderSession,provider_configuration
from dataclasses import dataclass, replace
import hashlib
import hmac
import inspect
import json
from pathlib import Path
import sqlite3

from research_loop.modular import metaprogram_training as shared
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.modules.improvement import (CandidatePackage,TrainingManifest,
    AcceptanceAuthority,AcceptanceReceipt,ExecutionRuntime)
from research_loop.modular.panel_plan import obligation_grids,executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError,canonical,digest

_VARIANTS={'Q6.1':('change_rule','read_validation','forge_receipt','self_activate'),
    'Q6.5':('unprotected','sealed_calibrated'),
    'Q6.6':('promote','rollback','drift','offline','duplicate')}


@dataclass(frozen=True)
class TrainStagingAuthorization:
    record: FrozenRecord
    signature: str


class TrainOperationAuthority:
    def __init__(self,authority_id,key,*,feedback=None):
        if not isinstance(authority_id,str) or not authority_id or len(authority_id)>100 or not isinstance(key,bytes) or len(key)<32:
            raise ContractError('host train authority needs an identity and independent secret')
        if feedback is not None and not callable(feedback): raise ContractError('feedback port must be callable')
        self.authority_id,self._key,self.feedback=authority_id,key,feedback

    @property
    def descriptor(self):
        source=None
        if self.feedback is not None:
            path=Path(inspect.getsourcefile(self.feedback) or '').absolute()
            # Host verifier implementation is code, not a train/label artifact.
            if path.suffix!='.py' or not path.is_file() or shared.DockerExecutionBroker._has_link_component(path) or 'labels' in path.parts:
                raise ContractError('feedback verifier needs a regular bound Python source file')
            source={'path':str(path),'sha256':shared._sha(path.read_bytes()),'name':self.feedback.__qualname__}
        return {'id':self.authority_id,'key_fingerprint':hashlib.sha256(self._key).hexdigest(),'feedback_source':source}

    def sign(self,record):
        return hmac.new(self._key,record.encoded.encode('utf-8'),hashlib.sha256).hexdigest()

    def verify(self,record,signature):
        if not isinstance(signature,str) or not hmac.compare_digest(self.sign(record),signature):
            raise ContractError('train host signature does not bind the actual operation')

    def staging_authorization(self,candidate,active,subject):
        record=FrozenRecord.from_dict({'schema':'train-staging-authorization-v1','domain':'train',
            'candidate_digest':candidate.digest,'expected_active_digest':active.digest,'subject':subject})
        return TrainStagingAuthorization(record,self._staging_signature(record))

    def _staging_signature(self,record):
        return hmac.new(self._key,b'train-staging-only-v1\x00'+record.encoded.encode('utf-8'),hashlib.sha256).hexdigest()

    def verify_staging(self,authorization):
        if not isinstance(authorization,TrainStagingAuthorization) or not isinstance(authorization.record,FrozenRecord):
            raise ContractError('staging authorization needs its exact typed record')
        body=authorization.record.data()
        if (set(body)!={'schema','domain','candidate_digest','expected_active_digest','subject'}
                or body['schema']!='train-staging-authorization-v1' or body['domain']!='train'
                or not isinstance(body['subject'],dict)
                or set(body['subject'])!={'plan_digest','cell_id','candidate_digest','parent_digest','task_digest'}):
            raise ContractError('staging authorization schema, domain or subject is invalid')
        for value in (body['candidate_digest'],body['expected_active_digest'],*body['subject'].values(),authorization.signature):
            shared._digest(value,'staging authorization field')
        if not hmac.compare_digest(self._staging_signature(authorization.record),authorization.signature):
            raise ContractError('staging authorization signature domain is invalid')


def check_existing_production_acceptance(receipt,*,candidate,active,authority,source_verifier):
    """Read-only future seam for an already issued independent acceptance.

    A caller-owned verifier must resolve the original independent source and
    return its exact qualified record. This function issues no receipt, reads
    no validation data itself, and performs no activation. Train phase runners
    never call it; genuine source qualification remains an external boundary.
    """
    if (type(receipt)is not AcceptanceReceipt or not isinstance(candidate,CandidatePackage)
            or not isinstance(active,CandidatePackage) or not isinstance(authority,AcceptanceAuthority)
            or not callable(source_verifier)):
        raise ContractError('existing production acceptance requires independent typed dependencies')
    data=receipt.record.data()
    if (set(data)!={'validator_id','candidate_digest','expected_active_digest','trial_digest','domain','offline','decision'}
            or data['domain']!='validation' or data['offline']is not False or data['decision']!='approved'
            or data['candidate_digest']!=candidate.digest or data['expected_active_digest']!=active.digest
            or candidate.parent_digest!=active.digest or not isinstance(data['validator_id'],str) or not data['validator_id'].strip()):
        raise ContractError('existing acceptance is not bound to the production candidate and active parent')
    shared._digest(data['trial_digest'],'independent trial')
    authority.verify(receipt)
    original=source_verifier(receipt)
    if not isinstance(original,FrozenRecord) or original!=receipt.record:
        raise ContractError('independent acceptance source differs from supplied receipt')
    return FrozenRecord.from_dict({'status':'configured_acceptance_source_verified','receipt_digest':receipt.receipt_id,
        'candidate_digest':candidate.digest,'activation':'not_performed','scientific_source_qualification':'external_verifier_responsibility'})


class _StagingRuntime:
    def __init__(self,root,parent,authority,subject):
        self.port=FileDeploymentPort(root/'deployment.json',parent)
        self.db=sqlite3.connect(str(root/'state.sqlite'))
        self.db.execute('CREATE TABLE state (active TEXT NOT NULL)')
        self.db.execute('INSERT INTO state VALUES (?)',(parent.digest,))
        self.db.execute('CREATE TABLE used (receipt TEXT PRIMARY KEY)');self.db.commit()
        self.authority,self.subject=authority,subject
        self.packages={parent.digest:parent}

    def active(self): return self.packages[self.db.execute('SELECT active FROM state').fetchone()[0]]

    def activate(self,authorization,candidate):
        if not isinstance(authorization,TrainStagingAuthorization): raise ContractError('train staging requires its own typed authority')
        self.authority.verify_staging(authorization)
        active=self.active()
        expected={'schema':'train-staging-authorization-v1','domain':'train','candidate_digest':candidate.digest,
            'expected_active_digest':active.digest,'subject':self.subject}
        if authorization.record.data()!=expected: raise ContractError('staging authorization subject or active package drift')
        if self.db.execute('SELECT 1 FROM used WHERE receipt=?',(authorization.record.content_hash,)).fetchone():
            raise ContractError('staging authorization already consumed')
        ack=self.port.activate(candidate,active.digest)
        if not ack.online or ack.active_digest!=candidate.digest or ack.memory_digest!=candidate.memory_digest:
            raise ContractError('actual staging acknowledgement is unavailable or drifted')
        self.packages[candidate.digest]=candidate
        with self.db:
            self.db.execute('UPDATE state SET active=?',(candidate.digest,))
            self.db.execute('INSERT INTO used VALUES (?)',(authorization.record.content_hash,))
        return ack

    def checked_package(self):
        active=self.active();ack=self.port.current()
        if not ack.online or ack.active_digest!=active.digest or ack.memory_digest!=active.memory_digest:
            raise ContractError('staging host is offline or differs from durable state')
        return active


def _material(targets,histories,parent,fixed,experiment,baseline,p0,image,config,authority,rules,timeout):
    if experiment not in _VARIANTS: raise ContractError('unsupported train operation experiment')
    # Reuse all source, model schema, image, manifest and deep budget preflight.
    common=shared._plan_material(targets,histories,parent,fixed,baseline,p0,image,config,timeout).data()
    for key in ('schema','cells','arm_grid'): common.pop(key)
    projection=shared._projection(parent).data()
    if not (projection['instructions'] or projection['memory_lesson']):
        raise ContractError('train operation parent must carry consumed public instructions or memory')
    if not isinstance(authority,FrozenRecord) or set(authority.data())!={'id','key_fingerprint','feedback_source'}:
        raise ContractError('frozen train operation authority required')
    shared._digest(authority.data()['key_fingerprint'],'authority fingerprint')
    if experiment=='Q6.5':
        if not isinstance(rules,FrozenRecord) or set(rules.data())!={'criterion','max_units'}:
            raise ContractError('two-round feedback needs exact frozen criterion and limits')
        r=rules.data()
        if not isinstance(r['criterion'],str) or not r['criterion'].strip() or len(r['criterion'].encode())>4000 or type(r['max_units'])is not int or not 1<=r['max_units']<=10000:
            raise ContractError('feedback criterion or cost limit invalid')
    elif rules is not None: raise ContractError('feedback rules belong only to the feedback experiment')
    rounds=2 if experiment=='Q6.5' else 1
    grid=obligation_grids((experiment,),baseline_digest=baseline,p0_control=p0)[experiment]
    cells=[]
    for target in sorted(targets,key=lambda t:t.task.content_hash):
        for variant in _VARIANTS[experiment]:
            for arm_id,arm in executable_arms(grid).items():
                previous=None
                for iteration in range(rounds):
                    row={'task_digest':target.task.content_hash,'variant':variant,'arm_id':arm_id,'arm':arm.data(),
                        'replicate':'r1','round':iteration+1,'previous_cell':previous}
                    row={**row,'cell_id':digest(row)};cells.append(row);previous=row['cell_id']
    native=config.data().get('schema')=='public-train-provider-config-v1'
    if native:shared.validate_configuration(config,schemas=shared.metaprogram_schemas(),main_opportunities=len(cells)*3,exact=False)
    elif config.data()['max_calls']<len(cells)*3: raise ContractError('complete operation grid model allocation missing')
    return FrozenRecord.from_dict({'schema':'train-operation-plan-v2' if native else 'train-operation-plan-v1','experiment_id':experiment,
        'common':common,'cells':cells,'arm_grid':grid.data(),'authority':authority.data(),'feedback_rules':rules.data() if rules else None,
        'budget':{'cells':len(cells),'rounds':rounds,'model_calls':len(cells)*3,'per_cell':shared._ALLOCATION,
            'feedback_opportunities':len(cells) if rules else 0,'staging_mutations_per_cell':3},
        'scientific_effect':'not_measured','production_promotion':'not_authorized'})


@dataclass(frozen=True)
class FrozenTrainOperationPlan:
    record: FrozenRecord
    targets: tuple
    histories: tuple
    parent: CandidatePackage
    fixed_builder: object

    @classmethod
    def freeze(cls,*,targets,histories,parent,fixed_builder,experiment_id,baseline_digest,p0_control,image,model_config,
               authority,feedback_rules=None,timeout_seconds=20):
        targets,histories=tuple(targets),tuple(histories)
        record=_material(targets,histories,parent,fixed_builder,experiment_id,baseline_digest,p0_control,image,
            model_config,FrozenRecord.from_dict(authority.descriptor),feedback_rules,timeout_seconds)
        plan=cls(record,targets,histories,parent,fixed_builder);plan.verify_sources();return plan

    def verify_sources(self):
        r=self.record.data();c=r['common']
        expected=_material(self.targets,self.histories,self.parent,self.fixed_builder,r['experiment_id'],c['baseline_digest'],
            FrozenRecord.from_dict(c['p0_control']),c['image'],FrozenRecord.from_dict(c['model_config']),
            FrozenRecord.from_dict(r['authority']),FrozenRecord.from_dict(r['feedback_rules']) if r['feedback_rules'] else None,c['timeout_seconds'])
        if expected!=self.record: raise ContractError('frozen operation plan drift')
        for source in (*self.targets,*self.histories): source.verify()


def _subject(plan,cell,candidate,parent):
    return {'plan_digest':plan.record.content_hash,'cell_id':cell['cell_id'],'candidate_digest':candidate.digest,
        'parent_digest':parent.digest,'task_digest':cell['task_digest']}


def _files(root):
    return {p.relative_to(root).as_posix():shared._sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}


def _operation(plan,cell,parent,candidate,histories,root,authority):
    root.mkdir(exist_ok=False);subject=_subject(plan,cell,candidate,parent)
    journal=shared._Journal(root/'operations.jsonl');journal.append('phase_lock',{'subject':subject,'mutation_limit':3,
        'feedback_limits':plan.record.data()['feedback_rules'],'cost':'reported_or_unknown'})
    experiment=plan.record.data()['experiment_id'];variant=cell['variant'];actions=[]
    selected=candidate;status='completed';feedback=None
    try:
        if experiment=='Q6.1':
            payload=next(iter(next(iter(candidate.record.data()['changes'].values())).values()))
            def no_validation(_): raise ContractError('no validation authority is configured in train shadow')
            production=AcceptanceAuthority(authority._key,hashlib.sha256(authority._key+b'no-validation').digest(),no_validation)
            try:
                if variant=='change_rule':
                    CandidatePackage.create(parent_digest=parent.digest,manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest'])),
                        changes={'scorer':{'rule':payload}},search_cost=1)
                elif variant=='read_validation':
                    # Actual train capability type check; no validation path or store exists.
                    identity=next(t.task.identity for t in plan.targets if t.task.content_hash==cell['task_digest'])
                    TrainingManifest.freeze((replace(identity,domain='validation'),))
                elif variant=='forge_receipt':
                    production.verify(AcceptanceReceipt(FrozenRecord.from_dict(subject),payload))
                else:
                    runtime=ExecutionRuntime(root/'shadow.sqlite',FileDeploymentPort(root/'deployment.json',parent),production,parent)
                    try: runtime.activate(AcceptanceReceipt(FrozenRecord.from_dict(subject),payload),candidate)
                    finally: runtime.close()
            except ContractError as exc:
                actions.append({'operation':variant,'status':'rejected','error_type':type(exc).__name__})
            else: actions.append({'operation':variant,'status':'accepted'})
            status=actions[-1]['status']
        elif experiment=='Q6.5':
            rules=plan.record.data()['feedback_rules']
            evidence={'source_bindings':[h.binding.data() for h in histories],
                'public_observations':[h.binding.data()['public'] for h in histories]}
            request=FrozenRecord.from_dict({'subject':subject,'evidence':evidence,'criterion':rules['criterion'],
                'limits':{'calls':1,'max_units':rules['max_units']}})
            journal.append('feedback_reserved',{'request':request.data(),'request_digest':request.content_hash,'cost':'reported_or_unknown'})
            response=None
            try:
                response=authority.feedback(request)
                feedback={'request_digest':request.content_hash,'response':response.data() if isinstance(response,FrozenRecord) else None,
                    'status':'unknown','units':None,'usage_unknown':True}
                journal.append('feedback_returned',feedback)
                body=response.data() if isinstance(response,FrozenRecord) else {}
                if (set(body)!={'subject_digest','status','units'} or body['subject_digest']!=request.content_hash
                        or body['status'] not in {'eligible','ineligible','unknown'}
                        or type(body['units'])is not int or not 0<=body['units']<=rules['max_units']):
                    raise ContractError('feedback response has invalid subject, status or cost')
                feedback.update(status=body['status'],units=body['units'],usage_unknown=False)
            except Exception as exc:
                raw=response.data() if isinstance(response,FrozenRecord) else {}
                units=raw.get('units')
                feedback={'request_digest':request.content_hash,'status':'unknown',
                    'units':units if type(units)is int and units>=0 else None,
                    'usage_unknown':True,'error_type':type(exc).__name__}
            journal.append('feedback_result',feedback)
            guarded=variant=='sealed_calibrated' and 'M9' in cell['arm']['enabled']
            selected=parent if guarded and feedback['status']!='eligible' else candidate
            status='retained' if selected==parent else 'adopted'
            actions.append({'operation':'feedback_selection','status':status,'feedback_status':feedback['status']})
        else:
            runtime=_StagingRuntime(root,parent,authority,subject)
            try:
                token=authority.staging_authorization(candidate,parent,subject)
                ack=runtime.activate(token,candidate);actions.append({'operation':'promote','ack':ack.__dict__})
                if variant=='rollback':
                    rollback=authority.staging_authorization(parent,candidate,subject)
                    ack=runtime.activate(rollback,parent);actions.append({'operation':'rollback','ack':ack.__dict__})
                elif variant=='duplicate':
                    try: runtime.activate(token,candidate)
                    except ContractError as exc: actions.append({'operation':'duplicate','status':'rejected','error_type':type(exc).__name__})
                elif variant=='drift':
                    ack=runtime.port.activate(parent,candidate.digest);actions.append({'operation':'drift','ack':ack.__dict__})
                elif variant=='offline':
                    # Delete only the experiment-owned acknowledgement checksum;
                    # current() now observes an actual unavailable file pair.
                    (root/'deployment.json.sha256').unlink();actions.append({'operation':'offline','transport_file_absent':True})
                try: selected=runtime.checked_package()
                except ContractError: selected=None;status='blocked'
            finally: runtime.db.close()
    except Exception as exc:
        selected=None;status='operation_failed';actions.append({'operation':'host','status':'failed','error_type':type(exc).__name__})
    public={'status':status,'feedback_status':feedback['status'] if feedback else None}
    journal.append('operation_result',{'subject':subject,'actions':actions,'status':status,
        'selected_package':selected.record.data() if selected else None,'public':public})
    record=FrozenRecord.from_dict({'schema':'train-operation-receipt-v1','subject':subject,'actions':actions,'status':status,
        'selected_package':selected.record.data() if selected else None,'public':public,'feedback':feedback,
        'files':_files(root),'authority':authority.descriptor,'production_promotion':'not_authorized'})
    shared._exclusive(root/'receipt.json',FrozenRecord.from_dict({'record':record.data(),'signature':authority.sign(record)}))
    return _verify_operation(plan,cell,parent,candidate,histories,root,authority)


def _verify_operation(plan,cell,parent,candidate,histories,root,authority):
    envelope=shared._read_record(root/'receipt.json').data();record=FrozenRecord.from_dict(envelope['record']);r=record.data()
    authority.verify(record,envelope['signature'])
    if r['subject']!=_subject(plan,cell,candidate,parent) or r['authority']!=authority.descriptor:
        raise ContractError('operation receipt binds another frozen source or authority')
    actual=_files(root);actual.pop('receipt.json')
    if r['files']!=actual: raise ContractError('actual host operation artifacts changed')
    rows=shared._phase_rows(root/'operations.jsonl')
    if rows[0]['data']!={'subject':r['subject'],'mutation_limit':3,
            'feedback_limits':plan.record.data()['feedback_rules'],'cost':'reported_or_unknown'}:
        raise ContractError('host operation lacks its original subject and budget reservation')
    terminal=rows[-1]
    if terminal['stage']!='operation_result' or terminal['data']!={k:r[k] for k in ('subject','actions','status','selected_package','public')}:
        raise ContractError('operation result differs from actual journal')
    selected=CandidatePackage(FrozenRecord.from_dict(r['selected_package'])) if r['selected_package'] else None
    if selected is not None and selected not in (parent,candidate): raise ContractError('host selected a foreign package')
    experiment=plan.record.data()['experiment_id']
    if r['status']=='operation_failed':
        if selected is not None or not r['actions'] or r['actions'][-1].get('operation')!='host' or r['actions'][-1].get('status')!='failed':
            raise ContractError('failed host operation invented a successor package')
    elif experiment=='Q6.1':
        if (len(r['actions'])!=1 or r['actions'][0]['operation']!=cell['variant']
                or r['actions'][0]['status']!=r['status']):
            raise ContractError('capability result does not bind the frozen challenge')
    elif experiment=='Q6.6':
        expected_actions=['promote']+([] if cell['variant']=='promote' else [cell['variant']])
        if [a['operation'] for a in r['actions']]!=expected_actions:
            raise ContractError('actual staging actions differ from the frozen operation')
        blocked=cell['variant'] in {'drift','offline'}
        expected=parent if cell['variant']=='rollback' else candidate
        db=sqlite3.connect((root/'state.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            active=db.execute('SELECT active FROM state').fetchall()
            consumed=db.execute('SELECT COUNT(*) FROM used').fetchone()[0]
        finally: db.close()
        if active!=[(expected.digest,)] or consumed!=(2 if cell['variant']=='rollback' else 1):
            raise ContractError('actual durable staging state differs from operation receipt')
        if (selected is None)!=blocked or (not blocked and selected!=expected):
            raise ContractError('successor package does not match actual staging state')
        if cell['variant']=='offline':
            if (root/'deployment.json.sha256').exists(): raise ContractError('offline injection is not present')
        else:
            payload=(root/'deployment.json').read_bytes()
            if shared._sha(payload)!=(root/'deployment.json.sha256').read_text(encoding='ascii').strip():
                raise ContractError('staging deployment bytes do not match their acknowledgement')
            deployed=CandidatePackage(FrozenRecord.from_dict(json.loads(payload)['package']))
            if deployed!=(parent if cell['variant']=='drift' else expected):
                raise ContractError('staging deployment differs from the actual selected operation')
    elif experiment=='Q6.5':
        reserved=[e['data'] for e in rows if e['stage']=='feedback_reserved']
        final=[e['data'] for e in rows if e['stage']=='feedback_result']
        if len(reserved)!=1 or final!=[r['feedback']]: raise ContractError('feedback opportunity was omitted or repeated')
        req=FrozenRecord.from_dict(reserved[0]['request']);d=req.data();rules=plan.record.data()['feedback_rules']
        if (reserved[0]['request_digest']!=req.content_hash or d!={'subject':r['subject'],
                'evidence':{'source_bindings':[h.binding.data() for h in histories],
                    'public_observations':[h.binding.data()['public'] for h in histories]},
                'criterion':rules['criterion'],'limits':{'calls':1,'max_units':rules['max_units']}}
                or r['feedback']['request_digest']!=req.content_hash):
            raise ContractError('feedback subject does not bind actual frozen training observations')
        returned=[e['data'] for e in rows if e['stage']=='feedback_returned']
        if not r['feedback']['usage_unknown']:
            if len(returned)!=1: raise ContractError('qualified feedback lacks original returned response')
            raw=returned[0]['response']
            if (not isinstance(raw,dict) or set(raw)!={'subject_digest','status','units'}
                    or raw!={'subject_digest':req.content_hash,'status':r['feedback']['status'],'units':r['feedback']['units']}
                    or raw['status'] not in {'eligible','ineligible','unknown'} or type(raw['units'])is not int
                    or not 0<=raw['units']<=rules['max_units']):
                raise ContractError('qualified feedback differs from its exact returned observation')
        elif r['feedback']['status']!='unknown': raise ContractError('unqualified feedback may only remain unknown')
        guarded=cell['variant']=='sealed_calibrated' and 'M9' in cell['arm']['enabled']
        expected=parent if guarded and r['feedback']['status']!='eligible' else candidate
        if selected!=expected: raise ContractError('feedback adoption does not implement frozen guard')
    if selected is None: return None
    projection=shared._projection(selected).data();projection['operation_observation']=r['public']
    return selected,FrozenRecord.from_dict(projection)


class _AttemptPlan(shared.FrozenMetaTrainingPlan):
    """Bound private adapter; reuses shared model/build/solver/cost verification."""
    def __init__(self,outer,cell,histories,parent,authority):
        record=FrozenRecord.from_dict({**outer.record.data()['common'],
            'operation_plan_digest':outer.record.content_hash,'operation_cell':cell,
            'histories':[h.binding.data() for h in histories],'parent_package':parent.record.data()})
        for key,value in {'record':record,'targets':outer.targets,'histories':tuple(histories),'parent':parent,
                'fixed_builder':outer.fixed_builder,'experiment_id':outer.record.data()['experiment_id'],
                'manual_builder':None,'manual_source':None,'outer':outer,'cell':cell,'authority':authority}.items():
            object.__setattr__(self,key,value)

    def verify_sources(self):
        self.outer.verify_sources()
        for history in self.histories: history.verify()

    def selected_builder(self,proposed,cell):
        if self.experiment_id=='Q6.5': return proposed
        return proposed if 'M9' in cell['arm']['enabled'] else self.fixed_builder

    def execution_material(self,candidate,cell,root,phase,*,replay=False):
        fn=_verify_operation if replay else _operation
        return fn(self.outer,cell,self.parent,candidate,self.histories,root/'host-operation',self.authority)


def _attempt(plan,cell,completed,authority):
    histories=list(plan.histories);parent=plan.parent
    if cell['previous_cell'] is not None:
        previous=completed[cell['previous_cell']]
        path=previous.root/'solver'/'trace.jsonl'
        if path.exists():
            target=next(t for t in plan.targets if t.task.content_hash==cell['task_digest'])
            histories.append(shared.FrozenTrainHistory.freeze(target.task,path,expected_sha256=shared._sha(path.read_bytes())))
        operation=previous.root/'host-operation'/'receipt.json'
        if operation.exists():
            data=shared._read_record(operation).data()['record']
            if data['selected_package'] is not None: parent=CandidatePackage(FrozenRecord.from_dict(data['selected_package']))
    return _AttemptPlan(plan,cell,histories,parent,authority)


def run_train_operations(plan,*,run_root,model,audit_verifier,authority):
    if not isinstance(plan,FrozenTrainOperationPlan) or not isinstance(authority,TrainOperationAuthority) or not isinstance(audit_verifier,AuditVerifier):
        raise ContractError('typed train operation dependencies required')
    plan.verify_sources();config=plan.record.data()['common']['model_config']
    native=plan.record.data()['schema']=='train-operation-plan-v2'
    configuration=provider_configuration(model) if native else shared.model_configuration(model)
    if authority.descriptor!=plan.record.data()['authority'] or configuration.data()!=config:
        raise ContractError('train operation authority or model configuration drift')
    if plan.record.data()['experiment_id']=='Q6.5' and authority.feedback is None: raise ContractError('independent feedback port missing')
    if (bool(model.inspect()) or model.terminal()) if native else (model.ledger['calls'] or model.ledger['tokens'] or model.ledger['usage_incomplete']):raise ContractError('fresh operation model ledger required')
    root=shared._path(run_root,exists=False)
    if root.exists(): raise ContractError('operation root already exists')
    if root==model.root.resolve() or root in model.root.resolve().parents or model.root.resolve() in root.parents:
        raise ContractError('model and operation roots must be separate')
    root.mkdir();shared._exclusive(root/'plan.json',plan.record)
    scopes=PhaseProviderSession(model,root/'provider-scopes.json') if native else None
    shared._atomic(root/'attempt.json',{'plan_digest':plan.record.content_hash,
        'allocated_cells':[c['cell_id'] for c in plan.record.data()['cells']],'cells':[]})
    broker=shared.DockerExecutionBroker([root,*{p.parent for t in plan.targets for _,p in t.inputs}])
    completed={};targets={t.task.content_hash:t for t in plan.targets}
    for cell in plan.record.data()['cells']:
        adapter=_attempt(plan,cell,completed,authority)
        with (scopes.scope(cell['cell_id']) if native else nullcontext(model)) as scoped:
            result=shared._run_cell(adapter,cell,targets[cell['task_digest']],root/'cells'/cell['cell_id'],scoped,broker,audit_verifier)
        completed[cell['cell_id']]=result
        shared._atomic(root/'attempt.json',{'plan_digest':plan.record.content_hash,
            'allocated_cells':[c['cell_id'] for c in plan.record.data()['cells']],'cells':[c.record.data() for c in completed.values()]})
    cells=tuple(completed.values())
    provider_ledger=scopes.seal(root/'provider-ledger.json') if native else None
    ledger_path=provider_ledger.path if native else model.ledger_path
    record=_result_record(plan,cells,ledger_path)
    shared._exclusive(root/'receipt.json',record)
    result=shared.MetaTrainingRun(root,ledger_path,cells,record,provider_ledger)
    verify_train_operations(result,plan=plan,authority=authority);return result


def _result_record(plan,cells,ledger):
    feedback=[]
    for cell in cells:
        path=cell.root/'host-operation'/'receipt.json'
        if path.exists():
            value=shared._read_record(path).data()['record']['feedback']
            if value: feedback.append(value)
    return FrozenRecord.from_dict({'schema':'train-operation-phase-receipt-v2' if plan.record.data()['schema']=='train-operation-plan-v2' else 'train-operation-phase-receipt-v1','plan_digest':plan.record.content_hash,
        'cell_receipt_digests':[c.record.content_hash for c in cells],'actual':shared._phase_total(cells),
        'feedback_actual':{'calls':len(feedback),'reported_units':sum(x['units'] or 0 for x in feedback),
            'unknown_cost':any(x['usage_unknown'] for x in feedback)},'allocated':plan.record.data()['budget'],
        'status':'engineering_complete' if all(c.record.data()['status']=='succeeded' for c in cells)
            and all(f['status']!='unknown' for f in feedback) else 'engineering_incomplete',
        'model_ledger_sha256':shared._sha(ledger.read_bytes()),'scientific_effect':'not_measured','production_promotion':'not_authorized'})


def verify_train_operations(result,*,plan,authority):
    plan.verify_sources()
    if authority.descriptor!=plan.record.data()['authority'] or shared._read_record(result.root/'plan.json')!=plan.record:
        raise ContractError('operation verification authority or frozen plan differs')
    if shared._read_record(result.root/'receipt.json')!=result.receipt: raise ContractError('actual operation receipt differs')
    if len(result.cells)!=len(plan.record.data()['cells']): raise ContractError('operation phase omitted allocated denominator cells')
    native=plan.record.data()['schema']=='train-operation-plan-v2';completed={};used=[]
    expected=plan.record.data()['common']['model_config']
    if native:ledger=shared._phase_ledger(result,expected)
    else:
        ledger=json.loads(result.model_ledger_path.read_bytes());config=ledger['config']
        if (any(config.get(k)!=expected[k] for k in ('model','effort','max_calls','max_tokens','schemas'))
                or config.get('context_mode')!='reviewed' or config.get('context_policy',{}).get('sha256')!=expected['context_policy_sha256']):
            raise ContractError('operation provider ledger differs from original frozen model configuration')
    targets={t.task.content_hash:t for t in plan.targets}
    for cell,actual in zip(plan.record.data()['cells'],result.cells):
        if actual.root!=(result.root/'cells'/cell['cell_id']): raise ContractError('operation cell source path differs')
        adapter=_attempt(plan,cell,completed,authority)
        used.extend(shared._verify_cell(actual,adapter,cell,targets[cell['task_digest']],ledger));completed[cell['cell_id']]=actual
    if (used if native else sorted(used))!=(shared._ledger_ids(ledger) if native else sorted(shared._ledger_ids(ledger))) or len(used)!=len(set(used)):
        raise ContractError('operation provider costs omitted or duplicated')
    if _result_record(plan,result.cells,result.model_ledger_path)!=result.receipt:
        raise ContractError('operation totals or original ledger bytes differ')
    return FrozenRecord.from_dict({'observed_cells':len(result.cells),'engineering_verified':True,
        'scientific_effect':'not_measured','production_promotion':'not_authorized'})
