"""Source-bound P0 evidence for legacy primary public TRAIN packets.

A successful packet is independently checked against caller-owned custody source
material. Failure records attest retained bytes only, including malformed partial
outputs; they cannot be returned as a successful packet.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError, canonical
from evaluation.modular.train_io import PrimaryTrainSource, _safe_path, prepare_primary_public_task

CAT = 'legacy-primary-artifacts.jsonl'
SEAL = CAT + '.seal.json'
PACKET = 'packet-seal.json'
RESERVATION = 'reservation.json'
FAILURE = 'failure.json'
FAILURE_SEAL = 'failure.seal.json'
FILES = ('data.csv', 'public.json')
SUCCESS_FILES = {*FILES, CAT, SEAL, PACKET, RESERVATION}
ALL_FILES = {*SUCCESS_FILES, FAILURE, FAILURE_SEAL}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sources():
    from research_loop.modular.benchmarks import blade, discovery
    return {'schema': 'legacy-primary-producers-v2',
            **{name: source_snapshot(_safe_path(path)) for name, path in {
                'exporter': Path(__file__).with_name('train_io.py'), 'adapter': Path(__file__),
                'blade_projection': Path(blade.__file__), 'discovery_projection': Path(discovery.__file__)}.items()}}


def ref(value):
    record = FrozenRecord.from_dict(value)
    return {'kind': 'legacy_primary_producer_sources', 'digest': record.content_hash, 'canonical': record.data()}


def put(path, raw):
    with _safe_path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(path):
    path = _safe_path(path)
    if not path.is_file():
        raise ContractError('primary packet file is missing')
    raw = path.read_bytes()
    return {'file': path.name, 'sha256': sha(raw), 'bytes': len(raw)}


def _read(path):
    try:
        return FrozenRecord(_safe_path(path).read_bytes().decode('utf-8').strip())
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractError('primary packet canonical record is unreadable') from exc


def _inventory(root, *, complete=False):
    root = _safe_path(root)
    if not root.is_dir():
        raise ContractError('primary packet directory is missing')
    paths = list(root.iterdir())
    # Check every component before opening any content, including seal files.
    for path in paths:
        if not _safe_path(path).is_file() or path.name not in ALL_FILES:
            raise ContractError('primary packet has an unregistered output')
    if complete and {path.name for path in paths} != SUCCESS_FILES:
        raise ContractError('primary packet is not a complete successful inventory')
    return {path.name: snapshot(path) for path in sorted(paths)}


def _source(source):
    if (type(source) is not PrimaryTrainSource or type(source.task) is not PublicTask
            or type(source.anchor) is not FrozenRecord or type(source.receipt) is not FrozenRecord
            or type(source.metadata) is not bytes or type(source.csv) is not bytes):
        raise ContractError('primary packet requires exact independently derived source material')
    task = source.task
    task.identity.require_train()
    anchor = source.anchor.data()
    required = {'schema', 'identity', 'inventory_digest', 'split_digest', 'inventory_row',
                'allocation', 'source_selector', 'metadata', 'csv'}
    if set(anchor) != required or anchor['schema'] != 'legacy-primary-source-v2':
        raise ContractError('primary source anchor schema differs')
    for field in ('inventory_digest', 'split_digest'):
        value = anchor[field]
        if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ContractError('primary source requires frozen version digests')
    from evaluation.modular.custody import InventoryItem
    row = anchor['inventory_row']
    try:
        InventoryItem.parse(row)
        hashes = row['content_hashes']
        if any(type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value) for value in hashes):
            raise ContractError('primary inventory requires content hashes')
        allocation = anchor['allocation']
        if set(allocation) not in ({'item', 'group', 'domain', 'official_split'},
                                  {'item', 'group', 'domain', 'official_split', 'exposure', 'custodian_qualified'}):
            raise ContractError('primary source allocation schema differs')
        if ('custodian_qualified' in allocation and type(allocation['custodian_qualified']) is not bool):
            raise ContractError('primary source allocation field types differ')
        metadata = anchor['metadata']
        csv_info = anchor['csv']
        for info, raw in ((metadata, source.metadata), (csv_info, source.csv)):
            if (set(info) != {'file', 'sha256', 'bytes'} or type(info['file']) is not str
                    or not info['file'] or Path(info['file']).name != info['file']
                    or '/' in info['file'] or '\\' in info['file']
                    or type(info['bytes']) is not int or info['bytes'] != len(raw)
                    or info['sha256'] != sha(raw) or info['sha256'] not in hashes):
                raise ContractError('primary source buffer differs from inventory')
        selector = {'metadata_file': metadata['file'], 'metadata_sha256': sha(source.metadata), 'query_index': 0}
        expected_allocation = {**allocation, 'item': task.identity.benchmark + ':' + task.identity.task_id,
            'group': task.identity.group_id, 'domain': 'train', 'official_split': row['official_split']}
        expected_anchor = {**anchor, 'identity': task.identity.data(), 'inventory_digest': task.identity.dataset_version,
                           'split_digest': task.identity.split_id, 'allocation': expected_allocation, 'source_selector': selector}
        if source.anchor != FrozenRecord.from_dict(expected_anchor):
            raise ContractError('primary source identity or selector differs')
        if row['benchmark'] != task.identity.benchmark or row['task_id'] != task.identity.task_id:
            raise ContractError('primary source inventory subject differs')
        raw_metadata = json.loads(source.metadata.decode('utf-8'))
        expected_task = prepare_primary_public_task(task.identity, row, raw_metadata, source.csv)
        expected_data_name = raw_metadata['datasets'][0]['name'] if task.identity.benchmark == 'discoverybench' else 'data.csv'
        if (csv_info['file'] != expected_data_name or task != expected_task
                or task.identity.benchmark == 'blade' and metadata['file'] != 'info.json'
                or task.identity.benchmark == 'discoverybench' and not (metadata['file'].startswith('metadata_') and metadata['file'].endswith('.json'))):
            raise ContractError('primary source public task or dataset selection differs')
        receipt = {'identity': task.identity.data(), 'source_group': task.identity.group_id,
            'official_split': row['official_split'], 'split_digest': task.identity.split_id,
            'csv_sha256': sha(source.csv), 'packet_hash': task.content_hash}
        if task.identity.benchmark == 'discoverybench':
            receipt['source_selector'] = selector
        if source.receipt != FrozenRecord.from_dict(receipt):
            raise ContractError('primary source public receipt differs')
    except (KeyError, IndexError, TypeError, AttributeError, UnicodeError, ValueError) as exc:
        raise ContractError('primary source material is malformed') from exc
    return FrozenRecord.from_dict({'schema': 'legacy-primary-packet-binding-v2', 'identity': task.identity.data(),
        'task_sha256': task.content_hash, 'anchor': anchor, 'sources': sources(),
        'train_only': True, 'scientific_validated': False})


def _descriptor(kind, payload, *, binding, identity, source, source_ref, parents=(), status='produced'):
    frozen = FrozenRecord.from_dict(payload)
    return FrozenRecord.from_dict({'schema': 'artifact-descriptor-v2', 'kind': kind, 'module': 'P0',
        'coverage': 'covered', 'identity': identity, 'binding': binding,
        'payload': {'canonical': frozen.data(), 'digest': frozen.content_hash,
                    'bytes': len(frozen.encoded.encode()), 'encoding': 'canonical_json'},
        'parents': list(parents), 'control_sources': [], 'status': status, 'cost': {'known': False, 'units': None},
        'checks': [], 'producer_source': source, 'config_refs': [source_ref],
        'optimizer_visible': False, 'scientific_validated': False})


def _attempt_binding(source_binding, retained):
    """Only the original attempt identity may vary from independent source data."""
    if type(retained) is not dict:
        raise ContractError('primary attempt binding must be an object')
    attempt_id = retained.get('attempt_id')
    if (type(attempt_id) is not str or len(attempt_id) != 32
            or any(char not in '0123456789abcdef' for char in attempt_id)):
        raise ContractError('primary attempt id must be a 32-character hexadecimal string')
    expected = FrozenRecord.from_dict({**source_binding.data(), 'attempt_id': attempt_id})
    if FrozenRecord.from_dict(retained) != expected:
        raise ContractError('primary attempt binding differs from independent source')
    return expected


def _failure(root, binding, stage, error):
    # Never retry/overwrite a partly completed primary catalogue or its seal.
    # Preserve malformed terminal bytes exactly and bind them in separate storage
    # evidence. A failure marker permanently excludes success verification.
    files = _inventory(root)
    body = FrozenRecord.from_dict({'schema': 'legacy-primary-failure-storage-v1', 'binding': binding.data(),
        'stage': stage, 'error_type': type(error).__name__, 'error': None, 'files': files,
        'status': 'failed', 'operation_validated': False, 'scientific_validated': False})
    put(root / FAILURE, (body.encoded + '\n').encode())
    put(root / FAILURE_SEAL, (FrozenRecord.from_dict({'schema': 'legacy-primary-failure-seal-v1',
        'failure': snapshot(root / FAILURE)}).encoded + '\n').encode())


def write(directory, source):
    root = _safe_path(directory)
    source_binding = _source(source)  # TRAIN and source contract before any mkdir/write.
    attempt_id = uuid4().hex
    binding = FrozenRecord.from_dict({**source_binding.data(), 'attempt_id': attempt_id})
    if root.exists():
        raise ContractError('primary packet directory already used')
    root.mkdir(parents=True, exist_ok=False)
    stage = 'reservation'
    try:
        put(root / RESERVATION, (binding.encoded + '\n').encode())
        src = binding.data()['sources']
        catalogue = ArtifactCatalogue(root / CAT, identity=source.task.identity, run_id=attempt_id,
            experiment_id='P0:legacy-primary-export', lock_digest=binding.content_hash, producer_source=src['adapter'])
        last = catalogue.append(kind='p0_legacy_primary_binding', module='P0', payload=binding,
                                config_refs=(ref(src),))
        for name, raw in zip(FILES, (source.csv, source.public)):
            stage = name
            put(root / name, raw)
            last = catalogue.append(kind='p0_legacy_primary_file', module='P0', payload=snapshot(root / name),
                parents=(last.content_hash,), producer_source=src['exporter'], config_refs=(ref(src),))
        stage = 'terminal'
        terminal = {'schema': 'legacy-primary-packet-terminal-v2', 'status': 'produced',
            'stage': 'complete', 'files': {name: snapshot(root / name) for name in FILES},
            'error_type': None, 'error': None, 'scientific_validated': False}
        catalogue.append(kind='p0_legacy_primary_terminal', module='P0', payload=terminal,
                         parents=(last.content_hash,), config_refs=(ref(src),))
        stage = 'catalogue_seal'
        seal = catalogue.seal()
        packet = FrozenRecord.from_dict({'schema': 'legacy-primary-train-packet-v2', 'binding': binding.data(),
                                         'seal': seal.data(), 'train_only': True})
        stage = 'packet_seal'
        put(root / PACKET, (packet.encoded + '\n').encode())
        stage = 'verification'
        return verify(root, source)
    except Exception as error:
        try:
            _failure(root, binding, stage, error)
        except Exception as closure_error:
            error.add_note('primary packet failure storage also failed: ' + type(closure_error).__name__)
        raise


def verify(directory, expected_source):
    """Read a successful packet against independent custody/source material."""
    root = _safe_path(directory)
    source_binding = _source(expected_source)
    _inventory(root, complete=True)
    binding = _attempt_binding(source_binding, _read(root / RESERVATION).data())
    packet = _read(root / PACKET)
    body = packet.data()
    if (set(body) != {'schema', 'binding', 'seal', 'train_only'} or body['schema'] != 'legacy-primary-train-packet-v2'
            or body['train_only'] is not True or FrozenRecord.from_dict(body['binding']) != binding):
        raise ContractError('primary packet binding differs from independent source')
    try:
        first = FrozenRecord((root / CAT).read_bytes().splitlines()[0].decode()).data()['descriptor']
        run_binding = first['binding']
        run_id = run_binding['run_id']
        if (set(run_binding) != {'run_id', 'experiment_id', 'lock_digest'} or type(run_id) is not str
                or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id)
                or run_id != binding.data()['attempt_id']
                or run_binding['experiment_id'] != 'P0:legacy-primary-export'
                or run_binding['lock_digest'] != binding.content_hash):
            raise ContractError('primary packet original run binding differs')
        catalogue = ArtifactCatalogue(root / CAT, identity=expected_source.task.identity, **run_binding)
        catalogue.verify(FrozenRecord.from_dict(body['seal']))
        records = catalogue.records()
    except (OSError, IndexError, KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise ContractError('primary packet catalogue is unreadable') from exc
    files = {name: snapshot(root / name) for name in FILES}
    terminal = {'schema': 'legacy-primary-packet-terminal-v2', 'status': 'produced', 'stage': 'complete',
                'files': files, 'error_type': None, 'error': None, 'scientific_validated': False}
    src = binding.data()['sources']
    expected_rows = [('p0_legacy_primary_binding', binding.data(), src['adapter']),
                     *[('p0_legacy_primary_file', files[name], src['exporter']) for name in FILES],
                     ('p0_legacy_primary_terminal', terminal, src['adapter'])]
    if len(records) != len(expected_rows):
        raise ContractError('primary packet descriptor inventory differs')
    parent = ()
    for actual, (kind, payload, producer) in zip(records, expected_rows):
        expected = _descriptor(kind, payload, binding=run_binding, identity=expected_source.task.identity.data(),
                               source=producer, source_ref=ref(src), parents=parent)
        if actual != expected:
            raise ContractError('primary packet descriptor differs from exact producer contract')
        parent = (actual.content_hash,)
    if (root / 'data.csv').read_bytes() != expected_source.csv:
        raise ContractError('primary packet CSV differs from independently read source')
    if (root / 'public.json').read_bytes() != expected_source.public:
        raise ContractError('primary packet public task or receipt differs from independent source')
    return packet


def inspect_failure(directory, expected_source):
    """Verify retained failure bytes; never return an accepted packet."""
    root = _safe_path(directory)
    source_binding = _source(expected_source)
    files = _inventory(root)
    if not {FAILURE, FAILURE_SEAL} <= set(files):
        raise ContractError('primary failure storage closure is missing')
    body = _read(root / FAILURE)
    failure = body.data()
    if (set(failure) != {'schema', 'binding', 'stage', 'error_type', 'error', 'files', 'status',
                        'operation_validated', 'scientific_validated'}
            or failure['stage'] not in {'reservation', *FILES, 'terminal', 'catalogue_seal', 'packet_seal', 'verification'}
            or type(failure['error_type']) is not str or not failure['error_type'] or failure['error'] is not None):
        raise ContractError('primary failure storage schema differs')
    binding = _attempt_binding(source_binding, failure['binding'])
    retained = {name: value for name, value in files.items() if name not in {FAILURE, FAILURE_SEAL}}
    expected = {'schema': 'legacy-primary-failure-storage-v1', 'binding': binding.data(),
        'stage': failure['stage'], 'error_type': failure['error_type'], 'error': None,
        'files': retained, 'status': 'failed', 'operation_validated': False, 'scientific_validated': False}
    if body != FrozenRecord.from_dict(expected) or _read(root / FAILURE_SEAL) != FrozenRecord.from_dict({
            'schema': 'legacy-primary-failure-seal-v1', 'failure': snapshot(root / FAILURE)}):
        raise ContractError('primary failure retained bytes or binding differ')
    # A malformed/partial journal remains raw storage evidence. Every readable
    # descriptor must still belong to this attempt; no second identity can be
    # introduced by coherently rehashing the separate failure manifest.
    if CAT in retained:
        for line in (root / CAT).read_bytes().splitlines():
            try:
                row = FrozenRecord(line.decode('utf-8')).data()
                run_id = row['descriptor']['binding']['run_id']
            except (UnicodeError, ValueError, KeyError, TypeError, ContractError):
                continue
            if type(run_id) is not str or run_id != binding.data()['attempt_id']:
                raise ContractError('primary failed catalogue belongs to another attempt')
    return FrozenRecord.from_dict({'schema': 'legacy-primary-failure-inspected-v1', 'status': 'failed',
        'attempt_id': binding.data()['attempt_id'],
        'stage': failure['stage'], 'error_type': failure['error_type'], 'error': None,
        'storage_integrity_verified': True, 'operation_validated': False, 'acceptance_eligible': False,
        'scientific_validated': False})
