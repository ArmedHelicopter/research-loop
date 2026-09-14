"""Phase provenance for hosts whose real inputs need no preceding model call."""
from pathlib import Path
import json

from research_loop.ontology import ContractError
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.phase_artifacts import PhaseArtifactBridge, PhaseArtifactContext, verify_phase_artifacts


def _inputs(*, material, cell, objective, image, timeout_seconds, inputs, selected_job_id=None):
    return FrozenRecord.from_dict({'schema':'execution-phase-inputs-v1', 'cell':cell.data(),
        'material':material.record.data(), 'objective':objective.data(), 'image':image,
        'timeout_seconds':timeout_seconds, 'input_paths':{key:str(Path(value).absolute()) for key,value in inputs.items()},
        'selected_job_id':selected_job_id})


def _bridge(catalogue, root, cell, parent):
    return PhaseArtifactBridge(PhaseArtifactContext(catalogue, Path(root).parent/'phase-artifacts',
        {'inputs':parent}), phase_root=Path(root), enabled=set(cell.runtime_arm.data()['enabled']))


def run_audited_phase(*, session, material, cell, objective, root, broker, inputs, image, timeout_seconds,
                      selected_job_id=None):
    """Bind actual inputs before dispatch; anchor completed witnesses in the trace."""
    from research_loop.modular.runtime import RunSession
    from research_loop.modular.exploration_scheduler_combination import run_phase
    if (type(session) is not RunSession or session._terminal or session.task.identity != cell.identity
            or session.task.content_hash != cell.task_digest or session.arm != cell.runtime_arm
            or session.lock.data()['package_digest'] != cell.package_digest
            or Path(root).absolute() != (session.sidecar.parent/'phase').absolute()):
        raise ContractError('audited phase must use its original task, arm, package and sidecar')
    if Path(root).exists() or any(record.data()['kind'] == 'execution_phase_inputs' for record in session.artifacts.records()):
        raise ContractError('one fresh phase per host catalogue required')
    bound = _inputs(material=material,cell=cell,objective=objective,inputs=inputs,image=image,
        timeout_seconds=timeout_seconds,selected_job_id=selected_job_id)
    descriptor = session.record_artifact(kind='execution_phase_inputs',module='P0',payload=bound,
        producer_source=source_snapshot(Path(__file__)))
    report = run_phase(material=material,cell=cell,objective=objective,root=root,broker=broker,inputs=inputs,
        image=image,timeout_seconds=timeout_seconds,selected_job_id=selected_job_id,
        artifact_bridge=_bridge(session.artifacts,root,cell,descriptor.content_hash))
    session.artifacts.verify()
    rows = session.artifacts.path.read_bytes().splitlines()
    # The following trace event binds the precise descriptor prefix; later
    # solver calls may append without mutating this completed phase evidence.
    session._record('audited_phase_closed',{'phase_digest':report.content_hash,
        'input_descriptor':descriptor.content_hash,'catalogue_prefix_count':len(rows),
        'catalogue_prefix_head':FrozenRecord(rows[-1].decode()).content_hash})
    return report


def verify_audited_phase(*, trace_path, material, cell, objective, root, image, timeout_seconds, inputs,
                         selected_job_id=None):
    """Read the actual phase and its source-bound, trace-anchored catalogue."""
    from research_loop.modular.runtime import verify_trace
    trace_path, root = Path(trace_path), Path(root)
    if root.absolute() != (trace_path.parent.parent/'phase').absolute():
        raise ContractError('audited phase reader requires the original sidecar')
    verify_trace(trace_path)
    events = [json.loads(line) for line in trace_path.read_bytes().splitlines()]
    if not events or events[0]['stage'] != 'objective_lock':
        raise ContractError('audited phase lacks its original task lock')
    lock = FrozenRecord.from_dict(events[0]['data'])
    if (lock.data()['identity'] != cell.identity.data() or lock.data()['task_digest'] != cell.task_digest
            or lock.data()['arm'] != cell.runtime_arm.data() or lock.data()['package_digest'] != cell.package_digest):
        raise ContractError('audited phase task, arm or package lock differs')
    path = trace_path.parent/'artifacts.jsonl'
    if not path.is_file(): raise ContractError('audited phase catalogue is missing')
    entries = [FrozenRecord(line.decode()) for line in path.read_bytes().splitlines()]
    if not entries: raise ContractError('audited phase catalogue is empty')
    first = entries[0].data()['descriptor']; binding = first['binding']
    if binding['lock_digest'] != lock.content_hash:
        raise ContractError('audited phase catalogue lock differs')
    catalogue = ArtifactCatalogue(path,identity=cell.identity,**binding,producer_source=first['producer_source'])
    records = catalogue.records(); bodies = [record.data() for record in records]
    if [body['payload']['canonical'] for body in bodies if body['kind']=='trace_event'] != events:
        raise ContractError('audited phase catalogue and original trace differ')
    found = [index for index,body in enumerate(bodies) if body['kind']=='execution_phase_inputs']
    if len(found) != 1: raise ContractError('audited phase requires one original input witness')
    index = found[0]; body = bodies[index]
    expected = _inputs(material=material,cell=cell,objective=objective,inputs=inputs,image=image,
        timeout_seconds=timeout_seconds,selected_job_id=selected_job_id)
    prior = [record for record in records[:index] if record.data()['kind']=='trace_event']
    if (not prior or body['payload']['canonical'] != expected.data() or body['module'] != 'P0'
            or body['status'] != 'produced' or body['parents'] != [prior[-1].content_hash]
            or body['producer_source'] != source_snapshot(Path(__file__))
            or body['config_refs'] != [{'kind':'run_lock','digest':lock.content_hash,'canonical':lock.data()}]
            or body['cost'] != {'known':False,'units':None}
            or body['control_sources'] or body['checks'] or body['optimizer_visible']):
        raise ContractError('audited phase input witness differs from actual invocation')
    phases = [i for i,value in enumerate(bodies) if value['kind'].startswith('phase_')]
    if (not phases or phases != list(range(index+1,phases[-1]+1))
            or bodies[phases[0]]['kind'] != 'phase_allocation' or bodies[phases[-1]]['kind'] != 'phase_receipt'):
        raise ContractError('audited phase witnesses are not an original contiguous transaction')
    end = phases[-1]+1
    report = verify_phase_artifacts(bridge=_bridge(catalogue,root,cell,records[index].content_hash),
        material=material,cell=cell,objective=objective,root=root,image=image,timeout_seconds=timeout_seconds,
        inputs=inputs,selected_job_id=selected_job_id)
    closed = {'phase_digest':report.content_hash,'input_descriptor':records[index].content_hash,
        'catalogue_prefix_count':end,'catalogue_prefix_head':entries[end-1].content_hash}
    if (end >= len(bodies) or bodies[end]['kind'] != 'trace_event'
            or bodies[end]['payload']['canonical']['stage'] != 'audited_phase_closed'
            or bodies[end]['payload']['canonical']['data'] != closed
            or sum(event['stage']=='audited_phase_closed' for event in events) != 1):
        raise ContractError('audited phase is not anchored before subsequent runtime work')
    return report
