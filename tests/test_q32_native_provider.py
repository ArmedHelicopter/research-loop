"""Prospective source -> native default entry -> actual twelve Docker measurements."""
import hashlib
import pytest
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.q32_execution import FrozenQ32ProspectiveConfig,run_q32_prospective_execution_panel,SLOTS,PROGRAM_SCHEMA
from research_loop.modular.q32_native_provider import native_budget,projected_events
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError,digest
from helpers.native_ordinary_provider import native_ordinary_provider
from test_remaining_prospective_train_sources import prepared_primary
from test_modular_train_controller import FINAL
import test_q32_prospective_execution as q32


def prepare(root,patch,*,fault=None):
    exporter,selected,all_items,packets=prepared_primary(root)
    cells=[{'cell_id':digest({'task':p.task.content_hash,'variant':v}),'task_digest':p.task.content_hash,'variant':v}
        for p in packets for v in ('joint','separate')]
    providers=[];logs=[]
    for i,cell in enumerate(cells):
        provider,actual=native_ordinary_provider(root/f'provider-{i}',patch,
            schemas={s:FINAL if s=='final' else PROGRAM_SCHEMA for s in SLOTS},max_calls=4,
            response=q32.fixture_response,fault_at=2 if fault=='unknown_main' and i==0 else None)
        providers.append(provider);logs.append(actual)
    body={'schema':'q32-prospective-source-config-v3','domain':'train','export_mode':'primary_prospective',
        'item_ids':[i.token for i in selected], 'task_bindings':{i.token:{'identity':p.task.identity.data(),'task_digest':p.task.content_hash,
            'csv_sha256':hashlib.sha256(p.csv_path.read_bytes()).hexdigest(),'csv_byte_count':p.csv_path.stat().st_size} for i,p in zip(selected,packets,strict=True)},
        'material_by_task':{p.task.content_hash:q32.material() for p in packets},'image':q32.IMAGE,
        'providers_by_cell':{c['cell_id']:provider.configuration().data() for c,provider in zip(cells,providers)},
        'native_budget':native_budget()}
    config=FrozenQ32ProspectiveConfig(FrozenRecord.from_dict(body))
    return exporter,config,providers,logs


@pytest.mark.parametrize('fault',[None,'unknown_main','provenance'])
def test_native_q32_prospective_execution_and_run_terminal_denominator(tmp_path,monkeypatch,fault):
    exporter,config,providers,logs=prepare(tmp_path,monkeypatch,fault=fault)
    if fault=='provenance':
        from research_loop.modular.q32_execution import Q32ExecutionStage
        execute=Q32ExecutionStage.execute_next
        def corrupt_after_execution(self,**kwargs):
            result=execute(self,**kwargs)
            next(providers[0].backend.calls_root.glob('*/response.private.json')).write_bytes(b'{"synthetic_drift":true}')
            return result
        monkeypatch.setattr(Q32ExecutionStage,'execute_next',corrupt_after_execution)
    result=run_q32_prospective_execution_panel(config,prospective_exporter=exporter,
        snapshot_root=exporter.config['snapshot_root'],export_root=exporter.output_root,run_root=tmp_path/'run',
        model_factory=lambda i:providers[i],verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32})).data()['result']
    assert result['schema']=='q32-native-panel-result-v1'
    assert result['cell_count']==4 and result['measurement_denominator']==12
    assert len(result['results'])==4 and sum(len(r['rows']) for r in result['results'])==12
    assert all(not r['scientific_validated'] for r in result['results'])
    if fault:
        assert result['status']=='incomplete' and result['eligible_measurements']==0 and result['run_terminal']
        assert [len(x) for x in logs]==([2,0,0,0] if fault=='unknown_main' else [3,0,0,0])
        assert all(r['status']=='blocked' for r in result['results'][1:])
        assert result['historical_measurements']==(0 if fault=='unknown_main' else 1)
    else:
        assert [len(x) for x in logs]==[4,4,4,4]
        assert result['status']=='completed' and result['eligible_measurements']==12
        assert result['historical_measurements']==12
        compiled=FrozenRecord((tmp_path/'run/compiled.json').read_text())
        assert compiled.data()['budget']['native_lifetime_seconds']==60
        for i,cell in enumerate(compiled.data()['cells']):
            trace=tmp_path/'run'/str(i)/'runtime/trace.jsonl'
            q32.verify_q32_execution(trace,compiled)
            projected_events(trace,compiled,cell)
        # A rehashed projection cannot hide a changed original request link.
        events=q32.trace(tmp_path/'run/0/runtime/trace.jsonl')
        next(e for e in events if e['stage']=='q32_public_request')['data']['original_digest']='f'*64
        bad=tmp_path/'projection-attack.jsonl';q32.rechain(events,bad)
        with pytest.raises(ContractError):projected_events(bad,compiled,compiled.data()['cells'][0])


@pytest.mark.parametrize('fault',['lifetime','missing_cell','schema','call_budget','legacy_field'])
def test_native_q32_configuration_freezes_provider_budget_per_cell(tmp_path,monkeypatch,fault):
    _,config,providers,logs=prepare(tmp_path,monkeypatch)
    b=config.data();first=next(iter(b['providers_by_cell'].values()))
    if fault=='lifetime':b['native_budget']['native_lifetime_seconds']=180
    elif fault=='missing_cell':b['providers_by_cell'].pop(next(iter(b['providers_by_cell'])))
    elif fault=='schema':first['native_config']['schemas'].pop('program_2')
    elif fault=='call_budget':first['limits']['main_opportunities']=5
    else:b['model']='gpt-5.6-luna'
    with pytest.raises(ContractError):FrozenQ32ProspectiveConfig(FrozenRecord.from_dict(b))
    assert not any(logs)
