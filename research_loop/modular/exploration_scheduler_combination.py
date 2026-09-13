"""TRAIN-only restricted allocation and real Docker FIFO phase.

The host owns the journal and broker. Replay proves their subject bindings and
operations, not independent scientific validity or hostile-host attestation.
"""
from dataclasses import asdict, dataclass
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from research_loop.ontology import ContractError
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest, ExecutionReceipt
from research_loop.modular.modules.exploration import (ResourceClosure, ExplorationPlan, ExplorationBudget,
    FeasibilityObservation, assess_feasibility, admit_exploration)
from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.modular.runtime import RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.lineage_combination_driver import _verify_solver_files, _read_events
from research_loop.modular.combination_benchmark_driver import _runtime, _close_failure, _private_arm_marker
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.panel_receipts import opaque_panel_cell_binding

SLOTS = ('analysis_program', 'final_answer')
OBLIGATION = 'pair:M7+M8'


def registered_design(baseline):
    return default_compatibility(baseline).conditional_factorial(('M7', 'M8'))


def _hash(value): return hashlib.sha256(value).hexdigest()
def _digest(value): return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))
def _record(value): return FrozenRecord.from_dict(value)


def _read(path):
    if DockerExecutionBroker._has_link_component(path) or not path.is_file():
        raise ContractError('regular fixed phase artifact required')
    return path.read_bytes()


