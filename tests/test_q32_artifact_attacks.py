"""Independent Q3.2 custody attacks; every broker/model here is synthetic.

These tests exercise actual file writers and readers, not Docker correctness or
scientific validity. Originals and changed full-sidecar copies remain on disk.
"""
import json
from pathlib import Path
import shutil

import pytest

from evaluation.modular.q32_execution_verifier import verify_q32_execution
from research_loop.modular.benchmarks.execution import ExecutionReceipt, validate_artifact
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.q32_execution import Q32ExecutionStage, compile_q32_execution
from research_loop.ontology import ContractError
from test_q32_prospective_execution import IMAGE, fixture_response, setup


R = FrozenRecord.from_dict


class SyntheticBroker:
    """Typed receipts from a fixture; no program, subprocess, or Docker runs."""
    def __init__(self): self.calls = []

    def execute(self, request):
        n = len(self.calls); self.calls.append(request)
        observable, value = (('sum_x', 6), ('mean_x', 2), ('max_x', 3))[n]
        return ExecutionReceipt(request.identity, 'succeeded',
            validate_artifact(request.identity, 'program', request.program),
            R({'status': 'succeeded', 'stdout': json.dumps({'observable': observable, 'value': value}),
                'stderr': '', 'synthetic_no_process': True, 'input_artifacts': {
                    'public_csv': validate_artifact(request.identity, 'public_csv', request.inputs['public_csv']).record.data()}}))


def make_case(root, variant='joint'):
    _, _, packets, materials, verifier = setup(root)
    compiled = compile_q32_execution(packets, materials, image=IMAGE)
    cell = next(cell for cell in compiled.data()['cells'] if cell['variant'] == variant)
    packet = next(packet for packet in packets if packet.task.content_hash == cell['task_digest'])
    (root/'independent-inputs.json').write_bytes(R({'compiled': compiled.data(), 'cell': cell,
        'packet': packet.task.data(), 'packet_receipt': packet.receipt.data(), 'materials': materials}).encoded.encode())
    stage = Q32ExecutionStage(compiled, cell, packet, sidecar=root/'original', verifier=verifier)
    return stage, compiled


def complete_case(root, variant='joint'):
    stage, compiled = make_case(root, variant); calls = []; broker = SyntheticBroker()
    def model(request): calls.append(request); return fixture_response(request)
    result = stage.run(model, broker)
    assert result.data()['failure'] is None
    assert result.data()['scientific_validated'] is False
    assert len(calls) == 4 and len(broker.calls) == 3
    verify_q32_execution(stage._session.sidecar/'trace.jsonl', compiled)
    return stage, compiled, calls, broker


def copy_case(stage, compiled, root):
    target = root/'attack'; shutil.copytree(stage._session.sidecar, target)
    # A copied original must work before mutation, or the attack would only
    # prove that a path relocation/missing sibling causes rejection.
    verify_q32_execution(target/'trace.jsonl', compiled)
    return target


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def rehash_catalogue(root, edit):
    rows = [json.loads(line) for line in (root/'artifacts.jsonl').read_bytes().splitlines()]
    mapping = {}; previous = None
    for row in rows:
        old = row['descriptor_digest']; body = row['descriptor']; edit(body)
        body['parents'] = [mapping.get(parent, parent) for parent in body['parents']]
        payload = R(body['payload']['canonical'])
        body['payload'] = {'canonical': payload.data(), 'digest': payload.content_hash,
            'bytes': len(payload.encoded.encode()), 'encoding': 'canonical_json'}
        row['descriptor_digest'] = R(body).content_hash; mapping[old] = row['descriptor_digest']
        row['previous'] = previous; previous = R(row).content_hash
    (root/'artifacts.jsonl').write_bytes(b''.join((R(row).encoded+'\n').encode() for row in rows))
    seal = json.loads((root/'artifacts.jsonl.seal.json').read_bytes())
    seal.update(count=len(rows), head=previous)
    (root/'artifacts.jsonl.seal.json').write_bytes((R(seal).encoded+'\n').encode())


