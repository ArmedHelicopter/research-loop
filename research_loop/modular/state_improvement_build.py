"""History-only state operations followed by a real restricted candidate build.

Hashes bind a caller-frozen engineering history; neither execution nor a source
authority's MAC is a scientific qualification. Qualification is replayed from
its separately signed, subject-bound assessments.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, check_material_inputs
from research_loop.modular.lineage_combination_driver import _transition, _MemoryLog, _read_events
from research_loop.modular.metaprogram_training import (
    FrozenTrainHistory, _builder, _checked_build, _projection, _exclusive, _sha, _path, _read_record,
    _Journal, _phase_rows, _safe_call)
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest, FrozenBuilderVersion, RestrictedBuilderPort, BuilderRunReceipt
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.context import ContextCache, ContextBuilder
from research_loop.modular.runtime import RunSession, verify_trace
from research_loop.modular.workflow import ModularWorkflow
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical
from research_loop.modular.phase_provider import PhaseProviderScope, PhaseProviderLedger

PROPOSAL_INSTRUCTION = ('Propose a bounded emit_literal_change_v1 builder using the supplied existing public training observations. '
    'Return exactly entrypoint, surface, key and value. Use prompt/instructions or memory/lesson. '
    'Give useful reusable analysis guidance; do not propose tasks, scorers, tools, source paths or activation operations.')


def material_class(pair):
    return FrozenAdmissionMaterial if pair == 'pair:M1+M9' else FrozenLineageMaterial


def check_history(history, material, broker, inputs):
    if type(history) is not FrozenTrainHistory or type(material) not in (FrozenAdmissionMaterial, FrozenLineageMaterial):
        raise ContractError('exact frozen history and state types required')
    history.verify(); check_material_inputs(material, history.task, broker, inputs)
    executions=[r['data']['receipt'] for r in _read_events(history.trace_path) if r['stage']=='execution_result']
    expected={r['artifact']['artifact_id']:r['artifact'] for r in material.data()['public_artifacts']}
    if len(executions)!=1 or executions[0]['record'].get('input_artifacts')!=expected:
        raise ContractError('history material CSV differs from the original executed history inputs')
    try: observations = json.loads(history.binding.data()['public']['observations']['stdout'])
    except (ValueError, TypeError) as exc: raise ContractError('history must expose bounded keyed observations from its actual execution') from exc
    if not isinstance(observations, dict): raise ContractError('history observation map required')
    for row in material.data()['originals']:
        if (row['root_material'] != {'history_digest': history.binding.content_hash, 'observation_key': row['key']}
                or observations.get(row['key']) != row['content']):
            raise ContractError('state observation does not originate in the exact frozen history stdout')


def qualifier_check(pair, material, qualifier):
    if (type(material) is not material_class(pair)
            or type(qualifier) is not (AdmissionMaterialVerifier if pair == 'pair:M1+M9' else DualMaterialVerifier)):
        raise ContractError('pair requires exact state material and qualifier types')


def build_binding(plan_digest, recipe):
    return FrozenRecord.from_dict({'cell_digest':FrozenRecord.from_dict({'schema':'state-improvement-build-binding-v1',
        'plan_digest':plan_digest,'recipe':recipe}).content_hash,'scenario_digest':plan_digest})


def proposal_context(history, transition, binding):
    # Raw history stdout, other proposals and target public tasks are excluded.
    return FrozenRecord.from_dict({'schema':'state-improvement-history-context-v1',
        'history_binding':history.binding.content_hash, 'proposal_binding':binding.content_hash,
        'state_projection':transition.data()['public']})


def qualification_semantics(material, qualifier, path, binding):
    if type(material) is not FrozenAdmissionMaterial: return None
    return FrozenRecord.from_dict({'material_digest':material.record.content_hash,
        'qualifier':qualifier.binding().data(),
        'assessments':qualifier.assessments(material,path,cell_binding=binding)})


@dataclass(frozen=True)
class BuildResult:
    root: Path
    record: FrozenRecord


def run_build(*, recipe, plan_digest, history, material, qualifier, parent, fixed_builder,
              broker, inputs, model, audit_verifier, root):
    root.mkdir(parents=True, exist_ok=False)
    phase=_Journal(root/'phase.jsonl'); binding=build_binding(plan_digest,recipe)
    phase.append('phase_lock',{'binding':binding.data(),'allocation':{'source_calls':2,'model_calls':1,'builder_executions':1}})
    status='failed'; reason=None; candidate=None; session=None
    try:
        qualifier_check(recipe['pair'],material,qualifier);check_history(history,material,broker,inputs)
        source=qualifier.qualify(material,root/'source'/'source-verification.json',cell_binding=binding)
        if any(c['cost_unknown'] for c in json.loads((root/'source'/'source-verification.json').read_bytes())['calls']):
            raise ContractError('unknown source cost blocks the build proposal')
        check_history(history,material,broker,inputs)
        q=qualifier.assessments(material,root/'source'/'source-verification.json',cell_binding=binding) if type(material) is FrozenAdmissionMaterial else None
        session=RunSession(history.task,package_digest=parent.digest,arm=FrozenRecord.from_dict(recipe['arm']),
            objective=FrozenRecord.from_dict(history.binding.data()['lock']['objective']), slots=('builder_proposal',),
            execution_limit=0,sidecar=root/'proposal',verifier=audit_verifier,required_audit=('measurement',),
            context_budget=material.data()['context_budget_bytes'])
        workflow=ModularWorkflow(session)
        transition=_transition(session.evidence,session.claims,session.cache,material,workflow.enabled,q)
        session._record('state_improvement_history',{'transition':transition.data(),'source_sha256':source,
            'history_binding':history.binding.content_hash})
        def charged(request):
            phase.append('model_reservation',{'request_digest':request.content_hash,'slot':request.data()['slot']})
            before=model.cursor() if type(model) is PhaseProviderScope else len(model.ledger['calls'])
            try: return model(request)
            finally: phase.append('model_charge',{'request_digest':request.content_hash,
                'provider_calls':([c.data() for c in model.calls_since(before)] if type(model) is PhaseProviderScope
                    else [_safe_call(c) for c in model.ledger['calls'][before:]])})
        response=session.invoke('builder_proposal',charged,instruction=PROPOSAL_INSTRUCTION,
            module_context=proposal_context(history,transition,binding))
        proposed=_builder(FrozenBuilderVersion(response))
        session._record('state_improvement_proposal_terminal',{'response_digest':response.content_hash,'builder_digest':proposed.digest})
        session._terminal=True
        check_history(history,material,broker,inputs)
        selected=proposed if 'M9' in recipe['arm']['enabled'] else _builder(fixed_builder)
        _exclusive(root/'builder.json',selected.record)
        manifest=TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
        phase.append('builder_request',{'selected_builder_digest':selected.digest,'parent_digest':parent.digest,'search_cost':1})
        candidate,receipt=RestrictedBuilderPort().execute(selected,manifest,parent,expected_builder_digest=selected.digest,
            expected_entrypoint=selected.entrypoint,search_cost=1)
        phase.append('builder_returned',{'candidate':candidate.record.data(),'receipt':receipt.record.data()})
        _checked_build(candidate,receipt,selected,parent)
        _exclusive(root/'candidate.json',candidate.record);_exclusive(root/'builder-receipt.json',receipt.record)
        phase.append('builder_result',{'candidate_digest':candidate.digest,'receipt_digest':receipt.record.content_hash})
        status='succeeded'
    except Exception as exc:
        reason=type(exc).__name__
        if session is not None and not session._terminal:
            session.controller_failure(driver_id='state-improvement-builder',error_type=reason,panel_cell={'recipe_digest':FrozenRecord.from_dict(recipe).content_hash})
        phase.append('phase_failure',{'error_type':reason})
    phase.append('stage_result',{'status':status,'reason':reason})
    files={str(p.relative_to(root)).replace('\\','/'):_sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    native=type(model) is PhaseProviderScope
    result=BuildResult(root,FrozenRecord.from_dict({**({'provider_scope':model.scope_id} if native else {}),
        'schema':'state-improvement-build-receipt-v2' if native else 'state-improvement-build-receipt-v1','recipe':recipe,
        'plan_digest':plan_digest,'status':status,'reason':reason,'candidate_digest':candidate.digest if status=='succeeded' else None,
        'files':files}))
    _exclusive(root/'build-receipt.json',result.record)
    return result


@dataclass(frozen=True)
class FrozenProviderLedger:
    path: Path
    record: FrozenRecord

    @classmethod
    def freeze(cls,model,path):
        original=FrozenRecord.from_dict(json.loads(_path(model.ledger_path).read_bytes()))
        if original.data()!=model.ledger: raise ContractError('provider memory and persistent ledger differ')
        _exclusive(path,original)
        return cls(path,original)

    def verify(self):
        if _path(self.path).read_bytes()!=(self.record.encoded+'\n').encode('utf-8'): raise ContractError('sealed original provider ledger drift')

    def bind_events(self,events):
        self.verify(); calls=self.record.data()['calls'];used=[]
        requests=[r['data'] for r in events if r['stage']=='model_request']
        responses={r['data']['request_digest']:r['data'] for r in events if r['stage']=='model_response'}
        for event in requests:
            request=FrozenRecord.from_dict(event['request'])
            matches=[c for c in calls if c['request_hash']==request.content_hash]
            if len(matches)!=1 or matches[0]['id'] in used: raise ContractError('provider request lacks one original reserved call')
            call=matches[0];used.append(call['id'])
            if call['slot']!=request.data()['slot']: raise ContractError('provider slot differs')
            response=responses.get(request.content_hash)
            if response is not None:
                if (call['status']!='succeeded' or call['usage'] is None
                        or call['output_hash']!=FrozenRecord.from_dict(response['response']).content_hash):
                    raise ContractError('runtime response differs from original provider output or cost')
            elif call['status']=='succeeded': raise ContractError('original provider success omitted from journal')
        return used


def verify_build(result, *, recipe, plan_digest, history, material, qualifier, parent, fixed_builder, broker, inputs, ledger):
    if type(result) is not BuildResult: raise ContractError('typed build result required')
    if type(ledger) not in (FrozenProviderLedger,PhaseProviderLedger): raise ContractError('exact original build provider ledger required')
    b=result.record.data();root=result.root
    native=type(ledger) is PhaseProviderLedger
    if (_path(root/'build-receipt.json').read_bytes()!=(result.record.encoded+'\n').encode('utf-8')
            or set(b)!=({'schema','recipe','plan_digest','status','reason','candidate_digest','files'}|({'provider_scope'} if native else set()))
            or b['schema']!=('state-improvement-build-receipt-v2' if native else 'state-improvement-build-receipt-v1')
            or b['recipe']!=recipe or b['plan_digest']!=plan_digest
            or b['status']!='succeeded'):
        raise ContractError('successful original build receipt required')
    actual={str(p.relative_to(root)).replace('\\','/'):_sha(_path(p).read_bytes())
        for p in root.rglob('*') if p.is_file() and p!=root/'build-receipt.json'}
    if actual!=b['files']: raise ContractError('original build side effects drift')
    qualifier_check(recipe['pair'],material,qualifier);check_history(history,material,broker,inputs)
    binding=build_binding(plan_digest,recipe);sourcepath=root/'source'/'source-verification.json'
    source=qualifier.replay(material,sourcepath,cell_binding=binding)
    if any(c['cost_unknown'] for c in json.loads(sourcepath.read_bytes())['calls']):
        raise ContractError('unknown source cost blocks completed build replay')
    q=qualifier.assessments(material,sourcepath,cell_binding=binding) if type(material) is FrozenAdmissionMaterial else None
    evidence=EvidenceLedger(history.task.identity);claims=ClaimLedger(evidence)
    evidence._log=_MemoryLog();claims._log=_MemoryLog()
    enabled=set(recipe['arm']['enabled'])
    transition=_transition(evidence,claims,ContextCache(),material,enabled,q)
    events=_read_events(root/'proposal'/'trace.jsonl');lock=events[0]['data'];verify_trace(root/'proposal'/'trace.jsonl')
    if (lock['task_digest']!=history.task.content_hash or lock['identity']!=history.task.identity.data() or lock['package_digest']!=parent.digest or lock['arm']!=recipe['arm']
            or lock['slots']!=['builder_proposal'] or lock['execution_limit']!=0
            or lock['objective']!=history.binding.data()['lock']['objective']
            or lock['context_budget']!=material.data()['context_budget_bytes'] or lock['required_audit']!=['measurement']):
        raise ContractError('proposal lock allocation, history or package drift')
    trans=[e for e in events if e['stage']=='state_improvement_history']
    requests=[e for e in events if e['stage']=='model_request'];responses=[e for e in events if e['stage']=='model_response']
    if (len(trans)!=1 or trans[0]['data']!={'transition':transition.data(),'source_sha256':source,'history_binding':history.binding.content_hash}
            or len(requests)!=1 or len(responses)!=1 or events.index(trans[0])>=events.index(requests[0])
            or _read_events(root/'proposal'/'evidence.jsonl')!=evidence._log.rows
            or _read_events(root/'proposal'/'claims.jsonl')!=claims._log.rows):
        raise ContractError('proposal state/qualification journals differ from replay')
    request=requests[0]['data']['request']
    context=ContextBuilder(history.task.identity,budget_bytes=material.data()['context_budget_bytes']).build(
        canonical(history.task.payload.data()),evidence,claims,mode='candidate' if 'M3' in enabled else 'baseline',baseline_summary='').public_data()
    if (request['instruction']!=PROPOSAL_INSTRUCTION or request['module_context']!=proposal_context(history,transition,binding).data()
            or request['context']!=context or request['task']!=history.task.data()
            or request['slot']!='builder_proposal' or request['execution_feedback']!=[]
            or set(request)!={'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}):
        raise ContractError('proposal request leaks or omits frozen consumed history')
    if native:
        if b['provider_scope']!='build:'+FrozenRecord.from_dict(recipe).content_hash: raise ContractError('original build provider scope differs')
        used=ledger.bind_events(events,scope_id=b['provider_scope'],require_eligible=False)
        provider_calls=[c.data() for c in ledger.calls_for_scope(b['provider_scope'])]
    else:
        used=ledger.bind_events(events)
        provider_calls=[_safe_call(c) for c in ledger.record.data()['calls'] if c['id'] in used]
    proposed=_builder(FrozenBuilderVersion(FrozenRecord.from_dict(responses[0]['data']['response'])))
    selected=proposed if 'M9' in enabled else _builder(fixed_builder)
    if events[-1]['stage']!='state_improvement_proposal_terminal' or events[-1]['data']!={
            'response_digest':proposed.record.content_hash,'builder_digest':proposed.digest}:
        raise ContractError('proposal terminal differs from original provider response')
    if _read_record(root/'builder.json')!=selected.record: raise ContractError('selected builder violates frozen off/on policy')
    candidate=CandidatePackage(_read_record(root/'candidate.json'));receipt=BuilderRunReceipt(_read_record(root/'builder-receipt.json'))
    _checked_build(candidate,receipt,selected,parent)
    if candidate.digest!=b['candidate_digest']: raise ContractError('candidate was replaced after build')
    phases=_phase_rows(root/'phase.jsonl')
    if [p['stage'] for p in phases]!=['phase_lock','model_reservation','model_charge','builder_request','builder_returned','builder_result','stage_result']:
        raise ContractError('build side effect order differs')
    expected=[{'binding':binding.data(),'allocation':{'source_calls':2,'model_calls':1,'builder_executions':1}},
        {'request_digest':FrozenRecord.from_dict(request).content_hash,'slot':'builder_proposal'},
        {'request_digest':FrozenRecord.from_dict(request).content_hash,'provider_calls':provider_calls},
        {'selected_builder_digest':selected.digest,'parent_digest':parent.digest,'search_cost':1},
        {'candidate':candidate.record.data(),'receipt':receipt.record.data()},
        {'candidate_digest':candidate.digest,'receipt_digest':receipt.record.content_hash}, {'status':'succeeded','reason':None}]
    if [p['data'] for p in phases]!=expected: raise ContractError('builder journal differs from independent artifacts/provider ledger')
    return candidate
