"""M9 provenance at the durable builder writer, separate from VAL acceptance."""
from __future__ import annotations

import hashlib
from pathlib import Path

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_modules import PROPOSAL_INSTRUCTION, REVISION_INSTRUCTION, select_builder
from research_loop.modular.metaprogram_training import _checked_build, _exclusive
from research_loop.modular.modules.improvement import (
    BuilderRunReceipt, CandidatePackage, FrozenBuilderVersion, RestrictedBuilderPort, TrainingManifest,
)
from research_loop.ontology import ContractError

_RETURNED = 'm9-builder-return.json'
_FILES = ('builder.json', _RETURNED, 'builder-receipt.json', 'candidate.json')
_TERMINAL = 'm9-build-terminal.json'
_KINDS = dict(zip(_FILES, ('m9_builder_file', 'm9_builder_return', 'm9_builder_receipt', 'm9_candidate')))
_SOURCES = {'selection': Path(__file__).with_name('full_loo_modules.py'),
            'builder': Path(__file__).parent / 'modules' / 'improvement.py', 'bridge': Path(__file__)}


def _snapshot(root, name):
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ContractError('M9 original file is missing or is a symlink: ' + name)
    raw = path.read_bytes()
    try:
        record = FrozenRecord(raw.decode('utf-8').removesuffix('\n'))
        value = record.data() if raw == (record.encoded + '\n').encode('utf-8') else None
    except (ContractError, UnicodeError):
        value = None
    return {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'canonical': value}


def _read(root, name):
    value = _snapshot(root, name)['canonical']
    if value is None:
        raise ContractError('M9 original file is not exact canonical JSON: ' + name)
    return FrozenRecord.from_dict(value)