@pytest.mark.parametrize('variant,count', [('joint', 1), ('separate', 3)])
def test_unique_prediction_freezes_are_actual_durable_module_outputs(tmp_path, variant, count):
    stage, compiled = make_case(tmp_path, variant)
    root = stage._session.sidecar
    events = [json.loads(line) for line in (root/'predictions.jsonl').read_bytes().splitlines()]
    descriptors = [json.loads(line)['descriptor'] for line in (root/'artifacts.jsonl').read_bytes().splitlines()]
    predictions = [row for row in descriptors if row['kind']=='journal_event' and row['module']=='M4']
    assert len(events)==len(predictions)==count
    assert all(event['event']=='freeze' for event in events)
    assert [row['payload']['canonical']['event'] for row in predictions]==events
    assert all(row['status']=='produced' and row['scientific_validated'] is False for row in predictions)
    assert not (root/'reviews.jsonl').exists()
    assert stage._session._next_call==stage._session._attempts==0


@pytest.mark.parametrize('name', ['predictions.jsonl','execution-seal.json','result.json','artifacts.jsonl.seal.json'])
def test_exact_file_drift_is_rejected_without_callbacks_and_original_survives(tmp_path, name):
    stage, compiled, calls, broker = complete_case(tmp_path)
    root=copy_case(stage, compiled, tmp_path); before=tree_bytes(stage._session.sidecar)
    (root/name).write_bytes((root/name).read_bytes()+b' ')
    with pytest.raises(ContractError): verify_q32_execution(root/'trace.jsonl',compiled)
    verify_q32_execution(stage._session.sidecar/'trace.jsonl',compiled)
    assert before==tree_bytes(stage._session.sidecar)
    assert len(calls)==4 and len(broker.calls)==3


def test_missing_journal_reader_does_not_construct_or_touch_a_replay_writer(tmp_path):
    stage,compiled,calls,broker=complete_case(tmp_path); root=copy_case(stage,compiled,tmp_path)
    (root/'predictions.jsonl').unlink(); before=tree_bytes(root)
    with pytest.raises(ContractError): verify_q32_execution(root/'trace.jsonl',compiled)
    assert before==tree_bytes(root) and not (root/'predictions.jsonl').exists()
    assert len(calls)==4 and len(broker.calls)==3


def test_prediction_disk_drift_stops_before_second_model_callback(tmp_path):
    stage,compiled=make_case(tmp_path); calls=[]; broker=SyntheticBroker()
    def model(request):
        calls.append(request)
        response=fixture_response(request)
        path=stage._session.sidecar/'predictions.jsonl'; path.write_bytes(path.read_bytes()+b' ')
        return response
    try: result=stage.run(model,broker)
    except ContractError: result=None
    assert len(calls)==1 and broker.calls==[] and stage._session._attempts==0
    assert result is None or result.data()['failure'] is not None
    assert (stage._session.sidecar/'audit-failure.json').exists()


def test_execution_seal_byte_drift_stops_before_first_broker_call(tmp_path):
    stage,compiled=make_case(tmp_path); calls=[]; broker=SyntheticBroker()
    def model(request): calls.append(request); return fixture_response(request)
    seal=stage.produce(model); path=stage._session.sidecar/'execution-seal.json'
    path.write_bytes(path.read_bytes()+b' '); job=seal.data()['jobs'][0]
    with pytest.raises(ContractError):
        stage.execute_next(broker=broker,plan_id=job['plan_id'],program=job['program'],csv_path=stage.packet.csv_path)
    assert len(calls)==3 and broker.calls==[] and stage._session._attempts==0


