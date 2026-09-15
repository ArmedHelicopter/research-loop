"""Versioned native call ownership used by the explicit ordinary controllers."""
from contextlib import contextmanager
import json
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_provider import PhaseProviderSession, PhaseProviderLedger
from research_loop.modular.train_provider_preflight import (native_envelope, response_schemas,
    native_provider_preflight, scorer_process_preflight)
from research_loop.ontology import ContractError


_HEADLESS_PROVIDER = 'grok-headless-frozen-evaluator-v1'


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def headless_evaluator_binding(body, *, family, enabled):
    """Validate an opt-in evaluator declaration without constructing its worker."""
    usage_schema = f'{family}-headless-evaluator-usage-declaration-v1'
    usage_contract = f'grok-headless-{family}-usage-v1'
    usage_fields = {'schema', 'provider_kind', 'usage_contract', 'evaluator_config_digest'}
    provider_fields = {'kind', 'configuration_digest'}
    usage, provider = body.get('evaluator_usage'), body.get('evaluator_provider')
    if not enabled:
        if usage is not None or provider is not None:
            raise ContractError('legacy ordinary controller cannot carry a headless evaluator declaration')
        return None
    if (not isinstance(usage, dict) or set(usage) != usage_fields
            or usage.get('schema') != usage_schema or usage.get('provider_kind') != _HEADLESS_PROVIDER
            or usage.get('usage_contract') != usage_contract or not _digest(usage.get('evaluator_config_digest'))
            or not isinstance(provider, dict) or set(provider) != provider_fields
            or provider.get('kind') != _HEADLESS_PROVIDER or not _digest(provider.get('configuration_digest'))
            or usage['evaluator_config_digest'] != provider['configuration_digest']):
        raise ContractError('headless evaluator declaration or provider differs')
    return {'evaluator_usage': dict(usage), 'evaluator_provider': dict(provider)}


def _headless_evaluator_gate(binding, *, family, failure_reason):
    return {'schema': 'ordinary-headless-evaluator-final-gate-v1', 'family': family,
            'status': 'inconclusive', 'score_eligible': False,
            'evaluator_usage': binding['evaluator_usage'], 'evaluator_provider': binding['evaluator_provider'],
            'ordered_receipt_digests': [], 'closure': None, 'known_headless_main_tokens': None,
            'title_and_all_opportunity_settlement': 'unknown', 'failure_reason': failure_reason, 'error_type': None}


def finalize_headless_evaluator_gate(*, binding, family, service, panel, scores, scorer_authority_keys, scorer_config, capture):
    """Capture a signed closure before checking it; only full coverage is eligible."""
    if (not isinstance(binding, dict) or type(family) is not str or not family
            or not callable(capture)):
        raise ContractError('headless evaluator finalization inputs are malformed')
    gate = _headless_evaluator_gate(binding, family=family, failure_reason=None)
    def persist_gate():
        try:
            capture(gate)
            return True
        except Exception as exc:
            # A failed durable capture cannot be repaired by a later write.
            gate.update(status='inconclusive', score_eligible=False,
                        failure_reason='closure_capture_failed', error_type=type(exc).__name__)
            return False
    digests = []
    try:
        for score in scores:
            digest = score.receipt.content_hash
            if not _digest(digest):
                raise ContractError('headless evaluator scorer receipt digest is malformed')
            digests.append(digest)
    except Exception as exc:
        gate.update(failure_reason='invalid_scorer_receipts', error_type=type(exc).__name__)
        persist_gate(); return gate
    gate['ordered_receipt_digests'] = digests
    if not scores:
        gate['failure_reason'] = 'no_scorer_receipts'
        persist_gate(); return gate
    try:
        closure = service.finalize_headless_evaluator(receipts=tuple(scores))
        gate['closure'] = closure.data()
        # This durable callback must not refresh provider usage or close a ledger.
        if not persist_gate():
            return gate
        from evaluation.modular.headless_evaluator_closure import verify_closure
        raw = closure.data(); nonce = raw.get('body', {}).get('nonce') if isinstance(raw.get('body'), dict) else None
        if not isinstance(nonce, str) or not nonce:
            raise ContractError('headless evaluator closure nonce is malformed')
        verified = verify_closure(closure, authority_keys=scorer_authority_keys, panel=panel,
            config=scorer_config, provider=binding['evaluator_provider'], nonce=nonce, receipt_digests=digests)
        body = verified.data(); gate['known_headless_main_tokens'] = body['known_main_tokens']
        if not persist_gate():
            return gate
        expected = {tuple(cell.key) for cell in panel.cells}
        receipt_cells = tuple(score.cell_key for score in scores)
        scoped = body['scope'].get('scored_cell_keys')
        scoped_cells = tuple(tuple(value) for value in scoped) if isinstance(scoped, list) else ()
        if (len(receipt_cells) != len(expected) or len(receipt_cells) != len(set(receipt_cells))
                or set(receipt_cells) != expected or len(scoped_cells) != len(expected)
                or len(scoped_cells) != len(set(scoped_cells)) or set(scoped_cells) != expected
                or body['scope'].get('unscored_cell_count') != 0):
            gate['failure_reason'] = 'incomplete_panel_closure'
            persist_gate(); return gate
        gate.update(status='eligible', score_eligible=True)
        persist_gate(); return gate
    except Exception as exc:
        gate.update(status='inconclusive', score_eligible=False,
                    failure_reason='closure_verification_failed', error_type=type(exc).__name__)
        persist_gate(); return gate


