"""Actual singleton dispatch, including the separately owned solver call span."""
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.modular.train_provider_preflight import LEGACY_TRANSPORT_FIELDS
from helpers.native_ordinary_provider import native_ordinary_provider
from test_modular_train_controller import snapshot_and_custody
from test_modular_linked_train_controller import _linked_config, AUDIT


def response(request):
    b=request.data();slot=b['slot']
    if slot=='scenario':
        directions=['increase','decrease','increase']
        return {'question':'public','budget_units':3,'branches':[
            {'hypothesis_id':f'h{i}','mechanism_key':f'm{i}','mechanism':'public mechanism',
             'intervention':'public intervention','elimination_condition':'public disagreement',
             'predictions':[{'prediction_id':f'p{i}','discriminator_id':'shared','observable':'public observable',
                 'direction':directions[i],'value_range':None,'failure_condition':'does not '+directions[i]}]}
            for i in range(3)]}
    if slot=='analysis_program':
        return {'analysis':'public x mean','program':"import csv\nwith open('/input/public_csv',newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"}
    return {'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown',
        'evidence_ids':[],'conclusion':'synthetic engineering only','programme_complete':False}


@pytest.mark.parametrize('linked,fault',[(False,None),(True,None),(False,2)])
def test_default_native_singleton_dispatch_retains_exact_owned_calls_and_denominator(tmp_path,monkeypatch,linked,fault):
    snapshot,custody=snapshot_and_custody(tmp_path)
    old=_linked_config(custody,snapshot,tmp_path,linked=linked).data()
    provider,logs=native_ordinary_provider(tmp_path/'native',monkeypatch,schemas=old['schemas'],
        max_calls=old['max_calls'],response=response,fault_at=fault)
    body={k:v for k,v in old.items() if k not in LEGACY_TRANSPORT_FIELDS}
    body.update(schema='train-panel-controller-v2',provider=provider.configuration().data())
    result=run_train_panel(FrozenTrainControllerConfig(FrozenRecord.from_dict(body)),custody=custody,
        snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',model=provider,
        audit_verifier=AuditVerifier(AUDIT))
    b=result.receipt.data();rows=[r.data() for r in result.attempts]
    assert b['schema']=='train-panel-controller-receipt-v2' and len(rows)==b['expected_cells']==12
    assert b['pruned_cells']==[] and b['validation_opened'] is False
    if fault:
        assert len(logs)==2 and b['blocked_cells']==11
        assert b['execution_status']=='execution_incomplete'
        assert b['actual_model_usage']['known_reported_tokens']==24
        assert b['actual_model_usage']['unknown_main_opportunities']==1
    else:
        assert len(logs)==old['max_calls'] and len(result.runtimes)==12
        assert b['execution_status']=='engineering_complete',rows
        assert all(r['status']=='succeeded' and r['provider_seal_digest'] for r in rows)
        assert b['provider_final_gate']['provider_evidence_eligible'] is True
        if linked:
            assert len(result.linked_results)==12
            assert all(r.solver.execution.status=='succeeded' for r in result.linked_results)
