"""Explicit native provider envelope for the separate Q3.2 execution route."""
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession,PhaseProviderLedger
from research_loop.modular.train_provider import GrokTrainProvider, GrokHeadlessTrainProvider
from research_loop.modular.train_provider_preflight import validate_native_declaration,native_provider_preflight
from research_loop.modular.ordinary_provider import final_provider_gate
from research_loop.modular.runtime import verify_trace
from research_loop.ontology import ContractError,digest


def native_budget():
    from research_loop.modular.q32_execution import BUDGET
    return {k:v for k,v in BUDGET.items() if k not in {'model_token_stop_threshold','model_timeout_seconds'}}|{
        'native_lifetime_seconds':60,'observed_main_token_cap':131072,
        'terminal_policy':'stop_entire_run_after_any_unknown_main_or_original_fault'}


def validate_provider_map(providers,tasks,budget):
    from research_loop.modular.q32_execution import SLOTS,PROGRAM_SCHEMA
    expected={digest({'task':task,'variant':variant}) for task in tasks for variant in ('joint','separate')}
    if type(providers) is not dict or set(providers)!=expected or budget!=native_budget():
        raise ContractError('Q3.2 requires four frozen native cells and its exact run-wide terminal budget')
    for config in providers.values():
        if type(config) is not dict:raise ContractError('Q3.2 requires original immutable provider descriptors')
        body={'schema':'q32-prospective-source-config-v3','provider':config}
        schemas=config.get('native_config',{}).get('schemas',{})
        if set(schemas)!=set(SLOTS) or any(schemas[s]!=PROGRAM_SCHEMA for s in SLOTS[:3]):
            raise ContractError('Q3.2 native response schema allocation differs')
        validate_native_declaration(body,family='q32_execution',schemas=schemas,main_opportunities=4)


def compile_native(compiled,source):
    b=compiled.data();validate_provider_map(source['providers_by_cell'],b['tasks'],source['native_budget'])
    return FrozenRecord.from_dict({k:v for k,v in b.items() if k not in {'model','effort'}}|{
        'schema':'q32-prospective-execution-v2','budget':native_budget(),
        'providers_by_cell':source['providers_by_cell']})


