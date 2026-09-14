"""Actual TRAIN operation outputs; audit access does not grant activation authority."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.ontology import ContractError

_CATALOGUE = 'operation-artifacts.jsonl'
_BLOBS = 'operation-blobs'
_CLOSURE = 'operation-artifact-closure.json'
_META = {_CATALOGUE, _CATALOGUE+'.seal.json', _CLOSURE, 'receipt.json'}
_KNOWN = {'operations.jsonl', 'state.sqlite', 'shadow.sqlite', 'deployment.json',
          'deployment.json.sha256', 'deployment.json.previous', 'deployment.json.previous.sha256'}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ContractError('operation artifacts require original non-linked paths')
    return path


def _sources():
    here = Path(__file__)
    return {name: source_snapshot(here.parent/name) for name in
            ('train_operation_artifacts.py', 'train_operations.py', 'deployment.py', 'modules/improvement.py')}


def _inputs(plan, cell, parent, candidate, histories, authority):
    from research_loop.modular.train_operations import _subject
    matches = [t.task for t in plan.targets if t.task.content_hash == cell['task_digest']]
    if len(matches) != 1:
        raise ContractError('operation artifact requires its unique actual TRAIN task')
    task = matches[0]; task.identity.require_train()
    body = {'schema': 'train-operation-artifact-inputs-v1', 'subject': _subject(plan, cell, candidate, parent),
            'task': task.data(), 'cell': cell, 'experiment': plan.record.data()['experiment_id'],
            'parent': parent.record.data(), 'candidate': candidate.record.data(),
            'training_configuration_sources': [h.binding.data() for h in histories],
            'authority': authority.descriptor, 'feedback_rules': plan.record.data()['feedback_rules'],
            'sources': _sources(), 'production_promotion': 'not_authorized', 'scientific_validated': False}
    return task.identity, FrozenRecord.from_dict(body)


def _files(root):
    _safe(root)
    result = {}
    for path in sorted(root.rglob('*')):
        _safe(path)
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name in _META or name.startswith(_BLOBS+'/'):
            continue
        result[name] = path.read_bytes()
    return result


def _file_payload(root, name, raw, stage, *, write):
    key = _sha(raw); blob = root/_BLOBS/key
    if write:
        blob.parent.mkdir(exist_ok=True)
        if not blob.exists():
            with blob.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    _safe(blob)
    if not blob.is_file() or blob.read_bytes() != raw:
        raise ContractError('operation output lacks its exact original byte snapshot')
    return {'stage': stage, 'file': name, 'blob': _BLOBS+'/'+key, 'sha256': key, 'bytes': len(raw)}


def _source(kind, payload, sources):
    if kind == 'operation_file':
        name = payload['file']
        if name.startswith('deployment.json'):
            return sources['deployment.py']
        if name == 'shadow.sqlite':
            return sources['modules/improvement.py']
    return sources['train_operations.py']


def _spec(kind, payload, parents, *, status='produced', sources=None):
    unknown = kind == 'operation_file' and payload['file'] not in _KNOWN
    sources = sources if sources is not None else _sources()
    refs = FrozenRecord.from_dict(sources)
    return {'kind': kind, 'module': None if unknown else 'M9', 'payload': payload,
            'parents': parents, 'status': status, 'coverage': 'uncovered' if unknown else 'covered',
            'producer_source': _source(kind, payload, sources), 'optimizer_visible': False,
            'config_refs': [{'kind': 'operation_host_sources', 'digest': refs.content_hash, 'canonical': refs.data()}],
            'cost': {'known': False, 'units': None}}


def _status(outcome):
    return {'operation_failed': 'failed', 'blocked': 'blocked', 'rejected': 'rejected'}.get(outcome['status'], 'produced')


class OperationArtifacts:
    """Journal proxy records actual writes before later operation effects happen."""
    def __init__(self, root, plan, cell, parent, candidate, histories, authority):
        from research_loop.modular.metaprogram_training import _Journal
        self.root = _safe(root)
        identity, inputs = _inputs(plan, cell, parent, candidate, histories, authority)
        self.inputs = inputs; self.last = None; self.sources = inputs.data()['sources']
        self.catalogue = ArtifactCatalogue(root/_CATALOGUE, identity=identity,
            run_id=str(uuid4()), experiment_id=plan.record.data()['experiment_id'],
            lock_digest=inputs.content_hash, producer_source=self.sources['train_operations.py'])
        self.journal = _Journal(root/'operations.jsonl')
        self.record('operation_inputs', inputs.data())

    def record(self, kind, payload, *, status='produced'):
        record = self.catalogue.append(**_spec(kind, payload, [self.last] if self.last else [], status=status, sources=self.sources))
        self.last = record.content_hash
        return record

    def append(self, stage, data):
        self.journal.append(stage, data)
        self.record('operation_event', self.journal.rows[-1].data())

    def checkpoint(self, stage):
        files = _files(self.root)
        descriptors = []
        for name, raw in files.items():
            payload = _file_payload(self.root, name, raw, stage, write=True)
            descriptors.append(self.record('operation_file', payload).content_hash)
        self.record('operation_checkpoint', {'stage': stage, 'files': descriptors})

    def close(self, outcome):
        from research_loop.modular.metaprogram_training import _exclusive
        self.checkpoint('terminal')
        self.record('operation_outcome', outcome, status=_status(outcome))
        seal = self.catalogue.seal()
        closure = FrozenRecord.from_dict({'schema': 'train-operation-artifact-closure-v1',
            'inputs_digest': self.inputs.content_hash, 'outcome_digest': FrozenRecord.from_dict(outcome).content_hash,
            'catalogue_seal': seal.data(), 'scientific_validated': False})
        _exclusive(self.root/_CLOSURE, closure)
        return {'file': _CLOSURE, 'sha256': _sha((self.root/_CLOSURE).read_bytes()),
                'catalogue_seal': seal.data()}


def _match(record, spec):
    body = record.data(); payload = FrozenRecord.from_dict(spec['payload'])
    expected = {**spec, 'schema': 'artifact-descriptor-v2', 'identity': body['identity'],
                'binding': body['binding'], 'control_sources': [], 'checks': [], 'scientific_validated': False,
                'payload': {'digest': payload.content_hash, 'bytes': len(payload.encoded.encode('utf-8')),
                            'encoding': 'canonical_json', 'canonical': payload.data()}}
    if record != FrozenRecord.from_dict(expected):
        raise ContractError('operation artifact differs from actual host inputs, sources or sequence')


def _db(raw, *, shadow):
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(raw); db.execute('PRAGMA query_only=ON')
        if shadow:
            return {'state': [list(row) for row in db.execute('SELECT slot,active_digest FROM state ORDER BY slot')],
                    'used': [row[0] for row in db.execute('SELECT id FROM used_receipts ORDER BY id')],
                    'packages': [list(row) for row in db.execute('SELECT digest,record FROM packages ORDER BY digest')]}
        return {'state': [row[0] for row in db.execute('SELECT active FROM state')],
                'used': [row[0] for row in db.execute('SELECT receipt FROM used ORDER BY receipt')]}
    except sqlite3.Error as exc:
        raise ContractError('operation database snapshot cannot be read independently') from exc
    finally:
        db.close()


def _check_state(files, stage, inputs, authority):
    """Check intermediate state from retained bytes, without constructing a host."""
    body = inputs.data(); experiment = body['experiment']; variant = body['cell']['variant']
    parent = CandidatePackage(FrozenRecord.from_dict(body['parent']))
    candidate = CandidatePackage(FrozenRecord.from_dict(body['candidate']))
    if experiment == 'Q6.1' and variant == 'self_activate':
        required = {'operations.jsonl', 'shadow.sqlite', 'deployment.json', 'deployment.json.sha256'}
        if set(files) & _KNOWN != required:
            raise ContractError('self-activation snapshot contains missing or unexpected runtime outputs')
        expected = {'state': [[1, parent.digest]], 'used': [], 'packages': [[parent.digest, parent.record.encoded]]}
        if _db(files['shadow.sqlite'], shadow=True) != expected:
            raise ContractError('rejected self-activation changed the actual runtime state')
        deployed = parent
    elif experiment == 'Q6.6':
        initial = stage == 'initialized'
        rolled_back = stage == 'rollback' or stage == 'terminal' and variant == 'rollback'
        active = parent if initial or rolled_back else candidate
        token = authority.staging_authorization(candidate, parent, body['subject'])
        used = [] if initial else [token.record.content_hash]
        if rolled_back:
            used.append(authority.staging_authorization(parent, candidate, body['subject']).record.content_hash)
        if _db(files['state.sqlite'], shadow=False) != {'state': [active.digest], 'used': sorted(used)}:
            raise ContractError('staging snapshot differs from the recorded activation transition')
        deployed = parent if stage == 'drift' or stage == 'terminal' and variant == 'drift' else active
        previous = None if initial else candidate if rolled_back or stage == 'drift' or stage == 'terminal' and variant == 'drift' else parent
        required = {'operations.jsonl', 'state.sqlite', 'deployment.json'}
        if not (variant == 'offline' and stage in {'offline','terminal'}):
            required.add('deployment.json.sha256')
        if previous is not None:
            required.update({'deployment.json.previous', 'deployment.json.previous.sha256'})
        if set(files) & _KNOWN != required:
            raise ContractError('staging snapshot contains missing or unexpected runtime outputs')
        if previous is not None:
            _check_deployment(files, 'deployment.json.previous', previous)
    else:
        if any(name in _KNOWN and name != 'operations.jsonl' for name in files):
            raise ContractError('operation without a runtime invented a state output')
        return
    offline = experiment == 'Q6.6' and variant == 'offline' and stage in {'offline', 'terminal'}
    _check_deployment(files, 'deployment.json', deployed, offline=offline)


def _check_deployment(files, name, package, *, offline=False):
    # Pure serialization reference: never instantiate FileDeploymentPort on read.
    raw = files[name]
    expected = FrozenRecord.from_dict({'schema': 'modular-file-deployment-v1',
        'active_digest': package.digest, 'package': package.record.data(),
        'memory_view': package.record.data()['changes'].get('memory', {}),
        'memory_digest': package.memory_digest}).encoded.encode('utf-8')
    if raw != expected:
        raise ContractError('deployment snapshot does not bind its actual package and memory')
    if offline:
        if name+'.sha256' in files:
            raise ContractError('offline checkpoint retained a usable acknowledgement')
    elif files.get(name+'.sha256', b'').decode('ascii').strip() != _sha(raw):
        raise ContractError('deployment snapshot lacks its matching acknowledgement')


def verify_operation_artifacts(root, *, plan, cell, parent, candidate, histories, authority, outcome, binding):
    """Consumer gate: original journal, snapshots, closure and semantic transitions."""
    from research_loop.modular.metaprogram_training import _phase_rows, _read_record
    root = _safe(root)
    identity, inputs = _inputs(plan, cell, parent, candidate, histories, authority)
    closure = _read_record(_safe(root/_CLOSURE))
    path = _safe(root/_CATALOGUE)
    if not path.is_file() or not _safe(path.with_name(path.name+'.seal.json')).is_file():
        raise ContractError('operation audit is missing its original sealed journal')
    try:
        original_binding = FrozenRecord(path.read_text(encoding='utf-8').splitlines()[0]).data()['descriptor']['binding']
        run_id = original_binding['run_id']
        if str(UUID(run_id, version=4)) != run_id:
            raise ValueError('operation attempt identifier is not a UUID4')
    except (IndexError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ContractError('operation lacks its original unique attempt identifier') from exc
    cat = ArtifactCatalogue(path, identity=identity, run_id=run_id,
        experiment_id=plan.record.data()['experiment_id'], lock_digest=inputs.content_hash)
    seal = FrozenRecord.from_dict(closure.data()['catalogue_seal']); cat.verify(seal)
    if (closure != FrozenRecord.from_dict({'schema': 'train-operation-artifact-closure-v1', 'inputs_digest': inputs.content_hash,
            'outcome_digest': FrozenRecord.from_dict(outcome).content_hash, 'catalogue_seal': seal.data(), 'scientific_validated': False}
            ) or binding != {'file': _CLOSURE, 'sha256': _sha((root/_CLOSURE).read_bytes()), 'catalogue_seal': seal.data()}):
        raise ContractError('operation receipt does not bind its original artifact closure')
    records = cat.records(); events = []; checkpoints = []; pending = []; last = None; blobs = set()
    rows = _phase_rows(root/'operations.jsonl'); terminal = None; actual_files = _files(root)
    for index, record in enumerate(records):
        d = record.data(); kind = d['kind']; value = d['payload']['canonical']
        status = 'produced'
        if index == 0:
            if kind != 'operation_inputs' or value != inputs.data():
                raise ContractError('operation catalogue lacks its actual original inputs')
        elif kind == 'operation_event':
            if pending or len(events) >= len(rows) or value != rows[len(events)]:
                raise ContractError('operation event differs from original operation journal')
            events.append(value)
        elif kind == 'operation_file':
            if (type(value) is not dict or set(value) != {'stage','file','blob','sha256','bytes'}
                    or type(value['bytes']) is not int or value['bytes'] < 0):
                raise ContractError('operation file descriptor schema drift')
            name = value['file']
            if (type(name) is not str or name not in actual_files and value['stage'] == 'terminal'
                    or Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name or ':' in name):
                raise ContractError('operation file is outside its declared output directory')
            blob = value['blob']; key = value['sha256']
            if type(key) is not str or len(key) != 64 or any(c not in '0123456789abcdef' for c in key) or blob != _BLOBS+'/'+key:
                raise ContractError('operation blob address drift')
            raw = _safe(root/blob).read_bytes(); blobs.add(blob)
            if _file_payload(root, name, raw, value['stage'], write=False) != value:
                raise ContractError('operation blob bytes differ from original output')
            pending.append((record, raw))
        elif kind == 'operation_checkpoint':
            if value != {'stage': value['stage'], 'files': [r.content_hash for r,_ in pending]}:
                raise ContractError('operation checkpoint omitted an output descriptor')
            files = {r.data()['payload']['canonical']['file']: raw for r,raw in pending}
            names = [r.data()['payload']['canonical']['file'] for r,_ in pending]
            if (names != sorted(set(names)) or any(r.data()['payload']['canonical']['stage'] != value['stage'] for r,_ in pending)
                    or files.get('operations.jsonl') != b''.join((FrozenRecord.from_dict(e).encoded+'\n').encode() for e in events)):
                raise ContractError('operation checkpoint does not bind the actual journal prefix')
            if outcome['status'] != 'operation_failed' or value['stage'] != 'terminal':
                _check_state(files, value['stage'], inputs, authority)
            if value['stage'] == 'terminal':
                terminal = files
            checkpoints.append(value['stage']); pending = []
        elif kind == 'operation_outcome':
            status = _status(outcome)
            if pending or index != len(records)-1 or value != outcome or terminal is None:
                raise ContractError('operation audit lacks its unique original terminal outcome')
        else:
            raise ContractError('unexpected operation artifact entry')
        _match(record, _spec(kind, value, [last] if last else [], status=status, sources=inputs.data()['sources']))
        last = record.content_hash
    expected = ['terminal']
    if plan.record.data()['experiment_id'] == 'Q6.6':
        expected = ['initialized', 'promote']+([] if cell['variant'] == 'promote' else [cell['variant']])+['terminal']
    elif plan.record.data()['experiment_id'] == 'Q6.1' and cell['variant'] == 'self_activate':
        expected = ['initialized', 'terminal']
    if outcome['status'] == 'operation_failed':
        valid = checkpoints[-1:] == ['terminal'] and checkpoints[:-1] == expected[:len(checkpoints)-1]
    else:
        valid = checkpoints == expected
    entries = list((root/_BLOBS).iterdir())
    if any(not _safe(p).is_file() for p in entries):
        raise ContractError('operation byte snapshot store must contain only flat regular files')
    if (not valid or events != rows or pending or terminal != _files(root)
            or not records or records[-1].data()['kind'] != 'operation_outcome'
            or blobs != {p.relative_to(root).as_posix() for p in entries}):
        raise ContractError('operation audit omitted a stage, original output or terminal record')
    return FrozenRecord.from_dict({'schema': 'train-operation-artifact-verification-v1',
        'descriptors': len(records), 'checkpoints': checkpoints, 'status': outcome['status'],
        'storage_verified': True, 'operation_validated': outcome['status'] != 'operation_failed',
        'engineering_verified': outcome['status'] != 'operation_failed',
        'scientific_validated': False, 'production_promotion': 'not_authorized'})
