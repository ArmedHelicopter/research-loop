"""Read-only replay of source admissions, real ledgers and cached request contexts.

This proves a frozen engineering operation sequence. Caller admission authority
qualification and scientific truth remain separate obligations.
"""
from __future__ import annotations
import json
import re
import stat
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.context import ContextCache
from research_loop.modular.runtime import RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.history_panel_drivers import Q11HistoryDriver, Q12DependencyDriver, _resolve as history_material
from research_loop.modular.support_panel_drivers import Q13RepresentationDriver, Q14SupportDriver, _resolve as support_material
from research_loop.ontology import ContractError, canonical

COVERAGE = frozenset({'Q1.1','Q1.2','Q1.3','Q1.4'})
_DRIVERS = {'Q1.1':Q11HistoryDriver,'Q1.2':Q12DependencyDriver,'Q1.3':Q13RepresentationDriver,'Q1.4':Q14SupportDriver}
_LABEL = re.compile(r'(?i)(?:Q[1-9][.]\d|q1[1-4][_-]|\bM[1-9](?:off|on|[_+-])|\b(?:one_withdrawn|all_withdrawn|summary_only|expected_correctness|arm_id)\b)')


def validate_lineage_material(*, cell, task, scenario):
    resolver = history_material if cell.coverage_id in {'Q1.1','Q1.2'} else support_material
    material = resolver(None, task, scenario, cell.coverage_id, cell.variant).data()
    # Controller selectors stay in the frozen bundle, never in a public value.
    for key in ('schema','experiment_id','identity'):
        material.pop(key, None)
    if _LABEL.search(canonical(material)):
        raise ContractError('public lineage material contains controller labels')
    return material


class _Log:
    def __init__(self): self.rows=[]
    def append(self, row): self.rows.append(FrozenRecord.from_dict(dict(row)).data())


class _ReplaySession(RunSession):
    def _record(self, stage, data):
        event=FrozenRecord.from_dict({'sequence':len(self._events),
            'previous':self._events[-1].content_hash if self._events else None,
            'lock_digest':self.lock.content_hash,'stage':stage,'data':data})
        self._events.append(event)
        return event


