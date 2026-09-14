"""Synthetic source -> exporter -> real consumer boundary regression tests."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from evaluation.modular import legacy_primary_packet_artifacts as artifacts
from evaluation.modular.train_io import (TrainPacketExporter, read_primary_train_sources,
                                        verify_primary_train_packets)
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import ContractError
from test_modular_train_io import fixture

ITEMS = ('discoverybench:synth:train:family_1_1', 'blade:fish')


def _setup(tmp_path):
    snapshot, custody = fixture(tmp_path)
    # Retain the actual independent synthetic custody input before any packet
    # producer runs, so later archive readers need not infer it from a packet.
    _put(tmp_path / 'independent-custody.json', {'schema': 'synthetic-primary-custody-input-v1',
        'state': custody.state, 'identities': [identity.data() for identity in custody.export_train()]})
    sources = read_primary_train_sources(custody, snapshot, ITEMS)
    return snapshot, custody, sources


def _record(path):
    return FrozenRecord(path.read_bytes().decode().strip())


def _put(path, body):
    path.write_bytes((FrozenRecord.from_dict(body).encoded + '\n').encode())


def _reseal(root, mutate=None):
    """Repair every catalogue hash and seal; semantic forgeries remain visible."""
    binding = _record(root / artifacts.RESERVATION)
    entries = [FrozenRecord(line).data()['descriptor'] for line in (root / artifacts.CAT).read_text().splitlines()]
    def snapshot(name):
        raw = (root / name).read_bytes()
        return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    files = {name: snapshot(name) for name in artifacts.FILES}
    rebuilt, parent = [], None
    for descriptor in entries:
        kind = descriptor['kind']
        descriptor['binding']['lock_digest'] = binding.content_hash
        payload = descriptor['payload']['canonical']
        if kind == 'p0_legacy_primary_binding': payload = binding.data()
        elif kind == 'p0_legacy_primary_file': payload = files[payload['file']]
        elif kind == 'p0_legacy_primary_terminal': payload['files'] = files
        if mutate: mutate(descriptor, payload)
        frozen = FrozenRecord.from_dict(payload)
        descriptor['payload'] = {'canonical': frozen.data(), 'digest': frozen.content_hash,
                                 'bytes': len(frozen.encoded.encode()), 'encoding': 'canonical_json'}
        descriptor['parents'] = [parent] if parent else []
        row = FrozenRecord.from_dict(descriptor)
        rebuilt.append(FrozenRecord.from_dict({'schema': 'artifact-catalogue-entry-v2', 'sequence': len(rebuilt),
            'previous': rebuilt[-1].content_hash if rebuilt else None, 'descriptor_digest': row.content_hash,
            'descriptor': row.data()}))
        parent = row.content_hash
    (root / artifacts.CAT).write_bytes(''.join(row.encoded + '\n' for row in rebuilt).encode())
    first = rebuilt[0].data()['descriptor']
    seal = {'schema': 'artifact-catalogue-seal-v1', 'count': len(rebuilt), 'head': rebuilt[-1].content_hash,
            'binding': first['binding']}
    _put(root / artifacts.SEAL, seal)
    _put(root / artifacts.PACKET, {'schema': 'legacy-primary-train-packet-v2', 'binding': binding.data(),
                                  'seal': seal, 'train_only': True})
    ArtifactCatalogue(root / artifacts.CAT, identity=DataIdentity.parse(first['identity']), **first['binding']).verify()


def test_actual_exporter_and_consumer_use_independent_custody_source(tmp_path):
    snapshot, custody, sources = _setup(tmp_path)
    packets = TrainPacketExporter(custody, snapshot, tmp_path / 'out').export(ITEMS)
    before = {p: p.read_bytes() for p in (tmp_path / 'out').rglob('*') if p.is_file()}
    assert verify_primary_train_packets(packets, custody=custody, snapshot_root=snapshot,
        item_ids=ITEMS, output_root=tmp_path / 'out') == sources
    assert before == {p: p.read_bytes() for p in (tmp_path / 'out').rglob('*') if p.is_file()}
    for packet, source in zip(packets, sources):
        sealed = artifacts.verify(packet.packet_path.parent, source)
        assert sealed.data()['binding']['anchor']['inventory_digest'] == custody.state['inventory_digest']
        terminal = FrozenRecord((packet.packet_path.parent / artifacts.CAT).read_text().splitlines()[-1]).data()['descriptor']['payload']['canonical']
        assert 'engineering_verified' not in terminal and terminal['scientific_validated'] is False


@pytest.mark.parametrize('mutation', ['task', 'receipt', 'csv_path', 'public_path', 'order'])
def test_consumer_rejects_packet_fields_before_execution(tmp_path, mutation):
    snapshot, custody, _ = _setup(tmp_path)
    packets = TrainPacketExporter(custody, snapshot, tmp_path / 'out').export(ITEMS)
    packet = packets[0]
    if mutation == 'task': packet = replace(packet, task=PublicTask.create(packet.task.identity, {'question': 'forged'}))
    elif mutation == 'receipt': packet = replace(packet, receipt=FrozenRecord.from_dict({**packet.receipt.data(), 'csv_sha256': 'f' * 64}))
    elif mutation == 'csv_path': packet = replace(packet, csv_path=packets[1].csv_path)
    elif mutation == 'public_path': packet = replace(packet, packet_path=packets[1].packet_path)
    changed = tuple(reversed(packets)) if mutation == 'order' else (packet, packets[1])
    with pytest.raises(ContractError, match='consumer packet fields'):
        verify_primary_train_packets(changed, custody=custody, snapshot_root=snapshot,
                                     item_ids=ITEMS, output_root=tmp_path / 'out')


@pytest.mark.parametrize('mutation', ['public_task', 'receipt', 'csv', 'descriptor', 'source', 'selector', 'field_types', 'terminal_claim'])
def test_coherently_rehashed_packet_rejected_by_independent_reader(tmp_path, mutation):
    _, _, sources = _setup(tmp_path)
    source = sources[0]; root = tmp_path / 'packet'
    artifacts.write(root, source)
    if mutation in {'public_task', 'receipt'}:
        body = _record(root / 'public.json').data()
        if mutation == 'receipt': body['receipt']['csv_sha256'] = 'e' * 64
        else: body['task']['payload'] = {'question': 'forged'}
        _put(root / 'public.json', body)
    elif mutation == 'csv': (root / 'data.csv').write_bytes(b'x\n999\n')
    elif mutation in {'selector', 'field_types'}:
        body = _record(root / artifacts.RESERVATION).data()
        if mutation == 'selector': body['anchor']['source_selector']['query_index'] = 1
        else: body['train_only'] = 1
        _put(root / artifacts.RESERVATION, body)
    def change(descriptor, payload):
        if mutation == 'descriptor': descriptor['optimizer_visible'] = True
        elif mutation == 'source': descriptor['producer_source'] = artifacts.sources()['exporter']
        elif mutation == 'terminal_claim' and descriptor['kind'] == 'p0_legacy_primary_terminal':
            payload['engineering_verified'] = True
    _reseal(root, change)
    with pytest.raises(ContractError): artifacts.verify(root, source)


def test_wrong_independent_anchor_and_unverified_source_dict_are_rejected(tmp_path):
    _, _, sources = _setup(tmp_path)
    artifacts.write(tmp_path / 'packet', sources[0])
    with pytest.raises(ContractError): artifacts.verify(tmp_path / 'packet', sources[1])
    with pytest.raises(ContractError): artifacts.write(tmp_path / 'arbitrary', {'anchor': {}, 'public': b'{}'})
    bad = replace(sources[0], task=PublicTask.create(sources[0].task.identity, {'question': 'forged'}))
    with pytest.raises(ContractError): artifacts.write(tmp_path / 'bad-task', bad)
    assert not (tmp_path / 'arbitrary').exists() and not (tmp_path / 'bad-task').exists()


@pytest.mark.parametrize('mutation', ['inventory_hash', 'split_hash', 'content_hashes', 'selector_source'])
def test_independent_custody_and_source_drift_blocks_existing_packet(tmp_path, mutation):
    snapshot, custody, _ = _setup(tmp_path)
    packets = TrainPacketExporter(custody, snapshot, tmp_path / 'out').export(ITEMS)
    if mutation == 'inventory_hash': custody.state['inventory_digest'] = 'f' * 64
    elif mutation == 'split_hash': custody.state['split']['digest'] = 'e' * 64
    elif mutation == 'content_hashes': custody.state['inventory'][0]['content_hashes'] = ['d' * 64]
    else:
        metadata = snapshot / 'discovery/upstream/discoverybench/synth/train/family_1_1/metadata_1.json'
        metadata.write_bytes(b'{"queries":[{"question":"new source"}]}')
    with pytest.raises(ContractError):
        verify_primary_train_packets(packets, custody=custody, snapshot_root=snapshot,
                                     item_ids=ITEMS, output_root=tmp_path / 'out')


@pytest.mark.parametrize('stage', ['reservation', 'data.csv', 'public.json', 'catalogue_seal', 'packet_seal', 'terminal'])
def test_partial_write_and_seal_failure_preserve_original_bytes_and_error(tmp_path, monkeypatch, stage):
    _, _, sources = _setup(tmp_path)
    source = sources[0]; root = tmp_path / 'packet'; error = RuntimeError('original '+stage)
    real_put, real_append = artifacts.put, ArtifactCatalogue.append
    seal_calls = []
    def broken_put(path, raw):
        target = artifacts.RESERVATION if stage == 'reservation' else artifacts.PACKET if stage == 'packet_seal' else stage
        if path.name == target:
            path.write_bytes(b'partial malformed bytes')
            raise error
        return real_put(path, raw)
    def broken_seal(self):
        seal_calls.append(1)
        raise error
    def broken_append(self, **kwargs):
        if kwargs['kind'] == 'p0_legacy_primary_terminal':
            with self.path.open('ab') as stream: stream.write(b'{partial-terminal')
            raise error
        return real_append(self, **kwargs)
    monkeypatch.setattr(artifacts, 'put', broken_put)
    if stage == 'catalogue_seal': monkeypatch.setattr(ArtifactCatalogue, 'seal', broken_seal)
    if stage == 'terminal': monkeypatch.setattr(ArtifactCatalogue, 'append', broken_append)
    with pytest.raises(RuntimeError) as caught: artifacts.write(root, source)
    assert caught.value is error
    if stage == 'catalogue_seal': assert seal_calls == [1]
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    report = artifacts.inspect_failure(root, source).data()
    assert report['stage'] == stage and report['error'] is None
    assert report['error_type'] == type(error).__name__
    assert report['storage_integrity_verified'] is True and report['acceptance_eligible'] is False
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ContractError): artifacts.verify(root, source)
    retained = next(name for name in before if name not in {artifacts.FAILURE, artifacts.FAILURE_SEAL})
    attack = tmp_path / 'attack'
    shutil.copytree(root, attack)
    (attack / retained).write_bytes(b'changed failed bytes')
    with pytest.raises(ContractError): artifacts.inspect_failure(attack, source)
    assert artifacts.inspect_failure(root, source).data()['storage_integrity_verified'] is True


def test_failure_storage_failure_cannot_replace_primary_exception(tmp_path, monkeypatch):
    _, _, sources = _setup(tmp_path)
    real_put = artifacts.put; error = OSError('primary write failed')
    def broken(path, raw):
        if path.name == 'public.json': raise error
        if path.name == artifacts.FAILURE: raise RuntimeError('secondary closure failed')
        return real_put(path, raw)
    monkeypatch.setattr(artifacts, 'put', broken)
    with pytest.raises(OSError) as caught: artifacts.write(tmp_path / 'packet', sources[0])
    assert caught.value is error
    assert caught.value.__notes__ == ['primary packet failure storage also failed: RuntimeError']
    with pytest.raises(ContractError): artifacts.inspect_failure(tmp_path / 'packet', sources[0])


def test_validation_in_whole_selection_is_rejected_before_source_read_or_write(tmp_path, monkeypatch):
    snapshot, custody, _ = _setup(tmp_path)
    identity = custody.identities[1]
    custody.identities[1] = replace(identity, domain='validation')
    def forbidden(*_args, **_kwargs): raise AssertionError('source content read before TRAIN preflight')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    with pytest.raises(ContractError): TrainPacketExporter(custody, snapshot, tmp_path / 'out').export(ITEMS)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('target', ['output', 'snapshot', 'packet_file'])
def test_link_paths_are_refused_before_read_or_mkdir(tmp_path, monkeypatch, target):
    snapshot, custody, sources = _setup(tmp_path)
    real = tmp_path / 'real'; real.mkdir()
    linked = tmp_path / 'linked'
    try: linked.symlink_to(real, target_is_directory=True)
    except OSError as exc: pytest.skip('host cannot create symlink: '+str(exc))
    if target == 'packet_file':
        artifacts.write(tmp_path / 'packet', sources[0])
        public = tmp_path / 'packet' / 'public.json'; public.unlink(); public.symlink_to(real / 'missing.json')
    def forbidden(*_args, **_kwargs): raise AssertionError('linked path content read')
    if target in {'output', 'snapshot'}: monkeypatch.setattr(Path, 'read_bytes', forbidden)
    with pytest.raises(ContractError):
        if target == 'output': TrainPacketExporter(custody, snapshot, linked / 'out').export(ITEMS)
        elif target == 'snapshot': TrainPacketExporter(custody, linked, tmp_path / 'out').export(ITEMS)
        else: artifacts.verify(tmp_path / 'packet', sources[0])
    assert list(real.iterdir()) == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction semantics')
@pytest.mark.parametrize('target', ['output', 'snapshot'])
def test_windows_junction_ancestor_is_refused_before_content_access(tmp_path, monkeypatch, target):
    snapshot, custody, _ = _setup(tmp_path)
    real = tmp_path / 'real'; real.mkdir()
    linked = tmp_path / 'junction'
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(linked), str(real)], check=True, capture_output=True)
    assert linked.is_junction()
    def forbidden(*_args, **_kwargs): raise AssertionError('junction content read before path rejection')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    with pytest.raises(ContractError):
        TrainPacketExporter(custody, linked if target == 'snapshot' else snapshot,
                            linked / 'out' if target == 'output' else tmp_path / 'out').export(ITEMS)
    assert not (real / 'out').exists()


@pytest.mark.parametrize('tamper', [False, True])
def test_actual_controller_gate_precedes_compile_and_model_calls(tmp_path, monkeypatch, tamper):
    import research_loop.modular.train_controller as controller
    from research_loop.modular.runtime import AuditVerifier
    from test_modular_train_controller import snapshot_and_custody, config, model_port
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = config(custody, snapshot, tmp_path)
    model = model_port(tmp_path, monkeypatch)
    compiled = []
    class StopAfterGate(RuntimeError): pass
    def stop(**kwargs):
        compiled.append(kwargs)
        raise StopAfterGate('synthetic stop before model execution')
    monkeypatch.setattr(controller, 'compile_train_panel', stop)
    original_export = TrainPacketExporter.export
    def export(self, ids):
        packets = original_export(self, ids)
        if tamper:
            root = packets[0].packet_path.parent
            (root / 'data.csv').write_bytes(b'x\n999\n')
            _reseal(root)
        return packets
    monkeypatch.setattr(TrainPacketExporter, 'export', export)
    with pytest.raises(ContractError if tamper else StopAfterGate):
        controller.run_q31_train_panel(frozen, custody=custody, snapshot_root=snapshot,
            export_root=tmp_path / 'export', run_root=tmp_path / 'run', model=model,
            audit_verifier=AuditVerifier({'a': b'a'*32, 'b': b'b'*32}))
    assert bool(compiled) is (not tamper)
    assert model.ledger['calls'] == []
    attempt = _record(tmp_path / 'run/controller-attempt.json').data()
    assert attempt['status'] == 'blocked_before_execution'


def test_failure_error_text_is_never_exported_even_when_exception_contains_private_context(tmp_path, monkeypatch):
    _, _, sources = _setup(tmp_path)
    source = sources[0]; root = tmp_path / 'packet'
    sentinel = 'PRIVATE-EXCEPTION-CONTEXT-SENTINEL-91'
    error = RuntimeError(sentinel)
    real_put = artifacts.put
    def fail(path, raw):
        if path.name == 'public.json': raise error
        return real_put(path, raw)
    monkeypatch.setattr(artifacts, 'put', fail)
    with pytest.raises(RuntimeError) as caught: artifacts.write(root, source)
    assert caught.value is error and str(caught.value) == sentinel
    assert all(sentinel.encode() not in path.read_bytes() for path in root.iterdir())
    report = artifacts.inspect_failure(root, source)
    assert report.data()['error'] is None and sentinel not in report.encoded
    attack = tmp_path / 'attack'; shutil.copytree(root, attack)
    body = _record(attack / artifacts.FAILURE).data(); body['error'] = sentinel
    _put(attack / artifacts.FAILURE, body)
    raw = (attack / artifacts.FAILURE).read_bytes()
    _put(attack / artifacts.FAILURE_SEAL, {'schema': 'legacy-primary-failure-seal-v1',
        'failure': {'file': artifacts.FAILURE, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}})
    with pytest.raises(ContractError): artifacts.inspect_failure(attack, source)


@pytest.mark.parametrize('caller', ['combination', 'q32'])
@pytest.mark.parametrize('tamper', [False, True])
def test_other_actual_legacy_callers_gate_packets_before_return_or_execution(tmp_path, monkeypatch, caller, tamper):
    from test_modular_train_controller import snapshot_and_custody
    import evaluation.modular.train_io as train_io
    from research_loop.modular.combination_train_source import CombinationTrainSource
    import research_loop.modular.q32_execution as q32
    snapshot, custody = snapshot_and_custody(tmp_path)
    body = {'item_ids': list(ITEMS), 'task_bindings': {
        identity.benchmark + ':' + identity.task_id: {'identity': identity.data()}
        for identity in custody.export_train()}}
    export_root = tmp_path / 'export'
    original_export, original_gate = TrainPacketExporter.export, train_io.verify_primary_train_packets
    gate_calls, phases = [], []
    def export(self, items):
        packets = original_export(self, items)
        if tamper:
            packet_root = packets[0].packet_path.parent
            (packet_root / 'data.csv').write_bytes(b'x\n999\n')
            _reseal(packet_root)
        return packets
    def gate(packets, **kwargs):
        gate_calls.append(kwargs)
        return original_gate(packets, **kwargs)
    def compile_packets(*args, **kwargs):
        phases.append('compile')
        return FrozenRecord.from_dict({'synthetic': 'stop before broker'})
    def after_compile(*args, **kwargs):
        phases.append('execution-boundary')
        return 'synthetic-boundary-reached'
    def forbidden(*args, **kwargs): raise AssertionError('model or Docker must not run')
    monkeypatch.setattr(TrainPacketExporter, 'export', export)
    monkeypatch.setattr(train_io, 'verify_primary_train_packets', gate)
    monkeypatch.setattr(q32, 'compile_q32_execution', compile_packets)
    monkeypatch.setattr(q32, '_run_q32_compiled', after_compile)
    monkeypatch.setattr(q32, 'DockerExecutionBroker', forbidden)
    def invoke():
        if caller == 'combination':
            return CombinationTrainSource(body, custody=custody, prospective_exporter=None,
                                          snapshot=snapshot, exported=export_root).export()
        return q32.run_q32_execution_panel(custody=custody, snapshot_root=snapshot,
            export_root=export_root, run_root=tmp_path / 'run', item_ids=ITEMS,
            material_by_task={}, image='synthetic-no-execution', model_factory=forbidden, verifier=None)
    if tamper:
        with pytest.raises(ContractError): invoke()
        assert phases == []
    else:
        result = invoke()
        if caller == 'combination': assert len(result) == 2 and phases == []
        else: assert result == 'synthetic-boundary-reached' and phases == ['compile', 'execution-boundary']
    assert gate_calls == [dict(custody=custody, snapshot_root=snapshot, item_ids=body['item_ids'] if caller == 'combination' else ITEMS,
                               output_root=export_root)]


def test_same_source_has_distinct_attempt_ids_bound_to_success_catalogues(tmp_path):
    _, _, sources = _setup(tmp_path)
    ids = []
    for name in ('first', 'second'):
        root = tmp_path / name
        packet = artifacts.write(root, sources[0])
        attempt = packet.data()['binding']['attempt_id']
        first = FrozenRecord((root / artifacts.CAT).read_text().splitlines()[0]).data()['descriptor']
        assert first['binding']['run_id'] == attempt
        assert len(attempt) == 32 and all(char in '0123456789abcdef' for char in attempt)
        ids.append(attempt)
    assert ids[0] != ids[1]


@pytest.mark.parametrize('stage', ['reservation', 'public.json'])
@pytest.mark.parametrize('invalid', [True, 'not-an-attempt', 'f' * 32])
def test_failed_attempt_id_is_checked_even_before_catalogue_exists(tmp_path, monkeypatch, stage, invalid):
    _, _, sources = _setup(tmp_path)
    source = sources[0]; root = tmp_path / 'packet'; real_put = artifacts.put
    def fail(path, raw):
        target = artifacts.RESERVATION if stage == 'reservation' else stage
        if path.name == target:
            path.write_bytes(b'partial reservation or output')
            raise RuntimeError('original failure remains caller-only')
        return real_put(path, raw)
    monkeypatch.setattr(artifacts, 'put', fail)
    with pytest.raises(RuntimeError): artifacts.write(root, source)
    original = artifacts.inspect_failure(root, source).data()['attempt_id']
    assert len(original) == 32
    attack = tmp_path / 'attack'; shutil.copytree(root, attack)
    body = _record(attack / artifacts.FAILURE).data(); body['binding']['attempt_id'] = invalid
    _put(attack / artifacts.FAILURE, body)
    raw = (attack / artifacts.FAILURE).read_bytes()
    _put(attack / artifacts.FAILURE_SEAL, {'schema': 'legacy-primary-failure-seal-v1',
        'failure': {'file': artifacts.FAILURE, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}})
    if stage == 'reservation' and invalid == 'f' * 32:
        # No readable original catalogue exists: storage-only can check format,
        # not authenticate an external historical identity. Never accept success.
        assert artifacts.inspect_failure(attack, source).data()['acceptance_eligible'] is False
    else:
        with pytest.raises(ContractError): artifacts.inspect_failure(attack, source)
    with pytest.raises(ContractError): artifacts.verify(attack, source)
