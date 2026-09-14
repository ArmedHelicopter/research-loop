"""Versioned native call ownership used by the explicit ordinary controllers."""
from contextlib import contextmanager

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession, PhaseProviderLedger
from research_loop.modular.train_provider_preflight import (native_envelope, response_schemas,
    native_provider_preflight, scorer_process_preflight)
from research_loop.ontology import ContractError


def family_service_preflight(config, model, service, execution_authority, scorer_keys, *, family):
    body=config.data()
    if native_envelope(body,family):
        native_provider_preflight(body,model,family=family,schemas=response_schemas(body,family=family),
            main_opportunities=body['provider']['limits']['main_opportunities'])
        scorer_process_preflight(body,service,execution_authority,scorer_keys,family=family)
    else:
        from research_loop.modular.combination_train_controller import _service_preflight
        _service_preflight(config,model,service,execution_authority,scorer_keys)


def model_root(model, *, native):
    return model.backend.root if native else model.root


def allocation_fields(body, *, native):
    if native:
        return {'provider':body['provider'],
            'allocated_main_opportunities':body['provider']['limits']['main_opportunities']}
    return {'max_model_calls':body['max_calls'],'max_model_tokens':body['max_tokens']}


def provider_usage(session,model):
    if session is not None:return session.usage().data()
    from research_loop.modular.combination_train_controller import _usage
    return _usage(model)


def provider_terminal(session,model):
    return session.terminal() if session is not None else model.ledger['usage_incomplete']


def unused_main_opportunities(session,model,body):
    if session is None:return body['max_calls']-len(model.ledger['calls'])
    usage=session.usage().data()
    if usage['schema']=='public-train-provider-terminal-snapshot-v1':return None
    return body['provider']['limits']['main_opportunities']-usage['main_opportunities']


def cell_scope_id(cell):return FrozenRecord.from_dict(cell.data()).content_hash


@contextmanager
def provider_scope(session,model,cell):
    if session is None:
        yield model
    else:
        with session.scope(cell_scope_id(cell)) as scoped:
            yield scoped


def bind_runtime_originals(session,cell,runtime,path):
    if session is None:return None
    ledger=session.finish(path)
    if type(ledger) is not PhaseProviderLedger:
        raise ContractError('terminal provider accounting cannot authorize runtime scoring')
    events=[FrozenRecord(line).data() for line in runtime.trace_path.read_text(encoding='utf-8').splitlines()]
    ledger.bind_events(events,scope_id=cell_scope_id(cell))
    return ledger.record.content_hash


def bind_singleton_originals(session,cell,result,path,*,linked):
    ledger=session.finish(path)
    if type(ledger) is not PhaseProviderLedger or result is None:
        raise ContractError('native singleton lacks a checked original runtime')
    runtime=result.mechanism.runtime if linked else result.runtime
    paths=[runtime.trace_path]
    if linked and result.solver is not None:
        paths.append(result.solver.session.sidecar/'trace.jsonl')
    events=[FrozenRecord(line).data() for trace in paths for line in trace.read_text(encoding='utf-8').splitlines()]
    ledger.bind_events(events,scope_id=cell_scope_id(cell),require_eligible=runtime.status=='succeeded')
    return ledger.record.content_hash


def final_provider_gate(session,path):
    if session is None:return None
    final=session.finish(path)
    eligible=False;verification=None
    if type(final) is PhaseProviderLedger:
        verification=final.verify()
        eligible=verification.data()['score_eligible'] is True
    else:
        verification=final.verify()
    return FrozenRecord.from_dict({'schema':'ordinary-native-final-provider-gate-v1',
        'provider_evidence_eligible':eligible,'final_record_schema':final.record.data()['schema'],
        'final_record_digest':final.record.content_hash,'verification':verification.data(),
        'current_accounting':session.usage().data()})


def final_score_fields(gate,scores):
    if gate is None:return {}
    return {'provider_final_gate':gate.data(),
        'eligible_scored_cells':len(scores) if gate.data()['provider_evidence_eligible'] else 0,
        'historical_score_receipt_digests':[score.receipt.content_hash for score in scores]}


def unavailable_provider_contrast(panel,gate):
    return FrozenRecord.from_dict({'schema':'ordinary-native-inconclusive-contrast-v1',
        'panel_digest':panel.digest,'status':'inconclusive',
        'reason':'provider_final_provenance_unavailable','provider_final_gate_digest':gate.content_hash,
        'scientific_status':'not_measured'})