def _read(path):
    for node in (path,*path.parents):
        if node.exists() and (node.is_symlink() or getattr(node.lstat(),'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ContractError('lineage sidecar cannot use a reparse path')
    if not path.is_file(): raise ContractError('lineage sidecar is missing')
    try:
        lines=path.read_text(encoding='utf-8').splitlines()
        rows=[json.loads(line) for line in lines]
        if any(not isinstance(row,dict) or canonical(row)!=line for row,line in zip(rows,lines)):
            raise ValueError
        return rows
    except (ValueError,UnicodeError) as exc:
        raise ContractError('lineage sidecar is not canonical JSONL') from exc


def _replay(proof, *, cell, task, scenario):
    try:
        return _replay_checked(proof, cell=cell, task=task, scenario=scenario)
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise ContractError('lineage replay has malformed typed material') from exc


def _replay_checked(proof, *, cell, task, scenario):
    if not isinstance(proof,dict) or set(proof)!={'events','evidence_events','claim_events'}:
        raise ContractError('lineage replay proof is malformed')
    validate_lineage_material(cell=cell,task=task,scenario=scenario)
    events=proof['events']
    if not isinstance(events,list) or len(events)<2 or events[0].get('stage')!='objective_lock':
        raise ContractError('lineage replay lacks its real source lock')
    lock=FrozenRecord.from_dict(events[0]['data']); body=lock.data()
    driver_type=_DRIVERS[cell.coverage_id]
    if (body.get('identity')!=task.identity.data() or body.get('task_digest')!=task.content_hash
        or body.get('package_digest')!=cell.package_digest or body.get('arm')!=cell.runtime_arm.data()
        or body.get('slots')!=list(driver_type().slots) or type(body.get('execution_limit')) is not int or body.get('execution_limit')!=0
        or body.get('required_audit')!=['measurement'] or type(body.get('context_budget')) is not int
        or body['context_budget']<1):
        raise ContractError('lineage replay has a foreign run lock')
    session=object.__new__(_ReplaySession)
    session.task=task;session.objective=FrozenRecord.from_dict(body['objective']);session.arm=cell.runtime_arm;session.lock=lock
    session.context_budget=body['context_budget'];session.required_audit=tuple(body['required_audit'])
    session.slots=tuple(body['slots']);session.execution_limit=0
    session.evidence=EvidenceLedger(task.identity);session.claims=ClaimLedger(session.evidence);session.cache=ContextCache()
    session.evidence._log=_Log();session.claims._log=_Log()
    session.executions={};session.admissions={};session.admission_roots={};session._events=[]
    session._next_call=0;session._attempts=0;session._terminal=False;session._research_version=None
    session._record('objective_lock',lock.data())
    workflow=object.__new__(ModularWorkflow);workflow.session=session;workflow.enabled=frozenset(cell.runtime_arm.data()['enabled'])
    workflow.deployment=None;workflow.revealed=None;workflow.frontier_result=None
    admissions=[row['data'] for row in events if row.get('stage')=='modular_workflow' and row['data'].get('stage')=='operation_public_material_admission']
    requests=[row['data'] for row in events if row.get('stage')=='model_request']
    responses=[row['data'] for row in events if row.get('stage')=='model_response']
    admission_index=0;model_index=0
    def admission(public_task, record):
        nonlocal admission_index
        if admission_index>=len(admissions): raise ContractError('lineage replay lacks an actual admission')
        row=admissions[admission_index];admission_index+=1
        if row.get('record')!=record.data() or public_task!=task: raise ContractError('lineage admission subject mismatch')
        receipt=row.get('receipt')
        if not isinstance(receipt,dict): raise ContractError('lineage admission receipt is malformed')
        workflow._trace('operation_public_material_admission_attempt','reserved',record_digest=record.content_hash,
            limits={'max_calls':1},cost_measurement='not_provided_by_caller_port')
        workflow._trace('operation_public_material_admission','executed',record=record.data(),receipt=receipt)
        return receipt
    def model(request):
        nonlocal model_index
        if model_index>=len(requests) or model_index>=len(responses): raise ContractError('lineage replay lacks actual model I/O')
        wanted=requests[model_index]; response=responses[model_index];model_index+=1
        if (wanted!={'request_digest':request.content_hash,'request':request.data()}
            or response.get('request_digest')!=request.content_hash):
            raise ContractError('lineage model context does not match actual ledger replay')
        return FrozenRecord.from_dict(response['response'])
    _,candidate,_=driver_type(admission_port=admission).run(workflow,cell=cell,scenario=scenario,model=model,package=None)
    session.finish(candidate)
    if (admission_index!=len(admissions) or model_index!=len(requests) or model_index!=len(responses)
        or [row.data() for row in session._events]!=events
        or session.evidence._log.rows!=proof['evidence_events'] or session.claims._log.rows!=proof['claim_events']):
        raise ContractError('lineage actual stages or ledger files differ from replay')
    return session, requests[-1]['request']['module_context']


def verify_lineage_trace(*,cell,task,scenario,package,events,sidecar):
    proof={'events':events,'evidence_events':_read(sidecar/'evidence.jsonl'),'claim_events':_read(sidecar/'claims.jsonl')}
    if _read(sidecar/'trace.jsonl')!=events: raise ContractError('lineage trace changed during replay')
    _replay(proof,cell=cell,task=task,scenario=scenario)
    return proof


def _public(value):
    # Strip only the typed ledger receipt fields, never caller observation keys.
    result = FrozenRecord.from_dict(value).data()
    for entry in result["context"]["entries"]["entries"]:
        if entry["kind"] == "evidence":
            entry["payload"].pop("trusted_validator", None)
            entry["payload"].pop("validator_verified", None)
    return result


def project_lineage_material(body, *,cell,task,scenario):
    proof=body.get('lineage_replay')
    session,final_context=_replay(proof,cell=cell,task=task,scenario=scenario)
    if (FrozenRecord.from_dict(proof['events'][-1]).content_hash!=body['runtime_trace_digest']
        or [{'stage':row['data']['stage'],'data':row['data']} for row in proof['events'] if row['stage']=='modular_workflow']!=body['mechanism_stages']):
        raise ContractError('lineage provenance does not bind the replayed trace')
    actual_calls=[];requests={}
    for row in proof['events']:
        data=row['data']
        if row['stage']=='model_request': requests[data['request_digest']]=data['request']
        if row['stage']=='model_response':
            request=requests[data['request_digest']];response=FrozenRecord.from_dict(data['response'])
            actual_calls.append({'slot':request['slot'],'request_digest':data['request_digest'],'request':request,
                'response_digest':response.content_hash,'response':response.data(),'status':'responded'})
    if FrozenRecord.from_dict({'responses':[item['response'] for item in actual_calls], 'terminal':proof['events'][-1]['data']}).content_hash!=body['runtime_output_digest']:
        raise ContractError('lineage provenance has an unbound final output')
    if actual_calls!=body['responses']: raise ContractError('lineage provenance has foreign model responses')
    material={'schema':'public-source-context-state-v1','source_material':final_context.get('history_material',final_context.get('public_support_state')),
        'context':final_context['reconstructed_context']}
    material=_public(material)
    if _LABEL.search(canonical({'material':material,'candidate':actual_calls[-1]['response']})): raise ContractError('lineage projection contains controller labels')
    return material
