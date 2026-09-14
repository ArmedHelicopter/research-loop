"""Bounded actual host seams; synthetic public TRAIN tasks, no paid provider."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.ontology import ContractError
from test_builder_artifacts import rewrite_catalogue

R = FrozenRecord.from_dict
AUDIT = AuditVerifier({'a':b'a'*32,'b':b'b'*32})
FAMILIES = ('state_exploration','state_scheduling','mechanism_exploration','mechanism_scheduling','admission_prediction_exploration')


def check_outputs(result, verify, kwargs, *, tamper):
    verify(result, **kwargs)
    path = result.runtime.trace_path.parent/'artifacts.jsonl'
    raw = path.read_bytes(); rows = [json.loads(line)['descriptor'] for line in raw.splitlines()]
    assert sum(row['kind']=='execution_phase_inputs' for row in rows) == 1
    phase = [row for row in rows if row['kind'].startswith('phase_')]
    assert sum(row['kind']=='phase_program' for row in phase) == sum(row['kind']=='phase_return' for row in phase) == 2
    assert sum(row['kind']=='phase_allocation' for row in phase) == sum(row['kind']=='phase_receipt' for row in phase) == 1
    enabled = result.cell.runtime_arm.data()['enabled']
    assert all(row['status']==('produced' if row['module'] in enabled else 'not_applied') for row in phase)
    assert (path.parent.parent/'phase/queue.sqlite').exists() == ('M8' in enabled)
    trace = [json.loads(line) for line in result.runtime.trace_path.read_bytes().splitlines()]
    closed = next(i for i,event in enumerate(trace) if event['stage']=='audited_phase_closed')
    calls = [i for i,event in enumerate(trace) if event['stage']=='model_request'
             and event['data']['request']['slot']=='analysis_program']
    assert not calls or closed < calls[0]
    if not tamper: return
    first = rows[0]
    catalogue = ArtifactCatalogue(path,identity=result.cell.identity,**first['binding'])
    seal_before = catalogue.seal_path.read_bytes() if catalogue.seal_path.exists() else None
    def edit(body):
        if body['kind']=='execution_phase_inputs':
            body['payload']['canonical']['timeout_seconds'] += 1
    try:
        rewrite_catalogue(SimpleNamespace(artifacts=catalogue),edit)
        with pytest.raises(ContractError,match='input witness differs from actual invocation'):
            verify(result, **kwargs)
    finally:
        path.write_bytes(raw)
        if seal_before is None: catalogue.seal_path.unlink()
        else: catalogue.seal_path.write_bytes(seal_before)
    verify(result, **kwargs)
    blob = path.parent.parent/'phase-artifacts/blobs'/phase[0]['payload']['canonical']['bytes']['sha256']
    original = blob.read_bytes()
    try:
        blob.write_bytes(b'corrupted phase bytes')
        with pytest.raises(ContractError,match='immutable blob differs'):
            verify(result, **kwargs)
    finally: blob.write_bytes(original)
    verify(result, **kwargs)


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mode', ('enabled','disabled','phase_failure'))
def test_actual_composite_host_and_reader_preserve_phase_outputs(tmp_path, family, mode):
    suffix = '_controller' if family=='admission_prediction_exploration' else '_train_controller'
    fixture = importlib.import_module('test_'+family+suffix)
    driver = importlib.import_module('research_loop.modular.'+family+
        ('_driver' if family=='admission_prediction_exploration' else '_combination_driver'))
    setup = fixture.prepare(tmp_path, 'phase' if mode=='phase_failure' else None)
    compiled = setup['compiled']; panel = compiled.panels[0]
    arm = ('0' if mode=='disabled' else '1')*len(panel.cells[0].arm_id)
    cell = next(cell for cell in panel.cells if cell.arm_id==arm and cell.identity.benchmark=='blade')
    packet = next(packet for packet in compiled.packets if packet.task.content_hash==cell.task_digest)
    kwargs = dict(panel=panel,task=packet.task,scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash],material=compiled.materials[panel.obligation_id][cell.task_digest],
        source_verifier=setup['verifiers'][panel.obligation_id],public_inputs={'public_csv':packet.csv_path},
        broker=DockerExecutionBroker([tmp_path]))
    extra = {'provider':fixture.Provider(setup['retrieval_calls'])} if family.startswith('mechanism_') else {}
    seen=[]; config=setup['config'].data()
    result = getattr(driver,'run_'+family+'_cell')(cell=cell,**kwargs,**extra,
        objective=R(config['objective']),sidecar=tmp_path/'actual-host',image=config['image'],
        model=fixture.model(seen),audit_verifier=AUDIT,timeout_seconds=config['timeout_seconds'])
    assert result.runtime.status == ('failed' if mode=='phase_failure' else 'succeeded')
    assert result.phase is not None
    check_outputs(result,getattr(driver,'verify_'+family+'_cell'),kwargs,tamper=mode=='enabled')
    assert not any(row['slot']=='analysis_program' for row in seen) if mode=='phase_failure' else bool(seen)


@pytest.mark.parametrize('mode', ('enabled','disabled','phase_failure'))
def test_actual_phase_before_any_model_call_needs_no_invented_model_parent(tmp_path,mode):
    from test_exploration_scheduler_combination import fixture
    from research_loop.modular.exploration_scheduler_combination import (
        FrozenExplorationSchedulerMaterial,run_exploration_scheduler_cell,verify_exploration_scheduler_cell)
    _,_,config,compiled,service=fixture(tmp_path,job_fault='docker_failed' if mode=='phase_failure' else None)
    service.close()
    enabled=[] if mode=='disabled' else ['M7','M8']
    cell=next(cell for cell in compiled.panel.cells if cell.runtime_arm.data()['enabled']==enabled)
    packet=next(packet for packet in compiled.packets if packet.task.content_hash==cell.task_digest)
    b=config.data();seen=[]
    def model(request):
        body=request.data();seen.append(body)
        if body['slot']=='analysis_program':
            values=[float(row['stdout']) for row in body['module_context']['joint_mechanism']['material']['observations']]
            return R({'analysis':'Sum the actual public phase observations.','program':'print('+repr(sum(values))+')'})
        return R({'objective_digest':body['module_context']['required_objective_digest'],'outcome':'unknown',
            'evidence_ids':[],'conclusion':'Observed '+body['execution_feedback'][0]['stdout'],'programme_complete':False})
    kwargs=dict(panel=compiled.panel,task=packet.task,scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash],
        material=FrozenExplorationSchedulerMaterial(R(b['materials_by_task'][cell.task_digest])),
        public_inputs={'public_csv':packet.csv_path},broker=DockerExecutionBroker([tmp_path]),
        image=b['image'],timeout_seconds=b['timeout_seconds'])
    result=run_exploration_scheduler_cell(cell=cell,**kwargs,objective=R({'panel_digest':compiled.panel.digest}),
        sidecar=tmp_path/'actual-host',model=model,audit_verifier=AUDIT)
    assert result.runtime.status==('failed' if mode=='phase_failure' else 'succeeded')
    check_outputs(result,verify_exploration_scheduler_cell,kwargs,tamper=mode=='enabled')
    rows=[json.loads(line)['descriptor'] for line in (result.runtime.trace_path.parent/'artifacts.jsonl').read_bytes().splitlines()]
    index=next(i for i,row in enumerate(rows) if row['kind']=='execution_phase_inputs')
    assert not any(row['kind']=='model_context' for row in rows[:index])
    assert len(seen)==(0 if mode=='phase_failure' else 2)
