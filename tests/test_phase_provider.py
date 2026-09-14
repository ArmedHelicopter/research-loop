import json
from dataclasses import replace

import pytest

from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.phase_provider import (PhaseProviderSession, PhaseProviderLedger,
    PhaseProviderAbort, provider_configuration, validate_configuration, call_accounting)
from research_loop.modular.metaprogram_training import metaprogram_schemas
from research_loop.modular.modules.improvement import (TrainingManifest,CandidatePackage,
    FrozenBuilderVersion,RestrictedBuilderPort)
from research_loop.ontology import ContractError
from helpers.native_phase_provider import native_phase_provider
from test_grok_train_solver import REQUEST


def trace(request,response):
    return [{'stage':'model_request','data':{'request':request.data()}},
        {'stage':'model_response','data':{'request_digest':request.content_hash,'response':response.data()}}]


def fixture(root,patch,*,fault_at=None):
    proposal={'entrypoint':'emit_literal_change_v1','surface':'prompt','key':'instructions','value':'Use public mean'}
    provider,logs=native_phase_provider(root/'provider',patch,schemas={'builder_proposal':metaprogram_schemas()['builder_proposal']},
        max_calls=3,response=lambda request:proposal,fault_at=fault_at)
    request=FrozenRecord.from_dict({**REQUEST.data(),'slot':'builder_proposal'})
    return provider,logs,request


def test_native_history_build_prefix_and_targets_have_disjoint_original_spans(tmp_path,monkeypatch):
    provider,logs,request=fixture(tmp_path,monkeypatch)
    validate_configuration(provider_configuration(provider),schemas=provider.backend.schemas,main_opportunities=3)
    session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as model: response=model(request)
    ledger=session.seal(tmp_path/'history.json')
    builder=FrozenBuilderVersion(response)
    manifest=TrainingManifest.freeze([DataIdentity('blade','synthetic','synthetic','a'*64,'b'*64,'train')])
    parent=CandidatePackage.create(parent_digest=None,manifest=manifest,changes={'prompt':{'instructions':'Baseline'}},search_cost=0)
    candidate,receipt=RestrictedBuilderPort().execute(builder,manifest,parent,expected_builder_digest=builder.digest,
        expected_entrypoint=builder.entrypoint,search_cost=1)
    assert candidate.record.data()['changes']['prompt']['instructions']=='Use public mean'
    assert receipt.output_candidate_digest==candidate.digest
    with session.scope('target-1') as model: second=model(request)
    with session.scope('target-2') as model: third=model(request)
    final=session.seal(tmp_path/'targets.json')
    assert ledger.verify().data()['later_calls']==2
    assert ledger.bind_events(trace(request,response),scope_id='history')==(1,)
    assert final.bind_events(trace(request,second),scope_id='target-1')==(2,)
    assert final.bind_events(trace(request,third),scope_id='target-2')==(3,)
    assert len(logs)==3
    usage=call_accounting(provider.inspect())
    assert usage['known_reported_tokens']==36 and usage['possible_initial_title_opportunities']==3
    assert usage['unknown_main_opportunities']==0 and usage['settled_additional_charge_usd'] is None


def test_failed_target_keeps_known_main_and_history_originals_without_score_eligibility(tmp_path,monkeypatch):
    provider,logs,request=fixture(tmp_path,monkeypatch,fault_at=2)
    session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as model: response=model(request)
    history=session.seal(tmp_path/'history.json')
    with pytest.raises(ContractError):
        with session.scope('failed-target') as model: model(request)
    with session.scope('blocked-target'): pass
    final=session.seal(tmp_path/'final.json')
    assert history.verify().data()['originals_verified'] and not history.verify().data()['score_eligible']
    assert history.bind_events(trace(request,response),scope_id='history',require_eligible=False)==(1,)
    assert len(final.record.data()['scopes']['scopes'])==3 and len(logs)==2
    assert call_accounting(provider.inspect())['known_reported_tokens']==24
    assert call_accounting(provider.inspect())['unknown_main_opportunities']==1
    with pytest.raises(ContractError): history.bind_events(trace(request,response),scope_id='history')


