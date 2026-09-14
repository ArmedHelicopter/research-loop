"""Atomic C5 component snapshots behind an independently signed deployment grant.

This store does not evaluate TRAIN or validation data and cannot issue grants.
It consumes an upstream C5 acceptance authority's decision. Source manifests
identify separate component builds; they do not certify those builds' efficacy.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Mapping

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.panel_receipts import verify_signed
from research_loop.ontology import ContractError


def _hash(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ContractError(name + ' must be a sha256 digest')
    return value


def _path(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or PurePosixPath(value).is_absolute() or any(p in {'', '.', '..'} for p in value.split('/'))):
        raise ContractError('component source path must be a portable relative file')
    return value


def validate_joint_activation(body, active, bundle, consumed_acceptances):
    fields = {'schema','authority','stage','allocation_stage','target_bundle_digest','expected_active_digest',
              'selection_digest','panel_digest','acceptance_digest','decision'}
    if set(body) != fields or body['stage'] != 'C5' or body['allocation_stage'] != 'V_final' or body['decision'] != 'approved':
        raise ContractError('joint activation requires the independent C5 approval')
    for name in ('selection_digest','panel_digest','acceptance_digest'): _hash(body[name], name)
    if body['acceptance_digest'] in consumed_acceptances:
        raise ContractError('independent acceptance receipt was already consumed')
    if (active is None or body['target_bundle_digest'] != bundle.digest
            or body['expected_active_digest'] != active.digest or bundle.parent_digest != active.digest):
        raise ContractError('joint approval is stale or targets a different bundle')
    if any(bundle.record.data()[name] != active.record.data()[name] for name in ('baseline_digest', 'p0_digest')):
        raise ContractError('joint deployment cannot replace the frozen baseline or P0 contract')


def validate_joint_rollback(body, active):
    if (set(body) != {'schema','authority','expected_active_digest','target_bundle_digest','reason'}
            or not isinstance(body['reason'], str) or not body['reason'].strip()):
        raise ContractError('joint rollback requires an exact independent authorization')
    if active is None or body['expected_active_digest'] != active.digest or body['target_bundle_digest'] != active.parent_digest:
        raise ContractError('joint rollback must restore the exact prior bundle')


@dataclass(frozen=True)
class JointComponentVersion:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError('component requires an exact frozen record')
        b = self.record.data()
        if (set(b) != {'schema', 'module_id', 'source_files', 'config', 'state', 'training_manifest'}
                or b['schema'] != 'joint-component-version-v1'
                or b['module_id'] not in {f'M{i}' for i in range(1, 10)}
                or not isinstance(b['source_files'], dict) or not b['source_files']
                or not isinstance(b['config'], dict) or not isinstance(b['state'], dict)):
            raise ContractError('invalid independently versioned component')
        for name, value in b['source_files'].items():
            _path(name); _hash(value, 'component source')
        TrainingManifest(FrozenRecord.from_dict(b['training_manifest']))

    @classmethod
    def capture(cls, module_id, *, source_root: Path, source_files, config: FrozenRecord,
                state: FrozenRecord, training_manifest: TrainingManifest):
        names = tuple(source_files)
        if not names or len(set(names)) != len(names):
            raise ContractError('component build needs unique source files')
        root = Path(source_root).resolve(strict=True)
        hashes = {}
        for name in names:
            path = (root / _path(name)).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ContractError('component source escapes its build root')
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if type(config) is not FrozenRecord or type(state) is not FrozenRecord or type(training_manifest) is not TrainingManifest:
            raise ContractError('component payload needs frozen config, state and TRAIN provenance')
        return cls(FrozenRecord.from_dict({'schema': 'joint-component-version-v1', 'module_id': module_id,
            'source_files': hashes, 'config': config.data(), 'state': state.data(),
            'training_manifest': training_manifest.record.data()}))

    @property
    def module_id(self): return self.record.data()['module_id']

    @property
    def digest(self): return self.record.content_hash

    def verify_sources(self, root):
        root = Path(root).resolve(strict=True)
        for name, expected in self.record.data()['source_files'].items():
            path = (root / name).resolve(strict=True)
            if (not path.is_relative_to(root) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                raise ContractError('component build source drift')


@dataclass(frozen=True)
class JointDeploymentBundle:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError('joint bundle requires an exact frozen record')
        b = self.record.data()
        if (set(b) != {'schema', 'parent_digest', 'baseline_digest', 'p0_digest', 'resource_schedule', 'components'}
                or b['schema'] != 'joint-deployment-bundle-v1' or not isinstance(b['components'], dict)
                or not isinstance(b['resource_schedule'], dict) or not b['resource_schedule']):
            raise ContractError('invalid complete joint deployment bundle')
        if b['parent_digest'] is not None: _hash(b['parent_digest'], 'joint parent')
        _hash(b['baseline_digest'], 'baseline'); _hash(b['p0_digest'], 'P0')
        components = {k: JointComponentVersion(FrozenRecord.from_dict(v)) for k, v in b['components'].items()}
        if any(k != v.module_id for k, v in components.items()):
            raise ContractError('joint component identity differs from its slot')
        default_compatibility(b['baseline_digest']).arm(tuple(components))
        identities = [i for c in components.values() for i in TrainingManifest(
            FrozenRecord.from_dict(c.record.data()['training_manifest'])).identities()]
        if len({i.split_id for i in identities}) > 1:
            raise ContractError('component builds must share one frozen TRAIN split')

    @classmethod
    def create(cls, *, parent_digest, baseline_digest, p0_digest, resource_schedule: FrozenRecord,
               components: Mapping[str, JointComponentVersion]):
        if type(resource_schedule) is not FrozenRecord or any(type(v) is not JointComponentVersion for v in components.values()):
            raise ContractError('joint bundle requires exact component versions and schedule')
        return cls(FrozenRecord.from_dict({'schema': 'joint-deployment-bundle-v1', 'parent_digest': parent_digest,
            'baseline_digest': baseline_digest, 'p0_digest': p0_digest, 'resource_schedule': resource_schedule.data(),
            'components': {k: v.record.data() for k, v in components.items()}}))

    @property
    def digest(self): return self.record.content_hash

    @property
    def parent_digest(self): return self.record.data()['parent_digest']

    def components(self):
        return {k: JointComponentVersion(FrozenRecord.from_dict(v)) for k, v in self.record.data()['components'].items()}

    def verify_sources(self, roots):
        components = self.components()
        if not set(components) <= set(roots):
            raise ContractError('joint deployment lacks a component build root')
        for name, component in components.items(): component.verify_sources(roots[name])

    def acknowledgement(self):
        return FrozenRecord.from_dict({'schema': 'joint-deployment-ack-v1', 'bundle_digest': self.digest,
            'component_digests': {k: v.digest for k, v in self.components().items()},
            'state_digests': {k: FrozenRecord.from_dict(v.record.data()['state']).content_hash for k, v in self.components().items()},
            'p0_digest': self.record.data()['p0_digest'],
            'resource_schedule_digest': FrozenRecord.from_dict(self.record.data()['resource_schedule']).content_hash})


class JointDeploymentStore:
    """One SQLite transaction publishes all components and consumes one grant.

    Readers take one immutable snapshot per task. Module code must consume that
    snapshot for the task; fetching components separately is not this contract.
    No external per-component service can be atomically changed by this store.
    """
    def __init__(self, path: Path, *, initial: JointDeploymentBundle, acceptance_keys, rollback_keys, source_roots,
                 task_domain='train', artifact_checkpoint=None):
        if type(initial) is not JointDeploymentBundle:
            raise ContractError('joint store requires a typed bootstrap bundle')
        self._acceptance_keys, self._rollback_keys = dict(acceptance_keys), dict(rollback_keys)
        self._roots = {k: Path(v).resolve() for k, v in source_roots.items()}
        self.task_domain = task_domain
        self._staging_attempt = None
        self.last_operation_receipt = None
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self._db.execute('PRAGMA foreign_keys=ON')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS bundles (digest TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS components (bundle TEXT NOT NULL REFERENCES bundles(digest),
                module TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(bundle,module));
            CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL REFERENCES bundles(digest));
            CREATE TABLE IF NOT EXISTS used_grants (digest TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS consumed_acceptances (digest TEXT PRIMARY KEY,
                grant_digest TEXT NOT NULL UNIQUE REFERENCES used_grants(digest));
        ''')
        try:
            if task_domain not in {'train', 'validation'}:
                raise ContractError('joint task domain must be train or validation')
            if self._db.execute("SELECT 1 FROM sqlite_master WHERE name='deployment_audit_meta'").fetchone():
                row = self._db.execute('SELECT record FROM deployment_audit_meta WHERE id=1').fetchone()
                if row is not None and FrozenRecord(row[0]).data().get('domain') != task_domain:
                    raise ContractError('deployment artifact store domain differs')
            with self._transaction():
                # Preserve one-use acceptance when reconstructing this derived
                # table in an earlier store; no past execution is invented.
                for grant_digest, encoded in self._db.execute('SELECT digest,record FROM used_grants').fetchall():
                    grant = FrozenRecord(encoded)
                    if grant.content_hash != grant_digest: raise ContractError('stored deployment grant drift')
                    if grant.data().get('body', {}).get('schema') == 'c5-joint-deployment-grant-v1':
                        body = verify_signed(grant, self._acceptance_keys, schema='c5-joint-deployment-grant-v1')
                        self._consume_acceptance(_hash(body['acceptance_digest'], 'acceptance receipt'), grant_digest)
            from research_loop.modular.joint_deployment_artifacts import JointDeploymentArtifacts
            self._artifacts = JointDeploymentArtifacts(self, task_domain, artifact_checkpoint)
            if self._db.execute('SELECT digest FROM active WHERE id=1').fetchone() is None:
                with self._transaction():
                    attempt = self._artifacts.begin('bootstrap', initial, producer=self._stage_bundle)
                self._artifacts.anchor = attempt['checkpoint']
                try:
                    with self._transaction():
                        self._staging_attempt = attempt
                        initial.verify_sources(self._roots)
                        self._stage_bundle(initial)
                        self._db.execute('INSERT INTO active VALUES(1,?)', (initial.digest,))
                        anchor = self._artifacts.finish(attempt, initial.acknowledgement())
                    self._remember(anchor)
                except BaseException as error:
                    self._failed(attempt, error)
                    raise
                finally:
                    self._staging_attempt = None
            self.active()
        except BaseException:
            self._db.close()
            raise

    def _remember(self, anchor):
        self._artifacts.anchor = anchor
        self.last_operation_receipt = anchor

    def _failed(self, attempt, error):
        try:
            self._remember(self._artifacts.fail(attempt, error))
        except BaseException as audit_error:
            # The durable started record remains incomplete. Never replace the
            # original failure with a made-up completed audit record.
            error.add_note('Deployment failure audit remains incomplete: ' + type(audit_error).__name__)

    def artifact_checkpoint(self):
        with self._transaction():
            anchor, _, _ = self._artifacts.verify()
        self._artifacts.anchor = anchor
        return anchor

    @contextmanager
    def _transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    def _stage_component(self, bundle, name, component):
        self._db.execute('INSERT INTO components VALUES(?,?,?)', (bundle.digest, name, component.record.encoded))

    def _stage_bundle(self, bundle):
        existing = self._db.execute('SELECT record FROM bundles WHERE digest=?', (bundle.digest,)).fetchone()
        if existing is not None:
            if self._read_bundle(bundle.digest) != bundle: raise ContractError('persisted joint bundle drift')
            return
        self._db.execute('INSERT INTO bundles VALUES(?,?)', (bundle.digest, bundle.record.encoded))
        for name, component in bundle.components().items():
            writer = self._stage_component
            try:
                writer(bundle, name, component)
            finally:
                if self._staging_attempt is not None:
                    self._artifacts.observe(self._staging_attempt, bundle, name, writer)

    def _read_bundle(self, digest):
        row = self._db.execute('SELECT record FROM bundles WHERE digest=?', (digest,)).fetchone()
        if row is None: raise ContractError('joint bundle is unavailable')
        bundle = JointDeploymentBundle(FrozenRecord(row[0]))
        components = dict(self._db.execute('SELECT module,record FROM components WHERE bundle=?', (digest,)))
        if bundle.digest != digest or components != {k: v.record.encoded for k, v in bundle.components().items()}:
            raise ContractError('persisted component snapshot drift')
        return bundle

    def _read_active(self):
        return self._read_bundle(self._db.execute('SELECT digest FROM active WHERE id=1').fetchone()[0])

    def active(self):
        # A read transaction pins both pointer and component rows across writers.
        self._db.execute('BEGIN')
        try:
            anchor, _, _ = self._artifacts.verify()
            bundle = self._read_active()
            bundle.verify_sources(self._roots)
            self._artifacts.anchor = anchor
            return bundle
        finally:
            self._db.execute('ROLLBACK')

    def _grant(self, grant, schema, keys):
        if type(grant) is not FrozenRecord: raise ContractError('joint grant requires an exact signed record')
        body = verify_signed(grant, keys, schema=schema)
        if self._db.execute('SELECT 1 FROM used_grants WHERE digest=?', (grant.content_hash,)).fetchone():
            raise ContractError('joint grant was already consumed')
        return body

    def _consume_acceptance(self, acceptance_digest, grant_digest):
        prior = self._db.execute('SELECT grant_digest FROM consumed_acceptances WHERE digest=?', (acceptance_digest,)).fetchone()
        if prior is not None:
            if prior[0] != grant_digest: raise ContractError('independent acceptance receipt was already consumed')
            return  # Idempotent reconstruction of a stored grant on reopen.
        self._db.execute('INSERT INTO consumed_acceptances VALUES(?,?)', (acceptance_digest, grant_digest))

    def activate(self, bundle: JointDeploymentBundle, grant: FrozenRecord):
        if type(bundle) is not JointDeploymentBundle: raise ContractError('joint activation requires an exact bundle')
        if type(grant) is not FrozenRecord: raise ContractError('joint grant requires an exact signed record')
        with self._transaction():
            attempt = self._artifacts.begin('activate', bundle, grant=grant, producer=self.activate)
        self._artifacts.anchor = attempt['checkpoint']
        try:
            with self._transaction():
                self._staging_attempt = attempt
                b = self._grant(grant, 'c5-joint-deployment-grant-v1', self._acceptance_keys)
                active = self._read_active()
                consumed = {r[0] for r in self._db.execute('SELECT digest FROM consumed_acceptances')}
                validate_joint_activation(b, active, bundle, consumed)
                active.verify_sources(self._roots); bundle.verify_sources(self._roots)
                self._stage_bundle(bundle)
                if self._read_bundle(bundle.digest).acknowledgement() != bundle.acknowledgement():
                    raise ContractError('partial joint deployment acknowledgement')
                bundle.verify_sources(self._roots)
                self._db.execute('UPDATE active SET digest=? WHERE id=1', (bundle.digest,))
                self._db.execute('INSERT INTO used_grants VALUES(?,?)', (grant.content_hash, grant.encoded))
                self._consume_acceptance(b['acceptance_digest'], grant.content_hash)
                anchor = self._artifacts.finish(attempt, bundle.acknowledgement())
            self._remember(anchor)
        except BaseException as error:
            self._failed(attempt, error)
            raise
        finally:
            self._staging_attempt = None
        return bundle.acknowledgement()

    def rollback(self, grant):
        if type(grant) is not FrozenRecord: raise ContractError('joint grant requires an exact signed record')
        with self._transaction():
            self._artifacts.verify()
            active = self._read_active()
            proposed = self._read_bundle(active.parent_digest) if active.parent_digest else active
            attempt = self._artifacts.begin('rollback', proposed, grant=grant, producer=self.rollback)
        self._artifacts.anchor = attempt['checkpoint']
        try:
            with self._transaction():
                b = self._grant(grant, 'c5-joint-rollback-grant-v1', self._rollback_keys)
                active = self._read_active()
                validate_joint_rollback(b, active)
                previous = self._read_bundle(active.parent_digest)
                previous.verify_sources(self._roots)
                self._db.execute('UPDATE active SET digest=? WHERE id=1', (previous.digest,))
                self._db.execute('INSERT INTO used_grants VALUES(?,?)', (grant.content_hash, grant.encoded))
                anchor = self._artifacts.finish(attempt, previous.acknowledgement())
            self._remember(anchor)
        except BaseException as error:
            self._failed(attempt, error)
            raise
        return previous.acknowledgement()

    def run_task(self, identity: DataIdentity, executor):
        if type(identity) is not DataIdentity: raise ContractError('joint task needs a typed identity')
        if identity.domain != self.task_domain:
            raise ContractError('joint task domain differs from its artifact store')
        with self._transaction():
            self._artifacts.verify()
            bundle = self._read_active()
            bundle.verify_sources(self._roots)
            attempt = self._artifacts.begin('task', bundle, identity=identity, producer=executor)
        self._artifacts.anchor = attempt['checkpoint']
        try:
            result = executor(identity, bundle)
            receipt = FrozenRecord.from_dict({'schema':'joint-task-snapshot-receipt-v1', 'identity':identity.data(),
                'snapshot':bundle.acknowledgement().data(), 'result':result})
            attempt['result'] = receipt.data()
            with self._transaction():
                bundle.verify_sources(self._roots)
                anchor = self._artifacts.finish(attempt, receipt)
            self._remember(anchor)
            return receipt
        except BaseException as error:
            self._failed(attempt, error)
            raise

    def close(self): self._db.close()