def verify_retained_headless_evaluator_gate(path, *, gate, binding, panel, scores,
                                            scorer_authority_keys, scorer_config):
    """Read the captured gate from the attempt journal before a controller returns.

    The append/write is not evidence by itself.  This binds the returned gate to
    the exact persisted JSON and rechecks any captured signed closure without
    starting a worker or finalizing a second time.
    """
    try:
        raw = Path(path).read_bytes(); retained = json.loads(raw)['evaluator_final_verification']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ContractError('retained evaluator final gate is unavailable') from exc
    if retained != gate:
        raise ContractError('retained evaluator final gate differs before return')
    closure_body = gate.get('closure') if isinstance(gate, dict) else None
    if closure_body is None:
        if gate.get('score_eligible') is True:
            raise ContractError('eligible retained evaluator gate lacks a closure')
        return gate
    try:
        from evaluation.modular.headless_evaluator_closure import verify_closure
        closure = FrozenRecord.from_dict(closure_body)
        nonce = closure.data()['body']['nonce']
        verified = verify_closure(closure, authority_keys=scorer_authority_keys, panel=panel,
            config=scorer_config, provider=binding['evaluator_provider'], nonce=nonce,
            receipt_digests=[score.receipt.content_hash for score in scores])
    except (KeyError, TypeError, ContractError) as exc:
        raise ContractError('retained evaluator closure no longer verifies') from exc
    if gate.get('score_eligible') is True and verified.data()['scope'].get('unscored_cell_count') != 0:
        raise ContractError('eligible retained evaluator gate has an incomplete scope')
    return gate


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
    # Accounting is replayed before the last provenance decision. The receipt
    # consumes this captured view without starting another accounting read.
    usage=session.usage().data()
    final=session.finish(path)
    try:
        verification=final.verify()
    except ContractError:
        # abort() itself requires an existing durable core provenance fault;
        # unrelated programming errors cannot manufacture terminal evidence.
        final=session.abort();verification=final.verify()
    eligible=type(final) is PhaseProviderLedger and verification.data()['score_eligible'] is True
    if type(final) is not PhaseProviderLedger:
        usage=final.snapshot.data()
    return FrozenRecord.from_dict({'schema':'ordinary-native-final-provider-gate-v1',
        'provider_evidence_eligible':eligible,'final_record_schema':final.record.data()['schema'],
        'final_record_digest':final.record.content_hash,'verification':verification.data(),
        'current_accounting':usage})


def final_usage(gate,model):
    return provider_usage(None,model) if gate is None else gate.data()['current_accounting']


def final_unused(gate,model,body):
    if gate is None:return unused_main_opportunities(None,model,body)
    usage=gate.data()['current_accounting']
    if usage['schema']=='public-train-provider-terminal-snapshot-v1':return None
    return body['provider']['limits']['main_opportunities']-usage['main_opportunities']


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
