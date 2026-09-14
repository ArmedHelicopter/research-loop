"""Transactional artifacts for a whole TRAIN-derived deployment configuration.

The journal is local evidence, not a new acceptance authority. An independently
retained checkpoint is required to detect replacement of the whole database.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
import sqlite3
import uuid

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.panel_receipts import verify_signed
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
ZERO = '0' * 64
TABLES = ('bundles', 'components', 'active', 'used_grants', 'consumed_acceptances')


def configuration_subject(bundle):
    from research_loop.modular.artifact_subjects import JointBundleSubject
    subject = JointBundleSubject(bundle)
    identities = sorted((i.data() for i in subject.train_identities), key=lambda v: R(v).encoded)
    return {'kind': 'joint_configuration', 'bundle_digest': subject.digest,
            'component_digests': subject.component_digests, 'training_identities': identities}


def _state(db):
    return {table: [list(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY 1,2').fetchall()]
            for table in TABLES}


def _bundle(encoded):
    from research_loop.modular.joint_deployment import JointDeploymentBundle
    bundle = JointDeploymentBundle(FrozenRecord(encoded))
    configuration_subject(bundle)
    return bundle


def _validate_state(state, acceptance_keys, rollback_keys):
    if type(state) is not dict or set(state) != set(TABLES):
        raise ContractError('deployment artifact state shape differs')
    bundles = {}
    for key, encoded in state['bundles']:
        bundle = _bundle(encoded)
        if key != bundle.digest or key in bundles:
            raise ContractError('deployment artifact bundle identity differs')
        bundles[key] = bundle
    expected = sorted([key, name, component.record.encoded]
                      for key, bundle in bundles.items() for name, component in bundle.components().items())
    if state['components'] != expected:
        raise ContractError('deployment artifact component rows differ')
    if state['active'] and (len(state['active']) != 1 or state['active'][0][0] != 1
                            or state['active'][0][1] not in bundles):
        raise ContractError('deployment artifact active pointer differs')
    grants = {}
    for key, encoded in state['used_grants']:
        grant = FrozenRecord(encoded)
        schema = grant.data().get('body', {}).get('schema')
        keys = acceptance_keys if schema == 'c5-joint-deployment-grant-v1' else rollback_keys
        if schema not in {'c5-joint-deployment-grant-v1', 'c5-joint-rollback-grant-v1'}:
            raise ContractError('deployment artifact grant schema differs')
        body = verify_signed(grant, keys, schema=schema)
        if key != grant.content_hash or key in grants or body['target_bundle_digest'] not in bundles:
            raise ContractError('deployment artifact grant identity differs')
        grants[key] = body
    expected_acceptances = sorted([body['acceptance_digest'], key] for key, body in grants.items()
                                  if body['schema'] == 'c5-joint-deployment-grant-v1')
    if (state['consumed_acceptances'] != expected_acceptances
            or len({row[0] for row in expected_acceptances}) != len(expected_acceptances)):
        raise ContractError('deployment artifact acceptance consumption differs')
    return bundles


def _transition(state, request, result, acceptance_keys, rollback_keys):
    """Reconstruct a committed transition; never mutate the original database."""
    from research_loop.modular.joint_deployment import validate_joint_activation, validate_joint_rollback
    before = deepcopy(state)
    bundles = {key: _bundle(encoded) for key, encoded in state['bundles']}
    active = bundles[state['active'][0][1]] if state['active'] else None
    operation = request['operation']
    if operation == 'task':
        pinned = _bundle(request['bundle'])
        identity = DataIdentity.parse(request['identity'])
        if (pinned.digest not in bundles or type(result) is not dict
                or set(result) != {'schema', 'identity', 'snapshot', 'result'}
                or result['schema'] != 'joint-task-snapshot-receipt-v1'
                or result['identity'] != identity.data() or result['snapshot'] != pinned.acknowledgement().data()):
            raise ContractError('deployment task artifact differs from its pinned configuration')
        return before
    target = _bundle(request['bundle'])
    if operation == 'bootstrap':
        if active is not None or state['bundles'] or state['used_grants']:
            raise ContractError('deployment bootstrap cannot replace existing state')
    else:
        grant = FrozenRecord(request['grant'])
        if grant.content_hash in dict(state['used_grants']):
            raise ContractError('deployment artifact grant was already consumed')
        if operation == 'activate':
            body = verify_signed(grant, acceptance_keys, schema='c5-joint-deployment-grant-v1')
            validate_joint_activation(body, active, target, set(dict(state['consumed_acceptances'])))
            before['consumed_acceptances'].append([body['acceptance_digest'], grant.content_hash])
        elif operation == 'rollback':
            body = verify_signed(grant, rollback_keys, schema='c5-joint-rollback-grant-v1')
            validate_joint_rollback(body, active)
            if target.digest != active.parent_digest or target.digest not in bundles:
                raise ContractError('deployment artifact rollback target differs')
        else:
            raise ContractError('deployment artifact operation differs')
        before['used_grants'].append([grant.content_hash, grant.encoded])
    if result != target.acknowledgement().data():
        raise ContractError('deployment acknowledgement artifact differs')
    if target.digest not in bundles:
        before['bundles'].append([target.digest, target.record.encoded])
        before['components'].extend([target.digest, name, c.record.encoded] for name, c in target.components().items())
    before['active'] = [[1, target.digest]]
    return {name: sorted(rows) for name, rows in before.items()}


def _request(request, domain):
    operation = request.get('operation')
    fields = {'operation', 'bundle', 'subject', 'grant', 'identity', 'producer'}
    if set(request) != fields or operation not in {'bootstrap', 'activate', 'rollback', 'task'}:
        raise ContractError('deployment artifact request shape differs')
    bundle = _bundle(request['bundle'])
    if request['subject'] != configuration_subject(bundle):
        raise ContractError('deployment configuration subject differs')
    if operation == 'task':
        identity = DataIdentity.parse(request['identity'])
        if identity.domain != domain or request['grant'] is not None:
            raise ContractError('deployment task domain differs from its artifact store')
    elif request['identity'] is not None:
        raise ContractError('deployment configurations are not single-task evidence')
    if operation in {'activate', 'rollback'}:
        FrozenRecord(request['grant'])  # Reservation captures a claim, not approval.
    elif request['grant'] is not None:
        raise ContractError('deployment artifact has an unexpected grant')
    producer = request['producer']
    if (set(producer) != {'name', 'source'} or type(producer['name']) is not str
            or not producer['name']):
        raise ContractError('deployment artifact producer differs')
    return bundle


def _source(source, resolver):
    if source is None:
        return
    if resolver is not None:
        resolver.verify_snapshot(source)
    elif source_snapshot(Path(source['path'])) != source:
        raise ContractError('deployment artifact producer source drift')


def _verify(db, *, domain, acceptance_keys, rollback_keys, expected=None, source_resolver=None, check_sources=True):
    # Check the domain header before selecting any event or task-result records.
    row = db.execute('SELECT record FROM deployment_audit_meta WHERE id=1').fetchone()
    meta = FrozenRecord(row[0]).data() if row else {}
    if (set(meta) != {'schema', 'store_id', 'domain', 'producer_source'}
            or meta['schema'] != 'joint-deployment-artifacts-v1' or meta['domain'] != domain
            or domain not in {'train', 'validation'}):
        raise ContractError('deployment artifact store domain or schema differs')
    if expected is not None:
        if type(expected) is not FrozenRecord:
            raise ContractError('deployment checkpoint must be an exact frozen record')
        anchor = expected.data()
        if (set(anchor) != {'schema', 'store_id', 'domain', 'count', 'head', 'state_digest'}
                or anchor['schema'] != 'joint-deployment-artifact-checkpoint-v1'
                or type(anchor['count']) is not int or anchor['count'] < 1
                or anchor['store_id'] != meta['store_id'] or anchor['domain'] != domain):
            raise ContractError('deployment checkpoint belongs to another store or domain')
    if check_sources:
        _source(meta['producer_source'], source_resolver)
    events = []; attempts = {}; previous = ZERO; state = None; anchored = expected is None
    for sequence, row_digest, encoded in db.execute('SELECT sequence,digest,record FROM deployment_audit_events ORDER BY sequence'):
        event = FrozenRecord(encoded); body = event.data()
        fields = {'schema', 'store_id', 'sequence', 'previous', 'kind', 'attempt_id', 'payload', 'state',
                  'producer_source', 'cost', 'scientific_validated'}
        if (set(body) != fields or body['schema'] != 'joint-deployment-artifact-event-v1'
                or body['store_id'] != meta['store_id'] or sequence != len(events) + 1
                or body['sequence'] != sequence or body['previous'] != previous or event.content_hash != row_digest
                or body['cost'] != {'known': False, 'units': None} or body['scientific_validated'] is not False):
            raise ContractError('deployment artifact journal chain or flags differ')
        if check_sources:
            _source(body['producer_source'], source_resolver)
        kind, payload, attempt_id = body['kind'], body['payload'], body['attempt_id']
        _validate_state(body['state'], acceptance_keys, rollback_keys)
        if kind == 'baseline':
            if events or attempt_id is not None or payload != {'history_complete': not bool(body['state']['bundles'])}:
                raise ContractError('deployment artifact baseline differs')
        elif kind == 'started':
            if state != body['state'] or type(attempt_id) is not str or attempt_id in attempts:
                raise ContractError('deployment artifact attempt identity differs')
            bundle = _request(payload, domain)
            if payload['operation'] == 'task' and state['active'] != [[1, bundle.digest]]:
                raise ContractError('deployment task was not pinned before dispatch')
            if check_sources:
                _source(payload['producer']['source'], source_resolver)
            attempts[attempt_id] = {'request': payload, 'terminal': False}
        elif kind in {'committed', 'failed'}:
            attempt = attempts.get(attempt_id)
            if attempt is None or attempt['terminal'] or set(payload) != {'result', 'error', 'staged'}:
                raise ContractError('deployment artifact terminal has no unique attempt')
            if type(payload['staged']) is not list:
                raise ContractError('deployment staged observations differ')
            target = _bundle(attempt['request']['bundle'])
            seen = set()
            for observation in payload['staged']:
                if (set(observation) != {'module', 'raw', 'sha256', 'bytes', 'producer'} or observation['module'] in seen
                        or observation['module'] not in target.components()):
                    raise ContractError('deployment staged observation identity differs')
                producer = observation['producer']
                if set(producer) != {'name', 'source'} or type(producer['name']) is not str or not producer['name']:
                    raise ContractError('deployment component producer differs')
                if check_sources:
                    _source(producer['source'], source_resolver)
                seen.add(observation['module']); raw = observation['raw']
                if raw is not None and type(raw) is not str:
                    raise ContractError('deployment staged raw record differs')
                if observation['sha256'] != (hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None):
                    raise ContractError('deployment staged bytes drift')
                if observation['bytes'] != (len(raw.encode()) if raw is not None else None):
                    raise ContractError('deployment staged byte count differs')
                if kind == 'committed' and raw != target.components()[observation['module']].record.encoded:
                    raise ContractError('deployment committed component differs from observed output')
            if kind == 'committed':
                if payload['error'] is not None or _transition(state, attempt['request'], payload['result'], acceptance_keys, rollback_keys) != body['state']:
                    raise ContractError('deployment committed artifact transition differs')
                new_bundle = target.digest not in dict(state['bundles'])
                expected_staged = set(target.components()) if new_bundle and attempt['request']['operation'] in {'bootstrap', 'activate'} else set()
                if seen != expected_staged:
                    raise ContractError('deployment committed component inventory differs')
            elif state != body['state'] or type(payload['error']) is not str or not payload['error']:
                raise ContractError('deployment failed attempt altered committed state')
            attempt['terminal'] = True
        else:
            raise ContractError('deployment artifact event kind differs')
        state = body['state']; previous = row_digest; events.append(event)
        if expected is not None and sequence == anchor.get('count'):
            anchored = (row_digest == anchor.get('head') and R(state).content_hash == anchor.get('state_digest'))
    head = db.execute('SELECT count,head FROM deployment_audit_head WHERE id=1').fetchone()
    if not events or head != (len(events), previous) or not anchored or state != _state(db):
        raise ContractError('deployment artifact tail, checkpoint or actual SQL state differs')
    checkpoint = R({'schema': 'joint-deployment-artifact-checkpoint-v1', 'store_id': meta['store_id'],
                    'domain': domain, 'count': len(events), 'head': previous, 'state_digest': R(state).content_hash})
    return checkpoint, tuple(events), tuple(k for k, v in attempts.items() if not v['terminal'])


class JointDeploymentArtifacts:
    def __init__(self, store, domain, expected=None):
        if domain not in {'train', 'validation'}:
            raise ContractError('deployment artifact store requires an exact domain')
        self.store, self.db, self.domain, self.anchor = store, store._db, domain, expected
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS deployment_audit_meta (id INTEGER PRIMARY KEY CHECK(id=1), record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deployment_audit_events (sequence INTEGER PRIMARY KEY, digest TEXT NOT NULL UNIQUE, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deployment_audit_head (id INTEGER PRIMARY KEY CHECK(id=1), count INTEGER NOT NULL, head TEXT NOT NULL);
        ''')
        with store._transaction():
            row = self.db.execute('SELECT record FROM deployment_audit_meta WHERE id=1').fetchone()
            if row is None:
                if expected is not None:
                    raise ContractError('cannot initialize a missing independently checkpointed journal')
                self.meta = R({'schema': 'joint-deployment-artifacts-v1', 'store_id': uuid.uuid4().hex,
                               'domain': domain, 'producer_source': source_snapshot(Path(__file__))}).data()
                self.db.execute('INSERT INTO deployment_audit_meta VALUES(1,?)', (R(self.meta).encoded,))
                self.db.execute('INSERT INTO deployment_audit_head VALUES(1,0,?)', (ZERO,))
                self._append('baseline', None, {'history_complete': not bool(_state(self.db)['bundles'])})
            else:
                self.meta = FrozenRecord(row[0]).data()
            self.verify()

    def verify(self, *, check_sources=True):
        result = _verify(self.db, domain=self.domain, acceptance_keys=self.store._acceptance_keys,
                         rollback_keys=self.store._rollback_keys, expected=self.anchor, check_sources=check_sources)
        return result

    def _append(self, kind, attempt_id, payload):
        count, previous = self.db.execute('SELECT count,head FROM deployment_audit_head WHERE id=1').fetchone()
        event = R({'schema': 'joint-deployment-artifact-event-v1', 'store_id': self.meta['store_id'],
                   'sequence': count + 1, 'previous': previous, 'kind': kind, 'attempt_id': attempt_id,
                   'payload': payload, 'state': _state(self.db), 'producer_source': source_snapshot(Path(__file__)),
                   'cost': {'known': False, 'units': None}, 'scientific_validated': False})
        self.db.execute('INSERT INTO deployment_audit_events VALUES(?,?,?)', (count + 1, event.content_hash, event.encoded))
        self.db.execute('UPDATE deployment_audit_head SET count=?,head=? WHERE id=1', (count + 1, event.content_hash))
        return event

    def begin(self, operation, bundle, *, grant=None, identity=None, producer=None):
        # Caller owns the transaction, including the task's snapshot selection.
        self.verify()
        source = inspect.getsourcefile(producer) if inspect.isfunction(producer) or inspect.ismethod(producer) else None
        request = {'operation': operation, 'bundle': bundle.record.encoded, 'subject': configuration_subject(bundle),
                   'grant': grant.encoded if type(grant) is FrozenRecord else None,
                   'identity': identity.data() if identity is not None else None,
                   'producer': {'name': getattr(producer, '__qualname__', type(producer).__qualname__),
                                'source': source_snapshot(Path(source)) if source else None}}
        _request(request, self.domain)
        attempt = {'id': uuid.uuid4().hex, 'request': request, 'staged': [], 'result': None}
        self._append('started', attempt['id'], request)
        attempt['checkpoint'] = self.verify()[0]
        return attempt

    def observe(self, attempt, bundle, module, producer):
        row = self.db.execute('SELECT record FROM components WHERE bundle=? AND module=?', (bundle.digest, module)).fetchone()
        raw = row[0] if row else None
        source = inspect.getsourcefile(producer) if inspect.isfunction(producer) or inspect.ismethod(producer) else None
        attempt['staged'].append({'module': module, 'raw': raw,
                                  'sha256': hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None,
                                  'bytes': len(raw.encode()) if raw is not None else None,
                                  'producer': {'name': getattr(producer, '__qualname__', type(producer).__qualname__),
                                               'source': source_snapshot(Path(source)) if source else None}})

    def finish(self, attempt, result):
        attempt['result'] = result.data()
        self._append('committed', attempt['id'], {'result': result.data(), 'error': None, 'staged': attempt['staged']})
        return self.verify()[0]

    def fail(self, attempt, error):
        # Failed SQL work has already rolled back. Preserve observed uncommitted
        # bytes, without storing an exception message that might contain secrets.
        with self.store._transaction():
            self.verify(check_sources=False)
            self._append('failed', attempt['id'], {'result': attempt['result'],
                         'error': type(error).__name__, 'staged': attempt['staged']})
            anchor = self.verify(check_sources=False)[0]
        return anchor


def verify_joint_deployment_artifacts(path, *, domain, checkpoint, acceptance_keys, rollback_keys, source_resolver=None):
    """Independent read-only artifact/state replay against a caller-pinned checkpoint."""
    if type(checkpoint) is not FrozenRecord:
        raise ContractError('independent deployment artifact checkpoint required')
    if source_resolver is not None and type(source_resolver) is not ArchivedSourceResolver:
        raise ContractError('deployment source resolver must be exact')
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        anchor, events, pending = _verify(db, domain=domain, expected=checkpoint,
            acceptance_keys=acceptance_keys, rollback_keys=rollback_keys, source_resolver=source_resolver)
        return R({'schema': 'joint-deployment-artifact-verification-v1', 'checkpoint': anchor.data(),
                  'events': [e.data() for e in events], 'pending_attempts': list(pending),
                  'optimizer_visible': domain == 'train', 'scientific_validated': False})
    finally:
        db.close()