def _write_new(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream: stream.write(_record(body).encoded)


@dataclass(frozen=True)
class FrozenExplorationSchedulerMaterial:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord: raise ContractError('frozen job material required')
        b = self.data()
        if set(b) != {'schema','identity','task_digest','public_artifacts','jobs','context_budget_bytes'} or b['schema'] != 'exploration-scheduler-material-v1':
            raise ContractError('closed exploration scheduler material required')
        DataIdentity.parse(b['identity']).require_train()
        if not _digest(b['task_digest']) or type(b['context_budget_bytes']) is not int or not 4000 <= b['context_budget_bytes'] <= 32000:
            raise ContractError('task and bounded public context required')
        inputs = b['public_artifacts']
        if not isinstance(inputs, list) or len(inputs) != 1 or set(inputs[0]) != {'artifact','container_path'}:
            raise ContractError('one exact custody input required')
        a = inputs[0]['artifact']
        if (set(a) != {'artifact_id','sha256','byte_count'} or a['artifact_id'] != 'public_csv'
                or not _digest(a['sha256']) or type(a['byte_count']) is not int or a['byte_count'] < 1
                or inputs[0]['container_path'] != '/input/public_csv'):
            raise ContractError('exact public CSV pin required')
        jobs = b['jobs']
        if not isinstance(jobs, list) or len(jobs) != 3: raise ContractError('exact three frozen candidates required')
        ids = []
        for index, job in enumerate(jobs):
            if (not isinstance(job, dict) or set(job) != {'id','purpose','program','dependencies','resources','cost_units'}
                    or not _digest(job['id']) or job['id'] in ids or job['purpose'] != ('probe' if index == 2 else 'main')
                    or type(job['cost_units']) is not int or job['cost_units'] != 1
                    or not isinstance(job['program'], str) or not job['program'].strip() or len(job['program'].encode()) > 6000
                    or '\r' in job['program'] or re.search(r'M[1-9]|Q\d+\.\d+|expected_correct|arm_id|validation|PRIVATE', job['program'], re.I)):
                raise ContractError('frozen neutral literal job contract invalid')
            for field in ('dependencies','resources'):
                values = job[field]
                if not isinstance(values, list) or len(set(values)) != len(values) or any(not _digest(v) for v in values):
                    raise ContractError('opaque unique dependency and resource identifiers required')
            # Both alternative second jobs may depend only on the common first.
            if any(v not in ids[:1] for v in job['dependencies']): raise ContractError('dependency must exist in both selected arms')
            ids.append(job['id'])

    def data(self): return self.record.data()


def check_inputs(material, task, broker, inputs):
    if type(material) is not FrozenExplorationSchedulerMaterial or material.data()['identity'] != task.identity.data() or material.data()['task_digest'] != task.content_hash:
        raise ContractError('material does not bind prepared public task')
    artifacts = broker.validate_inputs(task.identity, inputs)
    public = [{'artifact': a.record.data(), 'container_path': '/input/'+a.artifact_id} for a in artifacts]
    if public != material.data()['public_artifacts']: raise ContractError('actual complete input bytes differ from frozen material')


def selection(material, enabled, selected_job_id=None):
    """Real M7 permit consumes the same reserve as an ordinary main job."""
    b = material.data(); budget = ExplorationBudget(2, 2).reserve(1, 1); permit = None
    selected_job_id = selected_job_id or b['jobs'][2 if 'M7' in enabled else 1]['id']
    if selected_job_id not in {j['id'] for j in b['jobs'][1:]}:
        raise ContractError('choice must select one frozen bounded alternative')
    if 'M7' in enabled:
        job = next(j for j in b['jobs'] if j['id'] == selected_job_id)
        plan = ExplorationPlan(job['id'], DataIdentity.parse(b['identity']), _record(job),
            ResourceClosure(b['identity']['dataset_version'], b['public_artifacts'][0]['artifact']['sha256'],
                b['jobs'][0]['id'], 1, 1))
        report = assess_feasibility(plan, {'data': FeasibilityObservation('data','passed',
            _record({'task': b['task_digest'],'inputs': b['public_artifacts']}).content_hash)})
        permit = admit_exploration(plan=plan, feasibility=report, budget=budget)
        budget = permit.budget_after
    else: budget = budget.reserve(1, 1)
    selected = {b['jobs'][0]['id'], selected_job_id}
    return _record({'selected': [j['id'] for j in b['jobs'] if j['id'] in selected],
        'permit': asdict(permit) if permit else None, 'budget': asdict(budget)})


def _snapshot(material, cell, objective):
    return {'evidence': material.record.content_hash, 'rules': objective.content_hash, 'package': cell.package_digest}


def run_phase(*, material, cell, objective, root, broker, inputs, image, timeout_seconds, selected_job_id=None):
    """A single immutable phase; worker threads only touch their own Docker job."""
    if (type(material) is not FrozenExplorationSchedulerMaterial or type(objective) is not FrozenRecord
            or not isinstance(broker,DockerExecutionBroker) or type(timeout_seconds) is not int or not 1<=timeout_seconds<=120
            or material.data()['identity']!=cell.identity.data() or material.data()['task_digest']!=cell.task_digest):
        raise ContractError('typed bound auxiliary phase required')
    artifacts=broker.validate_inputs(cell.identity,inputs)
    if [{'artifact':a.record.data(),'container_path':'/input/'+a.artifact_id} for a in artifacts]!=material.data()['public_artifacts']:
        raise ContractError('data feasibility requires exact actual public bytes before permit')
    if root.exists(): raise ContractError('phase replay path is exclusive; no retry or overwrite')
    root.mkdir(parents=True)
    enabled = set(cell.runtime_arm.data()['enabled']); chosen = selection(material, enabled, selected_job_id)
    jobs = {j['id']: j for j in material.data()['jobs'] if j['id'] in chosen.data()['selected']}
    snapshot = _snapshot(material, cell, objective); experiment = _record(cell.data()).content_hash
    events, lock = [], threading.Lock()
    def emit(kind, **data):
        with lock:
            row = {'sequence':len(events),'time_ns':time.monotonic_ns(),'kind':kind,**data}
            with (root/'events.jsonl').open('a',encoding='utf-8',newline='\n') as stream: stream.write(_record(row).encoded+'\n')
            events.append(row)
    _write_new(root/'allocation.json', {'cell':cell.data(),'material_digest':material.record.content_hash,
        'objective':objective.data(),'selection':chosen.data(),'image':image,'timeout_seconds':timeout_seconds,'docker_limit':2,
        'input_paths':{k:str(v.absolute()) for k,v in inputs.items()}})
    scheduler = FifoScheduler(root/'queue.sqlite',max_concurrency=2,total_budget=2) if 'M8' in enabled else None
    run_ids = {}
    for job in jobs.values():
        run_ids[job['id']] = (scheduler.enqueue(experiment_id=experiment,task_id=job['id'],dependencies=job['dependencies'],
            resources=job['resources'],cost_units=1,snapshot=snapshot).run_id if scheduler else
            _record({'experiment_id':experiment,'task_id':job['id'],'attempt':1}).content_hash)
        emit('enqueue',job=job['id'],run_id=run_ids[job['id']])
    def work(job):
        path=root/(job['id']+'.py'); path.write_bytes(job['program'].encode('utf-8'))
        emit('start',job=job['id'])
        try:
            receipt=broker.execute(ExecutionRequest(DataIdentity.parse(material.data()['identity']),image,path,inputs,timeout_seconds))
            payload={'execution':receipt.data(),'error_type':None,'cost_unknown':False}
        except Exception as exc:
            payload={'execution':None,'error_type':type(exc).__name__,'cost_unknown':True}
        result={'schema':'exploration-scheduler-job-return-v1','job':job['id'],'run_id':run_ids[job['id']],
            'attempt':1,'cost_units':1,'snapshot_digest':_record(snapshot).content_hash,**payload}
        _write_new(root/(job['id']+'.json'),result)
        emit('finish',job=job['id'],return_digest=_record(result).content_hash)
        return result
    completed = {}
    def complete(job_id, result):
        if scheduler: scheduler.complete(run_ids[job_id],receipt_id=_record(result).content_hash,receipt=result,cost_units=1)
        completed[job_id]=result
        emit('complete',job=job_id,return_digest=_record(result).content_hash)
        if scheduler and len(completed)<len(jobs):
            try: scheduler.merge(experiment)
            except ContractError: emit('barrier_refused',unfinished=len(jobs)-len(completed))
            else: raise ContractError('scheduler exposed incomplete group')
    if scheduler:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {}
            while len(completed)<len(jobs):
                while len(pending)<2:
                    lease=scheduler.claim_next('worker-'+str(len(events)),lease_seconds=timeout_seconds+60)
                    if lease is None: break
                    emit('claim',job=lease.task_id,run_id=lease.run_id,attempt=lease.attempt)
                    pending[pool.submit(work,jobs[lease.task_id])]=lease.task_id
                if not pending: raise ContractError('frozen dependency group cannot progress')
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in sorted(done,key=lambda f: next(e['sequence'] for e in events if e['kind']=='finish' and e['job']==pending[f])):
                    complete(pending.pop(future),future.result())
        scheduler.merge(experiment)
        emit('merge',jobs=list(jobs))
    else:
        for job in jobs.values():
            emit('claim',job=job['id'],run_id=run_ids[job['id']],attempt=1)
            complete(job['id'],work(job))
            emit('merge',jobs=[job['id']])
    report = _phase_projection(material,cell,objective,root,image,timeout_seconds,inputs,selected_job_id)
    _write_new(root/'receipt.json',report.data())
    return report


def _phase_projection(material,cell,objective,root,image,timeout_seconds,inputs,selected_job_id=None):
    """Replay actual files and state; no model calls or mutation of the database."""
    enabled=set(cell.runtime_arm.data()['enabled']); chosen=selection(material,enabled,selected_job_id)
    expected={'cell':cell.data(),'material_digest':material.record.content_hash,'objective':objective.data(),
        'selection':chosen.data(),'image':image,'timeout_seconds':timeout_seconds,'docker_limit':2,
        'input_paths':{k:str(v.absolute()) for k,v in inputs.items()}}
    if json.loads(_read(root/'allocation.json')) != expected: raise ContractError('phase allocation drift')
    events=[json.loads(line) for line in _read(root/'events.jsonl').splitlines()]
    if any(e['sequence']!=i or type(e['time_ns']) is not int or i and e['time_ns']<events[i-1]['time_ns'] for i,e in enumerate(events)):
        raise ContractError('phase event chronology drift')
    jobs={j['id']:j for j in material.data()['jobs'] if j['id'] in chosen.data()['selected']}
    snapshot=_snapshot(material,cell,objective); experiment=_record(cell.data()).content_hash
    statuses={k:'pending' for k in jobs}; active=set(); finished=set(); enqueued=[]; starts={}; ends={}; returns={}; visible=[]; finish_order=[]; peak=0; barrier_count=0
    for job in jobs.values():
        body=json.loads(_read(root/(job['id']+'.json'))); returns[job['id']]=body
        prefix={'schema':'exploration-scheduler-job-return-v1','job':job['id'],
            'run_id':_record({'experiment_id':experiment,'task_id':job['id'],'attempt':1}).content_hash,
            'attempt':1,'cost_units':1,'snapshot_digest':_record(snapshot).content_hash}
        if set(body)!=set(prefix)|{'execution','error_type','cost_unknown'} or any(body[k]!=v for k,v in prefix.items()): raise ContractError('worker subject or attempt binding drift')
        literal=_read(root/(job['id']+'.py'))
        if literal!=job['program'].encode('utf-8'): raise ContractError('worker program bytes changed')
        if body['execution'] is None:
            if body['cost_unknown'] is not True or not isinstance(body['error_type'],str) or not body['error_type']: raise ContractError('lost unknown worker cost')
        else:
            receipt=ExecutionReceipt.parse(body['execution']); artifact=receipt.artifact
            if (body['error_type'] is not None or body['cost_unknown'] is not False or receipt.identity.data()!=material.data()['identity']): raise ContractError('execution subject or cost changed')
            if artifact is not None and (Path(artifact.path)!=(root/(job['id']+'.py')).absolute() or artifact.sha256!=_hash(literal) or artifact.byte_count!=len(literal)): raise ContractError('receipt differs from actual program artifact')
            if receipt.status != 'rejected':
                argv=receipt.record.data().get('argv')
                if not isinstance(argv,list) or len(argv)<6 or not isinstance(argv[5],str) or not re.fullmatch('research-loop-[0-9a-f]{20}',argv[5]): raise ContractError('missing actual bounded Docker invocation')
                expected_argv=['docker','run','--pull','never','--name',argv[5],'--rm','--network','none','--read-only',
                    '--user','1000:1000','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--pids-limit','128',
                    '--memory','1g','--cpus','1.0','--cap-drop','ALL','--security-opt','no-new-privileges']
                for key in sorted(inputs): expected_argv.extend(['-v',DockerExecutionBroker._mount_source(inputs[key].absolute())+':/input/'+key+':ro'])
                expected_argv.extend(['-v',DockerExecutionBroker._mount_source((root/(job['id']+'.py')).absolute())+':/task/analysis.py:ro',image,'python3','/task/analysis.py'])
                if argv!=expected_argv: raise ContractError('actual Docker program/input mounts or hard resource limits drift')
            if receipt.status in {'succeeded','failed','timed_out'}:
                if artifact is None or receipt.record.data().get('input_artifacts')!={a['artifact']['artifact_id']:a['artifact'] for a in material.data()['public_artifacts']}: raise ContractError('worker receipt input set changed')
            if receipt.status in {'succeeded','failed'} and (type(receipt.record.data().get('exit_code')) is not int or (receipt.record.data()['exit_code']==0)!=(receipt.status=='succeeded')): raise ContractError('worker status contradicts actual exit')
    for e in events:
        kind=e['kind']; job=e.get('job')
        if kind=='enqueue':
            if job not in jobs or job in enqueued or e['run_id']!=returns[job]['run_id']: raise ContractError('duplicate/foreign enqueue')
            enqueued.append(job)
        elif kind=='claim':
            ready=[k for k in jobs if statuses[k]=='pending' and all(statuses[d]=='complete' for d in jobs[k]['dependencies'])
                and not any(set(jobs[k]['resources'])&set(jobs[a]['resources']) for a in active)]
            if enqueued!=list(jobs) or not ready or job!=ready[0] or len(active)>=(2 if 'M8' in enabled else 1) or e['run_id']!=returns[job]['run_id'] or type(e['attempt']) is not int or e['attempt']!=1: raise ContractError('FIFO, atomic claim, dependency or resource exclusion violated')
            statuses[job]='leased';active.add(job);peak=max(peak,len(active))
        elif kind=='start':
            if job not in active or job in starts: raise ContractError('worker started without exclusive lease')
            starts[job]=e['time_ns']
        elif kind=='finish':
            if job not in starts or job in finished or e['return_digest']!=_record(returns[job]).content_hash: raise ContractError('worker return binding changed')
            finished.add(job);ends[job]=e['time_ns'];finish_order.append(job)
        elif kind=='complete':
            if job not in active or job not in finished or e['return_digest']!=_record(returns[job]).content_hash: raise ContractError('completion without actual return')
            statuses[job]='complete';active.remove(job)
        elif kind=='barrier_refused':
            if 'M8' not in enabled or e['unfinished']!=sum(v!='complete' for v in statuses.values()) or e['unfinished']<=0: raise ContractError('invented barrier refusal')
            barrier_count+=1
        elif kind=='merge':
            expected_merge=list(jobs) if 'M8' in enabled else [k for k in jobs if statuses[k]=='complete' and k not in visible]
            if e['jobs']!=expected_merge or any(statuses[k]!='complete' or k in visible for k in e['jobs']): raise ContractError('merge exposed unfinished or duplicate result')
            visible.extend(e['jobs'])
        else: raise ContractError('unknown phase event')
    if visible!=list(jobs) or active or len(starts)!=2 or len(ends)!=2 or any(v!='complete' for v in statuses.values()): raise ContractError('incomplete phase must not disappear')
    if 'M8' in enabled:
        if barrier_count!=1 or DockerExecutionBroker._has_link_component(root/'queue.sqlite'): raise ContractError('barrier evidence or database invalid')
        # Every scheduler operation closes its connection; WAL must be checkpointed
        # before immutable SQLite inspection (which cannot create journal files).
        if any((root/('queue.sqlite'+suffix)).exists() for suffix in ('-wal','-shm')):
            raise ContractError('scheduler writer or uncheckpointed state remains')
        with closing(sqlite3.connect((root/'queue.sqlite').absolute().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.row_factory=sqlite3.Row; rows=[dict(r) for r in db.execute('SELECT * FROM runs ORDER BY fifo')]
            if len(rows)!=2 or db.execute('SELECT reserved FROM budget WHERE id=1').fetchone()[0]!=2: raise ContractError('scheduler lost attempts or costs')
            if ([tuple(r) for r in db.execute('SELECT * FROM scheduler_meta')]!=[('limits',_record({'max_concurrency':2,'total_budget':2}).encoded)]
                    or [tuple(r) for r in db.execute('SELECT * FROM experiments')]!=[(experiment,_record(snapshot).content_hash)]):
                raise ContractError('scheduler limit or experiment binding drift')
            for index,(row,job) in enumerate(zip(rows,jobs.values())):
                if (row['experiment_id']!=experiment or row['fifo']!=index+1 or row['task_id']!=job['id'] or row['run_id']!=returns[job['id']]['run_id'] or row['status']!='merged'
                        or row['attempt']!=1 or row['cost_units']!=1 or row['worker_id'] is not None or row['lease_until'] is not None
                        or any(row[k] is not None for k in ('termination_receipt','invalidation_reason','parent_run_id'))
                        or json.loads(row['snapshot'])!=snapshot or row['snapshot_hash']!=_record(snapshot).content_hash
                        or json.loads(row['dependencies'])!=job['dependencies'] or json.loads(row['resources'])!=job['resources']
                        or json.loads(row['receipt'])!=returns[job['id']] or row['receipt_id']!=_record(returns[job['id']]).content_hash): raise ContractError('actual SQLite state differs from replayed work')
    elif (root/'queue.sqlite').exists(): raise ContractError('serial baseline invented durable state')
    public=[]; succeeded=True; residual=[]
    for job in jobs:
        receipt=ExecutionReceipt.parse(returns[job]['execution']) if returns[job]['execution'] else None
        if receipt is None or receipt.status!='succeeded': succeeded=False
        record=receipt.record.data() if receipt else {}
        if receipt and receipt.status=='timed_out' and record.get('cleanup',{}).get('removed') is not True: residual.append(job)
        public.append({'binding':job,'receipt_binding':receipt.content_hash if receipt else None,
            'status':receipt.status if receipt else 'unknown','stdout':record.get('stdout',''),'stderr':record.get('stderr','')})
    wall=max(ends.values())-min(starts.values()); overlap=max(0,min(ends.values())-max(starts.values()))
    return _record({'schema':'exploration-scheduler-phase-receipt-v1','cell_binding':_record(cell.data()).content_hash,
        'material_digest':material.record.content_hash,'selection':chosen.data(),'events_sha256':_hash(_read(root/'events.jsonl')),
        'return_digests':{k:_record(v).content_hash for k,v in returns.items()},'actual_docker_attempts':len(starts),
        'execution_units_reserved':2,'unknown_cost_attempts':sum(r['cost_unknown'] for r in returns.values()),
        'completion_order':finish_order,'fifo_order':list(jobs),'peak_dispatches':peak,
        'peak_leases':peak if 'M8' in enabled else 0,'overlap_ns':overlap,'wall_ns':wall,
        'jobs_per_second':len(ends)/(wall/1e9) if wall else None,'remaining_leases':list(active),'residual_containers':residual,
        'status':'succeeded' if succeeded and not residual else 'failed','public':{'observations':public}})


def verify_phase(*,material,cell,objective,root,image,timeout_seconds,inputs,selected_job_id=None):
    expected=_phase_projection(material,cell,objective,root,image,timeout_seconds,inputs,selected_job_id)
    if json.loads(_read(root/'receipt.json'))!=expected.data(): raise ContractError('phase receipt differs from actual replay')
    return expected


@dataclass(frozen=True)
class ExplorationSchedulerResult:
    cell: object
    runtime: object
    solver: object
    joint_mechanism: FrozenRecord | None
    phase: FrozenRecord


def _joint(phase,material):
    joint=_record({'schema':'public-combination-context-v1','material':phase.data()['public']})
    if (_private_arm_marker(joint.data()) or re.search(r'M[1-9]|Q\d+\.\d+|expected_correct|[A-Z]:[\\/]',joint.encoded)
            or len(joint.encoded.encode())>material.data()['context_budget_bytes']):
        raise ContractError('job output violates frozen public context bounds')
    return joint


def _validate(panel,cell,task,scenario,package,material):
    if (cell not in panel.cells or panel.obligation_id!=OBLIGATION or task.identity!=cell.identity
            or task.content_hash!=cell.task_digest or package.digest!=cell.package_digest
            or material.data()['task_digest']!=task.content_hash or material.data()['identity']!=task.identity.data()
            or panel.design!=registered_design(cell.runtime_arm.data()['baseline_digest'])
            or scenario.content_hash!=cell.scenario_digest or scenario.data()!= {'schema':'exploration-scheduler-scenario-v1',
                'obligation_id':OBLIGATION,'design_digest':panel.design.content_hash,'task_digest':task.content_hash,
                'replicate':cell.replicate,'material_digest':material.record.content_hash}):
        raise ContractError('phase does not bind exact registered cell/task/scenario/package')


def run_exploration_scheduler_cell(*,panel,cell,task,scenario,package,material,objective,sidecar,public_inputs,image,broker,model,audit_verifier,timeout_seconds=20):
    _validate(panel,cell,task,scenario,package,material);check_inputs(material,task,broker,public_inputs)
    if sidecar.exists() or type(timeout_seconds) is not int or not 1<=timeout_seconds<=120: raise ContractError('unused cell and bounded timeout required')
    session=RunSession(task,package_digest=package.digest,arm=cell.runtime_arm,objective=objective,slots=SLOTS,
        execution_limit=1,sidecar=sidecar/'runtime',verifier=audit_verifier,required_audit=('measurement',),context_budget=material.data()['context_budget_bytes'])
    phase=run_phase(material=material,cell=cell,objective=objective,root=sidecar/'phase',broker=broker,inputs=public_inputs,image=image,timeout_seconds=timeout_seconds)
    session._record('exploration_scheduler_phase',{'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(sidecar/'phase/receipt.json'))})
    joint=None;solver=None
    try:
        if phase.data()['status']!='succeeded': raise ContractError('auxiliary execution failed')
        joint=_joint(phase,material)
        session._record('exploration_scheduler_joint',{'joint':joint.data()})
        solver=run_benchmark_solve_in_session(session=session,workflow=ModularWorkflow(session),public_inputs=public_inputs,
            image=image,broker=broker,model=model,analysis_slot=SLOTS[0],final_slot=SLOTS[1],joint_mechanism=joint,
            panel_cell_binding=_record(opaque_panel_cell_binding(cell)),driver_id=OBLIGATION,timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:_close_failure(session,cell,scenario,exc)
    return ExplorationSchedulerResult(cell,_runtime(cell,session,joint,'succeeded' if solver and solver.status=='execution_succeeded' else 'failed'),solver,joint,phase)


def verify_exploration_scheduler_cell(result,*,panel,task,scenario,package,material,public_inputs,broker,image,timeout_seconds):
    if type(result) is not ExplorationSchedulerResult: raise ContractError('typed phase result required')
    _validate(panel,result.cell,task,scenario,package,material);check_inputs(material,task,broker,public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime,result.cell)
    path=result.runtime.trace_path; events=_read_events(path);objective=_record(events[0]['data']['objective'])
    phase=verify_phase(material=material,cell=result.cell,objective=objective,root=path.parent.parent/'phase',image=image,timeout_seconds=timeout_seconds,inputs=public_inputs)
    if phase!=result.phase: raise ContractError('returned phase differs from immutable sidecar')
    bindings=[e for e in events if e['stage']=='exploration_scheduler_phase']
    expected_binding={'phase_digest':phase.content_hash,'phase_receipt_sha256':_hash(_read(path.parent.parent/'phase/receipt.json'))}
    if len(bindings)!=1 or bindings[0]['data']!=expected_binding: raise ContractError('runtime did not bind actual phase sidecar')
    requests=[e for e in events if e['stage']=='model_request']
    if tuple(e['data']['request']['slot'] for e in requests)!=SLOTS[:len(requests)] or any(_private_arm_marker(e['data']['request']) for e in requests): raise ContractError('public request sequence or label isolation drift')
    if requests and events.index(bindings[0])>=events.index(requests[0]): raise ContractError('phase was attached after model use')
    try: joint=_joint(phase,material)
    except ContractError: joint=None
    if result.solver is None:
        if requests or result.runtime.status!='failed' or (phase.data()['status']=='succeeded' and joint is not None): raise ContractError('missing solver does not retain an actual failed prerequisite')
    else:
        if phase.data()['status']!='succeeded' or joint is None or result.joint_mechanism!=joint or result.solver.session.sidecar!=path.parent: raise ContractError('solver consumed foreign/failed phase')
        joints=[e for e in events if e['stage']=='exploration_scheduler_joint']
        if len(joints)!=1 or joints[0]['data']!={'joint':joint.data()} or events.index(joints[0])<=events.index(bindings[0]) or requests and events.index(joints[0])>=events.index(requests[0]):
            raise ContractError('joint must follow verified phase and precede actual model call')
        state=_solver_journal_state(events);_compare_solver_result(result.solver,state);_verify_solver_files(state,events,path,material)
        if result.runtime.status!=('succeeded' if state['status']=='execution_succeeded' else 'failed'): raise ContractError('solver failure status was changed')
        for event in requests:
            context=event['data']['request']['module_context']
            if context.get('joint_mechanism')!=joint.data() or context.get('joint_mechanism_digest')!=joint.content_hash: raise ContractError('solver request omitted actual work outputs')
    return _record({'status':result.runtime.status,'engineering_verified':True,'phase_digest':phase.content_hash,'scientific_validity':'not_measured'})


def issue_exploration_scheduler_score_input(*,authority,result,panel,**kwargs):
    from evaluation.modular.combination_scoring import _score_input_payload
    verify_exploration_scheduler_cell(result,panel=panel,**kwargs)
    return authority.issue(_score_input_payload(panel,result).data())