def _invocation(records, response, enabled, catalogue, parent):
    prefix = [r.data()['payload']['canonical'] for r in records if r.data()['kind'] == 'trace_event']
    try:
        trace = [FrozenRecord(line).data() for line in
                 (catalogue.path.parent / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    except OSError as exc:
        raise ContractError('M9 original invocation trace is missing') from exc
    if trace[:len(prefix)] != prefix:
        raise ContractError('M9 invocation catalogue differs from the original trace')
    locks = [r.data()['payload']['canonical']['data'] for r in records
             if r.data()['kind'] == 'trace_event' and r.data()['payload']['canonical']['stage'] == 'objective_lock']
    if (len(locks) != 1 or FrozenRecord.from_dict(locks[0]).content_hash != catalogue.binding['lock_digest']
            or locks[0]['package_digest'] != parent.digest
            or ('M9' in locks[0]['arm']['enabled']) != enabled):
        raise ContractError('M9 parent or activation differs from the actual run lock')
    model = [r for r in records if r.data()['kind'] == 'trace_event'
             and r.data()['payload']['canonical']['stage'] in {'model_request', 'model_response', 'model_failure'}]
    if len(model) < 2:
        raise ContractError('M9 requires an original model invocation in this catalogue')
    request, returned = model[-2:]
    req_event, resp_event = (r.data()['payload']['canonical'] for r in (request, returned))
    if req_event['stage'] != 'model_request' or resp_event['stage'] != 'model_response':
        raise ContractError('M9 invocation has no completed request/response pair')
    req, resp = req_event['data'], resp_event['data']
    body = req['request']
    if (req['request_digest'] != FrozenRecord.from_dict(body).content_hash
            or resp['request_digest'] != req['request_digest'] or resp['response'] != response.data()
            or body['task']['identity'] != catalogue.identity.data()
            or body['lock_digest'] != catalogue.binding['lock_digest']
            or body['slot'] != ('builder_proposal' if enabled else 'ordinary_revision')
            or body['instruction'] != (PROPOSAL_INSTRUCTION if enabled else REVISION_INSTRUCTION)):
        raise ContractError('M9 selected response differs from the actual builder invocation')
    return request, returned


def _inputs(catalogue, builder, parent, response, recipe, fixed_builder):
    if (type(catalogue) is not ArtifactCatalogue or type(builder) is not FrozenBuilderVersion
            or type(parent) is not CandidatePackage or type(response) is not FrozenRecord
            or type(fixed_builder) is not FrozenBuilderVersion or type(recipe) is not dict):
        raise ContractError('M9 requires exact immutable builder inputs')
    catalogue.identity.require_train()
    levels = recipe.get('history_build_levels')
    if type(levels) is not dict:
        raise ContractError('M9 requires frozen recipe activation levels')
    level = levels.get('M9')
    if type(level) is not int or level not in {0, 1}:
        raise ContractError('M9 activation must be the frozen recipe integer level')
    enabled = bool(level)
    manifest = TrainingManifest(FrozenRecord.from_dict(parent.record.data()['training_manifest']))
    if catalogue.identity not in manifest.identities():
        raise ContractError('M9 build subject is outside its frozen TRAIN manifest')
    if select_builder(response, recipe, fixed_builder) != builder:
        raise ContractError('M9 selected builder differs from its proposal or fixed control')
    return enabled, manifest


def _spec(kind, payload, parents, status, source='bridge', units=0):
    return dict(kind=kind, module='M9', payload=payload, parents=parents, status=status,
                producer_source=source_snapshot(_SOURCES[source]), cost={'known': True, 'units': units})


def _selection(builder, response, recipe, fixed_builder, request, returned, enabled):
    return {'schema': 'm9-builder-selection-v1', 'activation': 'applied' if enabled else 'not_applied',
            'builder': builder.record.data(), 'builder_digest': builder.digest,
            'response': response.data(), 'recipe': recipe, 'fixed_builder': fixed_builder.record.data(),
            'request_descriptor': request.content_hash, 'response_descriptor': returned.content_hash}


def begin_builder_artifacts(catalogue, *, root, builder, parent, response, recipe, fixed_builder):
    """Bind the actual invocation before executing; returned bridge owns output files.

    Call execute once, or fail(exc) if an intervening caller operation fails.
    An existing terminal is immutable even when the enclosing stage later fails.
    """
    enabled, manifest = _inputs(catalogue, builder, parent, response, recipe, fixed_builder)
    root = Path(root)
    records = catalogue.records()
    if any(r.data()['kind'].startswith('m9_') for r in records):
        raise ContractError('M9 build already began in this catalogue')
    if any((root / name).exists() for name in (*_FILES, _TERMINAL)):
        raise ContractError('M9 begin must precede all original builder output files')
    request, returned = _invocation(records, response, enabled, catalogue, parent)
    status = 'produced' if enabled else 'not_applied'
    selection = catalogue.append(**_spec('m9_builder_selection',
        _selection(builder, response, recipe, fixed_builder, request, returned, enabled),
        (request.content_hash, returned.content_hash), status, 'selection'))
    subjects = catalogue.append(**_spec('m9_builder_subjects', {
        'parent': parent.record.data(), 'parent_digest': parent.digest,
        'manifest': manifest.record.data(), 'manifest_digest': manifest.content_hash, 'search_cost': 1},
        (selection.content_hash,), status, 'builder'))
    return BuilderArtifactBridge(catalogue, root, builder, parent, manifest, status, subjects)


class BuilderArtifactBridge:
    def __init__(self, catalogue, root, builder, parent, manifest, status, subjects):
        self.catalogue, self.root, self.builder, self.parent = catalogue, root, builder, parent
        self.manifest, self.status, self.subjects = manifest, status, subjects
        self.last, self.files = subjects, {}
        self.phase, self.terminal = 'before_execute', None

    def _observe(self, name):
        snapshot = _snapshot(self.root, name)
        if name in self.files:
            if self.files[name] != snapshot:
                raise ContractError('M9 durable output changed after registration')
            return
        self.last = self.catalogue.append(**_spec(_KINDS[name], snapshot,
            (self.last.content_hash,), self.status, 'builder'))
        self.files[name] = snapshot

    def _write(self, name, record):
        if type(record) is not FrozenRecord:
            raise ContractError('M9 builder returned an unrecordable output')
        _exclusive(self.root / name, record)
        self._observe(name)

    def _finish(self, error=None):
        # Capture files even when a durable write/observer was interrupted.
        for name in _FILES:
            if (self.root / name).exists():
                self._observe(name)
        body = {'schema': 'm9-build-terminal-v1', 'status': 'failed' if error else 'succeeded',
                'activation': 'not_applied' if self.status == 'not_applied' else 'applied',
                'phase': self.phase, 'error_type': type(error).__name__ if error else None,
                'error': str(error) if error else None, 'files': self.files,
                'builder_digest': self.builder.digest, 'parent_digest': self.parent.digest,
                'manifest_digest': self.manifest.content_hash, 'search_cost': 1,
                'builder_attempted': self.phase not in {'before_execute', 'write_builder'},
                'scientific_validated': False}
        _exclusive(self.root / _TERMINAL, FrozenRecord.from_dict(body))
        self.terminal = self.catalogue.append(**_spec('m9_build_terminal', _snapshot(self.root, _TERMINAL),
            (self.last.content_hash,), 'failed' if error else self.status, units=int(body['builder_attempted'])))
        return self.terminal

    def fail(self, error):
        """Retain a failed attempt; never overwrite a prior successful build."""
        if self.terminal is not None:
            return self.terminal
        if not isinstance(error, Exception):
            raise ContractError('M9 failure must retain the original exception')
        return self._finish(error)

    def execute(self):
        if self.terminal is not None or self.phase != 'before_execute':
            raise ContractError('M9 build can execute only once')
        try:
            self.phase = 'write_builder'
            self._write('builder.json', self.builder.record)
            self.phase = 'execute'
            candidate, receipt = RestrictedBuilderPort().execute(self.builder, self.manifest, self.parent,
                expected_builder_digest=self.builder.digest, expected_entrypoint=self.builder.entrypoint, search_cost=1)
            # Retain both serializable results before either individual writer
            # can fail, including a valid candidate with an invalid receipt.
            self.phase = 'write_return'
            returned = {}
            for name, value in (('candidate', candidate), ('receipt', receipt)):
                record = getattr(value, 'record', None)
                returned[name] = record.data() if type(record) is FrozenRecord else None
                returned[name + '_type'] = type(value).__name__
            self._write(_RETURNED, FrozenRecord.from_dict(returned))
            # Keep returned records before semantic checks. Receipt precedes
            # candidate so its descriptor is a causal parent of that candidate.
            self.phase = 'write_receipt'
            self._write('builder-receipt.json', getattr(receipt, 'record', None))
            self.phase = 'write_candidate'
            self._write('candidate.json', getattr(candidate, 'record', None))
            self.phase = 'validate'
            _checked_build(candidate, receipt, self.builder, self.parent)
            self.phase = 'complete'
            self._finish()
            return candidate, receipt
        except Exception as exc:
            try:
                self.fail(exc)
            except Exception as journal_error:
                # Preserve original ContractError identity. The caller owns the
                # stage failure journal if this journal write itself failed.
                exc.add_note('M9 failure journal error: ' + type(journal_error).__name__)
            raise


def _match(descriptor, spec):
    actual = descriptor.data()
    payload = FrozenRecord.from_dict(spec['payload'])
    expected = {**actual, **spec,
        'payload': {'digest': payload.content_hash, 'bytes': len(payload.encoded.encode('utf-8')),
                    'encoding': 'canonical_json', 'canonical': payload.data()},
        'parents': list(spec['parents']), 'optimizer_visible': False, 'scientific_validated': False,
        'coverage': 'covered', 'control_sources': [], 'config_refs': [], 'checks': []}
    if actual != expected:
        raise ContractError('M9 artifact differs from original inputs, files, or semantic replay')


def verify_builder_artifacts(catalogue, *, root, builder, parent, response, recipe, fixed_builder):
    """Read existing files and replay the literal DSL; never create/resume work."""
    enabled, manifest = _inputs(catalogue, builder, parent, response, recipe, fixed_builder)
    root = Path(root)
    records = catalogue.records()
    selected = [(i, r) for i, r in enumerate(records) if r.data()['kind'].startswith('m9_')]
    if len(selected) < 3:
        raise ContractError('M9 build has no complete begin/terminal evidence')
    request, returned = _invocation(records[:selected[0][0]], response, enabled, catalogue, parent)
    rows = [r for _, r in selected]
    status = 'produced' if enabled else 'not_applied'
    _match(rows[0], _spec('m9_builder_selection',
        _selection(builder, response, recipe, fixed_builder, request, returned, enabled),
        (request.content_hash, returned.content_hash), status, 'selection'))
    _match(rows[1], _spec('m9_builder_subjects', {'parent': parent.record.data(), 'parent_digest': parent.digest,
        'manifest': manifest.record.data(), 'manifest_digest': manifest.content_hash, 'search_cost': 1},
        (rows[0].content_hash,), status, 'builder'))
    terminal = _read(root, _TERMINAL).data()
    if (set(terminal) != {'schema', 'status', 'activation', 'phase', 'error_type', 'error', 'files',
                         'builder_digest', 'parent_digest', 'manifest_digest', 'search_cost', 'builder_attempted', 'scientific_validated'}
            or terminal['schema'] != 'm9-build-terminal-v1' or terminal['status'] not in {'failed', 'succeeded'}
            or terminal['activation'] != ('applied' if enabled else 'not_applied')
            or terminal['builder_digest'] != builder.digest or terminal['parent_digest'] != parent.digest
            or terminal['manifest_digest'] != manifest.content_hash
            or type(terminal['search_cost']) is not int or terminal['search_cost'] != 1
            or type(terminal['builder_attempted']) is not bool
            or terminal['scientific_validated'] is not False):
        raise ContractError('M9 terminal subject or status drift')
    snapshots = {name: _snapshot(root, name) for name in _FILES if (root / name).exists()}
    if terminal['files'] != snapshots or len(rows) != len(snapshots) + 3:
        raise ContractError('M9 missing or unregistered original output')
    last, observed = rows[1], []
    for row in rows[2:-1]:
        name = row.data()['payload']['canonical'].get('file')
        if name not in snapshots or name in observed:
            raise ContractError('M9 output order or uniqueness drift')
        _match(row, _spec(_KINDS[name], snapshots[name], (last.content_hash,), status, 'builder'))
        observed.append(name)
        last = row
    if observed != [name for name in _FILES if name in snapshots]:
        raise ContractError('M9 durable output order drift')
    failed = terminal['status'] == 'failed'
    phase = terminal['phase']
    reachable = {'before_execute': (0,), 'write_builder': (0, 1), 'execute': (1,),
                 'write_return': (1, 2), 'write_receipt': (2, 3), 'write_candidate': (3, 4),
                 'validate': (4,), 'complete': (4,)}
    if (type(phase) is not str or phase not in reachable or len(observed) not in reachable[phase]
            or observed != list(_FILES[:len(observed)])
            or terminal['builder_attempted'] != (phase not in {'before_execute', 'write_builder'})):
        raise ContractError('M9 terminal phase cannot produce its retained file state')
    _match(rows[-1], _spec('m9_build_terminal', _snapshot(root, _TERMINAL), (last.content_hash,),
                          'failed' if failed else status, units=int(terminal['builder_attempted'])))
    if _RETURNED in snapshots:
        returned = snapshots[_RETURNED]['canonical']
        if returned is None:
            if not failed or phase != 'write_return':
                raise ContractError('M9 original returned outputs are malformed')
        else:
            if (set(returned) != {'candidate', 'receipt', 'candidate_type', 'receipt_type'}
                    or any(type(returned[k]) is not str or not returned[k] for k in ('candidate_type', 'receipt_type'))):
                raise ContractError('M9 original returned output schema drift')
            for key, name in (('candidate', 'candidate.json'), ('receipt', 'builder-receipt.json')):
                value = returned[key]
                if value is not None and type(value) is not dict:
                    raise ContractError('M9 returned output must be a canonical record or absent')
                if name in snapshots and snapshots[name]['canonical'] is not None and value != snapshots[name]['canonical']:
                    raise ContractError('M9 original return differs from its output file')
            if not failed and (returned['candidate_type'] != 'CandidatePackage' or returned['receipt_type'] != 'BuilderRunReceipt'):
                raise ContractError('M9 successful build returned untyped outputs')
    if 'builder.json' in snapshots:
        if snapshots['builder.json']['canonical'] is None:
            if not failed or terminal['phase'] != 'write_builder':
                raise ContractError('M9 malformed original selected builder')
        elif _read(root, 'builder.json') != builder.record:
            raise ContractError('M9 original selected builder differs')
    if not failed:
        if (observed != list(_FILES) or terminal['phase'] != 'complete'
                or terminal['error'] is not None or terminal['error_type'] is not None):
            raise ContractError('M9 successful terminal has missing outputs or failure fields')
        candidate = CandidatePackage(_read(root, 'candidate.json'))
        receipt = BuilderRunReceipt(_read(root, 'builder-receipt.json'))
        replay_candidate, replay_receipt = RestrictedBuilderPort().execute(builder, manifest, parent,
            expected_builder_digest=builder.digest, expected_entrypoint=builder.entrypoint, search_cost=1)
        _checked_build(candidate, receipt, builder, parent)
        if candidate != replay_candidate or receipt != replay_receipt:
            raise ContractError('M9 original outputs differ from restricted interpreter replay')
    elif (type(terminal['error_type']) is not str or not terminal['error_type'] or type(terminal['error']) is not str):
        raise ContractError('M9 failed terminal lacks its original failure')
    return FrozenRecord.from_dict({'schema': 'm9-builder-artifacts-verified-v1',
        'status': terminal['status'], 'activation': terminal['activation'],
        'candidate_digest': _read(root, 'candidate.json').content_hash if not failed else None,
        'scientific_validated': False, 'scientific_effect': 'not_measured'})