def projected_events(path,compiled,cell):
    """Derive a checked view; never rewrite original runtime event bytes."""
    from research_loop.modular.q32_execution import public_request
    verify_trace(path)
    events=[FrozenRecord(line).data() for line in path.read_text(encoding='utf-8').splitlines()]
    plans=[e for e in events if e['stage']=='q32_plans_frozen']
    if len(plans)!=1 or plans[0]['data']['compiled_digest']!=compiled.content_hash or plans[0]['data']['cell']!=cell:
        raise ContractError('Q3.2 projection lacks original cell/compilation binding')
    derived=[];pending=None;projected=None;bindings=[]
    for event in events:
        data=event['data']
        if event['stage']=='model_request':
            if pending is not None:raise ContractError('overlapping Q3.2 original requests')
            pending=FrozenRecord.from_dict(data['request']);projected=None
            if data['request_digest']!=pending.content_hash:raise ContractError('Q3.2 original request digest differs')
        elif event['stage']=='q32_public_request':
            if pending is None or projected is not None or data!={'original_digest':pending.content_hash,'request':public_request(pending.data())}:
                raise ContractError('Q3.2 public projection differs from original request')
            projected=FrozenRecord.from_dict(data['request'])
            derived.append({'stage':'model_request','data':{'request':projected.data(),'request_digest':projected.content_hash}})
            bindings.append({'original_request_digest':pending.content_hash,'public_request_digest':projected.content_hash,
                'original_public_event_digest':FrozenRecord.from_dict(event).content_hash,'response_digest':None})
        elif event['stage']=='model_response':
            if pending is None or projected is None or data['request_digest']!=pending.content_hash:
                raise ContractError('Q3.2 response differs from original projection pair')
            response=FrozenRecord.from_dict(data['response'])
            derived.append({'stage':'model_response','data':{'request_digest':projected.content_hash,'response':response.data()}})
            bindings[-1]['response_digest']=response.content_hash
            pending=None;projected=None
    if pending is not None and projected is None:raise ContractError('Q3.2 original request has no public projection')
    import hashlib
    receipt=FrozenRecord.from_dict({'schema':'q32-native-public-projection-v1','compiled_digest':compiled.content_hash,
        'cell':cell,'original_trace_path':str(path),'original_trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'bindings':bindings,'derived_events':derived})
    return derived,receipt


def run_native(packets,compiled,export_root,run_root,model_factory,verifier):
    from evaluation.modular.q32_execution_verifier import verify_q32_execution
    from research_loop.modular.q32_execution import Q32ExecutionStage,compare
    from research_loop.modular.benchmarks.execution import DockerExecutionBroker
    from research_loop.modular.train_controller import _label_ancestor,_write
    b=compiled.data();validate_provider_map(b['providers_by_cell'],b['tasks'],b['budget'])
    models=[]
    for i,cell in enumerate(b['cells']):
        config=b['providers_by_cell'][cell['cell_id']]
        model=model_factory(i)
        expected=GrokHeadlessTrainProvider if config['provider_kind']=='grok-headless-public-train-v1' else GrokTrainProvider
        if type(model) is not expected:raise ContractError('Q3.2 native factory requires a closed Grok provider')
        native_provider_preflight({'schema':'q32-prospective-source-config-v3','provider':config},model,
            family='q32_execution',schemas=config['native_config']['schemas'],main_opportunities=4)
        models.append(model)
    roots=[m.backend.root.resolve() for m in models]
    if any(a==z or a in z.parents or z in a.parents for n,a in enumerate(roots) for z in roots[n+1:]):
        raise ContractError('Q3.2 fresh cell provider roots must be mutually disjoint')
    for root in roots:
        if _label_ancestor(root):raise ContractError('Q3.2 model roots cannot inherit evaluation labels')
        if any(root==p or root in p.parents or p in root.parents for p in (Path(export_root).resolve(),Path(run_root).resolve())):
            raise ContractError('Q3.2 provider roots overlap execution or exports')
    run_root.mkdir(parents=True,exist_ok=True);_write(run_root/'compiled.json',b)
    broker=DockerExecutionBroker([export_root,run_root]);packet_by_task={p.task.content_hash:p for p in packets}
    sessions=[];results=[];stopped=False;completed_stages=[]
    def prior_artifacts_healthy():
        healthy=True
        for original_path,original_cell,original_model in completed_stages:
            try:
                verify_q32_execution(original_path,compiled,cell=original_cell)
            except Exception:
                original_model._poison('q32_original_artifact_drift')
                healthy=False
        return healthy
    def blocked(cell):
        task=b['tasks'][cell['task_digest']];plans=[task['plans'][0]]*3 if cell['variant']=='joint' else task['plans'][1:]
        return {'schema':'q32-native-cell-result-v1','cell':cell,'status':'blocked','failure':'prior_native_terminal',
            'rows':[{'ordinal':i,'plan_id':plans[i]['plan_id'],'measurement':measurement,'status':'blocked',
                'execution_digest':None,'receipt':None,'observation':None,'range_membership':compare(plans[i],measurement,None)}
                for i,measurement in enumerate(task['measurements'])],
            'allocated':b['budget'],'model_attempts':0,'execution_attempts':0,'unattempted_executions':3,
            'runtime_result':None,'provider_final_gate':None,'score_eligible':False,'scientific_validated':False,'programme_complete':False}
    for i,(cell,model) in enumerate(zip(b['cells'],models)):
        # Replay all previous cells before a fresh port can dispatch.
        artifacts_healthy=prior_artifacts_healthy()
        stopped=stopped or not artifacts_healthy or any(session.terminal() for session in sessions)
        if stopped:results.append(blocked(cell));continue
        sidecar=run_root/str(i);sidecar.mkdir()
        session=PhaseProviderSession(model,sidecar/'provider-scopes.json');sessions.append(session)
        stage=None;value=None;verification=None;projection=None;failure=None
        try:
            stage=Q32ExecutionStage(compiled,cell,packet_by_task[cell['task_digest']],sidecar=sidecar/'runtime',verifier=verifier)
            with session.scope(cell['cell_id']) as scoped:value=stage.run(scoped,broker)
            try:
                verification=verify_q32_execution(sidecar/'runtime/trace.jsonl',compiled,cell=cell)
                events,projection=projected_events(sidecar/'runtime/trace.jsonl',compiled,cell)
            except ContractError:
                model._poison('q32_original_runtime_projection_fault')
                raise
            _write(sidecar/'public-projection.json',projection.data())
            ledger=session.finish(sidecar/'provider-ledger.json')
            if type(ledger) is not PhaseProviderLedger:raise ContractError('Q3.2 terminal originals cannot authorize measurements')
            ledger.bind_events(events,scope_id=cell['cell_id'],require_eligible=value.data()['failure'] is None)
            completed_stages.append((sidecar/'runtime/trace.jsonl',cell,model))
        except Exception as exc:
            failure=type(exc).__name__;stopped=True
        gate=final_provider_gate(session,sidecar/'final-provider-ledger.json')
        stopped=stopped or session.terminal() or not gate.data()['provider_evidence_eligible']
        row=blocked(cell) if value is None else value.data()
        if value is None and stage is not None:
            # Retained runtime facts remain historical when terminal storage
            # fails. Never erase consumed opportunities to an all-zero row.
            observed=list(stage._rows)
            row.update(rows=observed+row['rows'][len(observed):],
                model_attempts=stage._session._next_call,
                execution_attempts=stage._session._attempts,
                unattempted_executions=3-stage._session._attempts)
        row.update(schema='q32-native-cell-result-v1',status='incomplete' if stopped or row.get('failure') else 'completed',
            failure=failure or row.get('failure'),runtime_result=None if value is None else value.data(),
            provider_final_gate=gate.data(),score_eligible=not stopped and row.get('failure') is None,
            projection_digest=None if projection is None else projection.content_hash,
            execution_verification=None if verification is None else verification.data())
        results.append(row);_write(sidecar/'native-result.json',row)
    artifacts_healthy=prior_artifacts_healthy()
    stopped=stopped or not artifacts_healthy
    gates=[final_provider_gate(session,run_root/f'final-provider-{i}.json') for i,session in enumerate(sessions)]
    eligible=not stopped and len(sessions)==4 and all(g.data()['provider_evidence_eligible'] for g in gates) and all(r['status']=='completed' for r in results)
    for row in results:
        row['schema']='q32-native-cell-result-v2'
        row['historical_cell_score_eligible']=row['score_eligible']
        row['score_eligible']=eligible and row['score_eligible']
    result=FrozenRecord.from_dict({'schema':'q32-native-panel-result-v2','compiled_digest':compiled.content_hash,
        'cell_count':4,'measurement_denominator':12,'results':results,'provider_final_gates':[g.data() for g in gates],
        'status':'completed' if eligible and all(r['status']=='completed' for r in results) else 'incomplete',
        'score_eligible':eligible,'eligible_measurements':12 if eligible else 0,
        'historical_measurements':sum(r['execution_attempts'] for r in results),'run_terminal':not eligible,
        'scientific_validated':False,'programme_complete':False})
    _write(run_root/'panel-result.json',result.data());return result
