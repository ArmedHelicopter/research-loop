"""Real custody -> CodexModelPort transport -> Docker, with production registration."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.exploration_extended_panel_drivers import (
    BUDGET, VARIANTS, LIMITS, freeze_extended_exploration_bundle, select_training_ratio,
)
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.panel_runner import DRIVERS
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel, _driver_plan
from research_loop.ontology import ContractError
from test_modular_exploration_extended_panel_drivers import Authority, _item, _model
from test_modular_semantic_train_controller import _closed_shape
from test_modular_train_controller import config, snapshot_and_custody, model_port, FINAL, REVIEW


def _frozen(root):
    snapshot,custody=snapshot_and_custody(root,csv_text='x,y\n1,-2\n3,0\n')
    base=config(custody,snapshot,root).data()
    packets=TrainPacketExporter(custody,snapshot,root/'material').export(base['item_ids'])
    authority=Authority(); bundles={}
    for packet in packets:
        task,path=packet.task,packet.csv_path
        common=_item(task,path,authority,count=8,ratio=True)
        q73={name:{**deepcopy(common),'config':{'ratio_id':'ratio_'+str(percent),'exploration_percent':percent,'control_percent':25,
            'main_ids':['job_'+str(i) for i in range(4)],'diagnostic_ids':['job_'+str(i) for i in range(4,8)]}}
            for name,percent in zip(VARIANTS['Q7.3'],(0,25,50,75))}
        q74={name:{**_item(task,path,authority,count=2,bad=True,repaired=name!='invalid_measure'),
            'config':{'old_id':'job_0','repair_id':'job_1','instrument_id':'calibrated-public-control'}} for name in VARIANTS['Q7.4']}
        states=[('valid_known','x',True,'known','explore',True),('novel_refuted','y',True,'novel','stop',False),
            ('infeasible','x',False,'unknown','repair',False),('easy_valid','x',True,'unknown','explore',False)]
        q75={name:{**_item(task,path,authority,measured=field,construct=field,known=known,novelty=novelty,investment=investment,prior=prior),
            'config':{'observation_id':'job_0','observation_claim':'Mean of '+field+' is positive.','novelty_claim':'The observation is absent from prior publications.'}}
            for name,field,known,novelty,investment,prior in states}
        q76={name:{**_item(task,path,authority,measured=measured,construct=construct),
            'config':{'observation_id':'job_0','theory':'Mean of intended field is positive.','construct':construct}}
            for name,measured,construct in [('contract_only','x','y'),('real_counterexample','y','y')]}
        bundles[task.content_hash]=freeze_extended_exploration_bundle(task,materials={'Q7.3':q73,'Q7.4':q74,'Q7.5':q75,'Q7.6':q76},budget=FrozenRecord.from_dict(BUDGET)).data()
    grids=obligation_grids(tuple(VARIANTS),baseline_digest=base['baseline_digest'],p0_control=FrozenRecord.from_dict(base['p0_control']))
    package=next(iter(base['packages_by_arm'].values())); final=deepcopy(FINAL)
    final['properties']['outcome']['enum']=['unknown','invalid','positive','negative']
    judgement=_closed_shape({'assessment':'accept','rationale':'public'})
    schemas={'prospective':judgement,'diagnostic':deepcopy(judgement),'semantic_review':REVIEW,'final':final}
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,'schema':'train-panel-controller-v1',
        'engineering_scope':'train_only_panel_engineering','stage':'extended-exploration-custody-controller',
        'scope_ids':list(VARIANTS),'evidence_by_task':bundles,'budget':BUDGET,'schemas':schemas,'max_calls':280,'max_tokens':800,
        'packages_by_arm':{arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()}}))
    return snapshot,custody,frozen,authority


def test_registered_driver_opportunities_match_actual_slots(tmp_path):
    snapshot,custody,frozen,authority=_frozen(tmp_path); data=frozen.data()
    assert _driver_plan(data['scope_ids'],baseline_digest=data['baseline_digest'],p0_control=FrozenRecord.from_dict(data['p0_control']),
        item_count=len(data['item_ids']),replicates=data['replicates'])==(88,280)
    assert {key:len(DRIVERS[key].slots) for key in VARIANTS}=={key:row[0] for key,row in LIMITS.items()}


def test_complete_88_cell_export_model_port_docker_controller(tmp_path,monkeypatch):
    snapshot,custody,frozen,authority=_frozen(tmp_path); seen=[]
    port=model_port(tmp_path,monkeypatch,max_calls=280,max_tokens=800,schemas=frozen.data()['schemas'],response_factory=_model(seen))
    verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32})
    with pytest.raises(ContractError,match='verification ports before export'):
        run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'rejected-export',run_root=tmp_path/'rejected-run',model=port,audit_verifier=verifier)
    assert not (tmp_path/'rejected-export').exists() and not (tmp_path/'rejected-run').exists()
    assert port.ledger['calls']==[] and authority.calls==[]
    result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',
        model=port,audit_verifier=verifier,exploration_authority=authority)
    assert len(result.runtimes)==len(result.compiled.panel.cells)==88
    assert len(seen)==len(port.ledger['calls'])==280 and len(authority.calls)==320
    assert port.ledger['tokens']==560 and port.ledger['usage_incomplete'] is False
    assert all(row.status=='succeeded' for row in result.runtimes)
    assert result.receipt.data()['execution_status']=='engineering_complete' and result.verdict.scientific_verified is False
    manifest=[]; total_executions=0; decisions={}
    for index,runtime in enumerate(result.runtimes):
        events=[json.loads(line) for line in runtime.trace_path.read_text().splitlines()]
        cell=next(cell for cell in result.compiled.panel.cells if cell.key==runtime.cell_key)
        actual=[e for e in events if e['stage']=='execution_result']
        assert len(actual)==LIMITS[cell.coverage_id][1]; total_executions+=len(actual)
        assert all(e['data']['record']['status']=='succeeded' and set(e['data']['record']['input_artifacts'])=={'data_csv'} for e in actual)
        assert sum(e['stage']=='extended_verifier_request' for e in events)==LIMITS[cell.coverage_id][2]
        terminal=events[-1]['data']; decisions[terminal['decision']]=decisions.get(terminal['decision'],0)+1
        response=next(e['data']['response'] for e in reversed(events) if e['stage']=='model_response')
        assert terminal['candidate_digest']==FrozenRecord.from_dict(response).content_hash
        manifest.append({'index':index,'cell':cell.data(),'trace_path':str(runtime.trace_path),
            'sha256':sha256(runtime.trace_path.read_bytes()).hexdigest(),'trace_digest':runtime.trace_digest})
    assert total_executions==160
    selections=[]
    for task in result.compiled.tasks.values():
        row=select_training_ratio(task=task,bundle=FrozenRecord.from_dict(frozen.data()['evidence_by_task'][task.content_hash]),panel=result.compiled.panel,runtimes=result.runtimes)
        assert row.data()['selected_ratio_id']=='ratio_25'; selections.append(row.data())
    (tmp_path/'controller-verification.json').write_text(json.dumps({'cells':manifest,'ratio_selections':selections,'decisions':decisions,
        'model_calls':len(port.ledger['calls']),'synthetic_reported_tokens':port.ledger['tokens'],'executions':total_executions,
        'verifier_calls':len(authority.calls),'scientific_verified':result.verdict.scientific_verified},indent=2))


@pytest.mark.parametrize('family',['Q7.3','Q7.4','Q7.5','Q7.6'])
def test_later_variant_foreign_csv_rejected_before_any_model_or_authority(tmp_path,monkeypatch,family):
    snapshot,custody,frozen,authority=_frozen(tmp_path); data=frozen.data()
    # Change every ratio identically to preserve the common-menu invariant;
    # the declared CSV is still a foreign artifact and must be rejected.
    bundle=next(iter(data['evidence_by_task'].values()))
    variants=bundle['materials'][family].values() if family=='Q7.3' else [bundle['materials'][family][VARIANTS[family][-1]]]
    for variant in variants: variant['jobs'][-1]['inputs']['data_csv']['sha256']='0'*64
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(data))
    port=model_port(tmp_path,monkeypatch,max_calls=280,max_tokens=800,schemas=data['schemas'])
    with pytest.raises(ContractError,match='differs from exported train CSV bytes'):
        run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',model=port,
            audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),exploration_authority=authority)
    assert port.ledger['calls']==[] and authority.calls==[]
    assert json.loads((tmp_path/'run/controller-attempt.json').read_text())['status']=='execution_interrupted'


def test_boolean_nested_budget_cannot_impersonate_an_execution_unit(tmp_path):
    _,_,frozen,_=_frozen(tmp_path); body=frozen.data(); body['budget']['Q7.5']['execution_opportunities']=True
    with pytest.raises(ContractError,match='exact matched opportunity budgets'):
        FrozenTrainControllerConfig(FrozenRecord.from_dict(body))