def test_duplicate_scope_or_unscoped_call_cannot_enter_a_seal(tmp_path,monkeypatch):
    provider,_,request=fixture(tmp_path,monkeypatch);session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('one') as model:model(request)
    with pytest.raises(ContractError):
        with session.scope('one'):pass
    provider(request)
    with pytest.raises(ContractError,match='unscoped'):session.seal(tmp_path/'invalid.json')


def test_coherently_rehashed_scope_reuse_rejected_against_original_partition(tmp_path,monkeypatch):
    provider,_,request=fixture(tmp_path,monkeypatch);session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('one') as model:model(request)
    with session.scope('two') as model:model(request)
    ledger=session.seal(tmp_path/'seal.json');body=ledger.record.data()
    body['scopes']['scopes'][1]['call_ids']=[1]
    changed=FrozenRecord.from_dict(body);ledger.path.write_bytes(changed.encoded.encode())
    with pytest.raises(ContractError):replace(ledger,record=changed).verify()


@pytest.mark.parametrize('field,value',[('lifetime_seconds',180),('main_opportunities',2),('possible_initial_title_opportunities',0)])
def test_native_configuration_cannot_reinterpret_lifetime_or_allocation(tmp_path,monkeypatch,field,value):
    provider,_,_=fixture(tmp_path,monkeypatch);body=provider_configuration(provider).data();body['limits'][field]=value
    with pytest.raises(ContractError):validate_configuration(FrozenRecord.from_dict(body),schemas=provider.backend.schemas,main_opportunities=3)


def test_provenance_abort_retains_unresolved_scope_and_only_historical_lower_bounds(tmp_path,monkeypatch):
    provider,logs,request=fixture(tmp_path,monkeypatch)
    session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    with session.scope('history') as model:model(request)
    with pytest.raises(ContractError):
        with session.scope('target') as model:
            model(request)
            original=provider.backend.calls_root/'0001-builder_proposal'/'response.private.json'
            original.write_bytes(original.read_bytes()+b' ')
    assert type(session.aborted) is PhaseProviderAbort and session.active is None
    def forbidden(*args,**kwargs):raise AssertionError('terminal accounting attempted a new original inspection')
    monkeypatch.setattr(provider,'inspect',forbidden)
    snapshot=session.usage().data()
    assert session.terminal() and snapshot['observed_main_opportunities_lower_bound']==2
    assert snapshot['known_reported_tokens_lower_bound']==24 and snapshot['total_main_opportunities'] is None
    assert snapshot['unknown_unobserved_opportunities'] and not snapshot['current_originals_verified']
    aborted=session.finish(tmp_path/'finished.json')
    assert type(aborted) is PhaseProviderAbort and type(aborted) is not PhaseProviderLedger
    b=aborted.record.data()
    assert b['unresolved_scope']=={'scope_id':'target','start_cursor':1}
    assert [r['scope_id'] for r in b['completed_scope_prefix']['scopes']]==['history']
    assert not b['scope_partition_complete'] and len(logs)==2
    assert aborted.verify().data()['status']=='terminal_accounting_only'
    assert not (tmp_path/'finished-originals.json').exists()
    with pytest.raises(ContractError):aborted.bind_events([],scope_id='target')
    with pytest.raises(ContractError):
        with session.scope('later'):pass


def test_phase_programming_error_does_not_manufacture_a_terminal_snapshot(tmp_path,monkeypatch):
    provider,logs,_=fixture(tmp_path,monkeypatch)
    session=PhaseProviderSession(provider,tmp_path/'scopes.json')
    session.path.write_bytes(b'{}')
    with pytest.raises(ContractError):session.finish(tmp_path/'invalid.json')
    assert session.aborted is None and not logs
    assert not (tmp_path/'invalid.json').exists()
    assert not list(provider.root.glob('terminal-snapshot-*.json'))