@pytest.mark.parametrize('name', ['trace.jsonl','predictions.jsonl','execution-seal.json','result.json','artifacts.jsonl'])
def test_linked_original_outputs_are_rejected_before_content_reads(tmp_path,monkeypatch,name):
    stage,compiled,calls,broker=complete_case(tmp_path); root=copy_case(stage,compiled,tmp_path)
    path=root/name; victim=tmp_path/'link-victim'; victim.write_bytes(path.read_bytes()); path.unlink()
    try: path.symlink_to(victim)
    except OSError as exc: pytest.skip('symlink unavailable: '+type(exc).__name__)
    original_read=Path.read_bytes; original_text=Path.read_text; victim_read=[]
    def read(self):
        if self==path or self==victim: victim_read.append(self); raise AssertionError('read through unsafe output')
        return original_read(self)
    def read_text(self,*args,**kwargs):
        if self==path or self==victim: victim_read.append(self); raise AssertionError('read through unsafe output')
        return original_text(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_bytes',read)
    monkeypatch.setattr(Path,'read_text',read_text)
    with pytest.raises(ContractError): verify_q32_execution(root/'trace.jsonl',compiled)
    assert victim_read==[] and len(calls)==4 and len(broker.calls)==3


@pytest.mark.parametrize('target', ['q32_execution_seal','q32_observation','q32_comparison_ready','q32_phase_result'])
def test_rehashed_missing_consumer_parents_fail_semantics_not_outer_checksums(tmp_path,target):
    from research_loop.modular.artifact_catalogue import ArtifactCatalogue
    from research_loop.modular.q32_artifacts import CLOSURE, inventory
    stage,compiled,calls,broker=complete_case(tmp_path); root=copy_case(stage,compiled,tmp_path)
    changed=[]
    def edit(body):
        if body['kind']=='q32_output' and body['payload']['canonical']['stage']==target:
            changed.append(body['parents']); body['parents']=[]
    rehash_catalogue(root,edit)
    assert changed and all(parents for parents in changed)
    closure=json.loads((root/CLOSURE).read_bytes()); closure['files']=inventory(root)
    (root/CLOSURE).write_bytes((R(closure).encoded+'\n').encode())
    # The generic catalogue and its recomputed seal are structurally valid.
    # Rejection must come from the Q3.2 producer-consumer edge contract.
    ArtifactCatalogue(root/'artifacts.jsonl',identity=stage.packet.task.identity,**closure['binding']).verify()
    with pytest.raises(ContractError,match='dependency'):
        verify_q32_execution(root/'trace.jsonl',compiled)
    verify_q32_execution(stage._session.sidecar/'trace.jsonl',compiled)
    assert len(calls)==4 and len(broker.calls)==3


def test_changed_literal_program_with_rehashed_inventory_is_not_original_execution(tmp_path):
    from research_loop.modular.q32_artifacts import CLOSURE, inventory
    stage,compiled,calls,broker=complete_case(tmp_path); root=copy_case(stage,compiled,tmp_path)
    (root/'analysis-1.py').write_bytes(b'print("forged program after execution")\n')
    closure=json.loads((root/CLOSURE).read_bytes()); closure['files']=inventory(root)
    (root/CLOSURE).write_bytes((R(closure).encoded+'\n').encode())
    with pytest.raises(ContractError): verify_q32_execution(root/'trace.jsonl',compiled)
    verify_q32_execution(stage._session.sidecar/'trace.jsonl',compiled)
    assert len(calls)==4 and len(broker.calls)==3


def test_first_program_byte_drift_blocks_second_execution(tmp_path):
    stage,compiled=make_case(tmp_path); calls=[]; broker=SyntheticBroker()
    def model(request): calls.append(request); return fixture_response(request)
    seal=stage.produce(model)
    def execute(job):
        return stage.execute_next(broker=broker,plan_id=job['plan_id'],program=job['program'],csv_path=stage.packet.csv_path)
    execute(seal.data()['jobs'][0])
    (stage._session.sidecar/'analysis-1.py').write_bytes(b'print("changed original")\n')
    with pytest.raises(ContractError): execute(seal.data()['jobs'][1])
    assert len(calls)==3 and len(broker.calls)==1 and stage._session._attempts==1
