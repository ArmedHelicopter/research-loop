"""Q5.4 actual public custody/export/model/Docker/authority seam."""
import json
import pytest
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_q54_causal_driver import material, Authority
from test_modular_semantic_train_controller import _closed_shape
from test_modular_train_controller import config, snapshot_and_custody, model_port, FINAL


def _config(tmp_path):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path/'material').export(base['item_ids'])
    grid = obligation_grids(('Q5.4',), baseline_digest=base['baseline_digest'],
                            p0_control=FrozenRecord.from_dict(base['p0_control']))['Q5.4']
    package = next(iter(base['packages_by_arm'].values()))
    schemas = {'ranking':_closed_shape({'ranking':['a','b'], 'rationale':'public'}),
               'diagnostic':_closed_shape({'decision':'continue','rationale':'public'}), 'final':FINAL}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,
        'schema':'train-panel-controller-v1', 'engineering_scope':'train_only_panel_engineering',
        'stage':'q54-custody-controller', 'scope_ids':['Q5.4'], 'schemas':schemas, 'max_calls':48,
        'budget':{'model_calls':3,'execution_opportunities':1,'verification_calls':1},
        'evidence_by_task':{p.task.content_hash:material(p.task,p.csv_path.read_bytes()).data() for p in packets},
        'packages_by_arm':{arm.content_hash:package for arm in executable_arms(grid).values()}}))
    return snapshot,custody,frozen


def test_full_16_cell_diagnostic_controller_with_real_custody_and_public_inputs(tmp_path,monkeypatch):
    snapshot,custody,frozen = _config(tmp_path)
    seen=[]
    def response(request):
        row=request.data(); seen.append(row); context=row['module_context']
        if row['slot']=='ranking': return FrozenRecord.from_dict({'ranking':['a','b'],'rationale':'public prior ranking'})
        if row['slot']=='diagnostic':
            gate=context['observation']['gate']['disposition']
            return FrozenRecord.from_dict({'decision':'continue' if gate=='unapplied' else gate,'rationale':'actual diagnostic observation'})
        return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown',
                                       'evidence_ids':[],'conclusion':'bounded diagnostic','programme_complete':False})
    port=model_port(tmp_path,monkeypatch,max_calls=48,schemas=frozen.data()['schemas'],response_factory=response)
    verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32})
    with pytest.raises(ContractError,match='verification port before export'):
        run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'rejected-export',
                        run_root=tmp_path/'rejected-run',model=port,audit_verifier=verifier)
    assert not (tmp_path/'rejected-export').exists() and not (tmp_path/'rejected-run').exists()
    assert port.ledger['calls']==[]
    result=run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',
                          run_root=tmp_path/'run',model=port,audit_verifier=verifier,diagnostic_authority=Authority())
    assert len(result.runtimes)==16 and len(seen)==len(port.ledger['calls'])==48
    assert all(r.status=='succeeded' for r in result.runtimes)
    assert result.receipt.data()['execution_status']=='engineering_complete' and not result.verdict.scientific_verified
    selections=set(); gates=set()
    for runtime in result.runtimes:
        events=[json.loads(line) for line in runtime.trace_path.read_text().splitlines()]
        assert sum(e['stage']=='execution_result' for e in events)==1
        request=next(e['data']['subject'] for e in events if e['stage']=='q54_authority_request')
        assert request['execution_receipt']['status']=='succeeded'
        selections.add(request['selection']['diagnostic_id'])
    for row in seen:
        if row['slot']=='diagnostic': gates.add(row['module_context']['observation']['gate']['disposition'])
    assert selections=={'a','b'} and gates=={'unapplied','continue','defer'}


def test_diagnostic_foreign_csv_stops_before_model_and_authority(tmp_path,monkeypatch):
    snapshot,custody,frozen=_config(tmp_path); data=frozen.data()
    next(iter(data['evidence_by_task'].values()))['variants']['preregistered_cost']['diagnostics'][1]['inputs']['data']['sha256']='0'*64
    frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(data))
    port=model_port(tmp_path,monkeypatch,max_calls=48,schemas=data['schemas'])
    class NoCall:
        def verify_diagnostic(self,subject): pytest.fail('foreign CSV reached authority')
    with pytest.raises(ContractError,match='differs from exported train CSV bytes'):
        run_train_panel(frozen,custody=custody,snapshot_root=snapshot,export_root=tmp_path/'export',run_root=tmp_path/'run',
                        model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),diagnostic_authority=NoCall())
    assert port.ledger['calls']==[]
