"""Immutable, local custody for one two-authority material qualification.

The receipt remains the compatibility boundary.  This companion directory is
deliberately independent: it records what was supplied to an authority before
it is invoked, and byte-for-byte copies of every subsequently overwritten
receipt version.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid
import re

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical


def _error_chain(exc):
    values = []
    while exc is not None and len(values) < 8:
        values.append(type(exc).__name__)
        exc = exc.__cause__ or exc.__context__
    return values


def _linked(path: Path):
    """Reject the path and every existing ancestor if it is a link/junction."""
    path = Path(path)
    current = path
    while True:
        try:
            if current.exists() or current.is_symlink():
                stat = current.lstat()
                if current.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                    return True
        except OSError:
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


class MaterialQualificationArtifacts:
    """Write-once custody companion for a single receipt path."""

    def __init__(self, receipt: Path, *, request: FrozenRecord, binding: FrozenRecord,
                 material: FrozenRecord, cell_binding: FrozenRecord):
        self.receipt = Path(receipt)
        self.root = self.receipt.with_name(self.receipt.name + '.artifacts')
        self.attempt_id = uuid.uuid4().hex
        if _linked(self.receipt.parent) or _linked(self.root.parent) or self.root.exists():
            raise ContractError('material artifact storage path is unsafe or already used')
        self.root.mkdir(parents=False)
        self.blobs = self.root / 'blobs'; self.blobs.mkdir()
        self.journal = self.root / 'journal.jsonl'
        sources = []
        for producer in (Path(__file__), Path(__file__).with_name('lineage_combination_material.py')):
            raw = producer.read_bytes()
            sources.append({'path': str(producer.resolve()), 'snapshot': self._put(raw)})
        self._event('begin', {'attempt_id': self.attempt_id, 'request': self._put_record(request),
            'binding': self._put_record(binding), 'material': self._put_record(material),
            'cell_binding': self._put_record(cell_binding), 'producer_sources': sources})

    def _put(self, raw: bytes):
        digest = hashlib.sha256(raw).hexdigest(); target = self.blobs / digest
        if _linked(self.blobs) or _linked(target):
            raise ContractError('material artifact storage path is unsafe')
        if target.exists():
            if target.read_bytes() != raw: raise ContractError('material artifact blob collision')
        else:
            try:
                with target.open('xb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            except OSError as exc:
                raise ContractError('material artifact blob write failed') from exc
        return {'sha256': digest, 'bytes': len(raw)}

    def _put_record(self, value):
        return self._put(value.encoded.encode('utf-8'))

    def _event(self, kind, data):
        if _linked(self.root) or _linked(self.journal): raise ContractError('material artifact storage path is unsafe')
        row = FrozenRecord.from_dict({'schema': 'material-qualification-artifact-event-v1',
            'sequence': sum(1 for _ in self.journal.open('r', encoding='utf-8')) if self.journal.exists() else 0,
            'kind': kind, 'data': data})
        try:
            with self.journal.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(row.encoded + '\n'); stream.flush(); os.fsync(stream.fileno())
        except OSError as exc:
            raise ContractError('material artifact journal write failed') from exc

    def reserve(self, authority, request):
        self._event('reserved', {'authority': authority, 'request': self._put_record(request)})

    def returned(self, authority, value):
        if isinstance(value, FrozenRecord):
            self._event('returned', {'authority': authority, 'typed': True, 'return': self._put_record(value)})
        else:
            self._event('returned', {'authority': authority, 'typed': False,
                'return_type': type(value).__name__})

    def checked(self, authority, status, response, cost_units, error=None):
        data = {'authority': authority, 'status': status, 'response': self._put_record(response)
                if isinstance(response, FrozenRecord) else None, 'cost_units': cost_units,
                'cost_unknown': cost_units is None, 'error_chain': _error_chain(error) if error else []}
        self._event('checked', data)

    def snapshot(self, label):
        try: raw = self.receipt.read_bytes()
        except OSError as exc: raise ContractError('material sidecar snapshot failed') from exc
        self._event('sidecar_snapshot', {'label': label, 'snapshot': self._put(raw)})

    def terminal(self, status):
        self._event('terminal', {'status': 'completed', 'outcome': status, 'receipt': self._put(self.receipt.read_bytes())})
        seal = FrozenRecord.from_dict({'schema': 'material-qualification-artifact-seal-v1',
            'attempt_id': self.attempt_id, 'journal_sha256': hashlib.sha256(self.journal.read_bytes()).hexdigest()})
        try:
            with (self.root / 'seal.json').open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(seal.encoded + '\n'); stream.flush(); os.fsync(stream.fileno())
        except OSError as exc: raise ContractError('material artifact seal write failed') from exc

    @classmethod
    def inspect(cls, receipt: Path):
        """Read custody without interpreting it as an accepted qualification."""
        receipt = Path(receipt); root = receipt.with_name(receipt.name + '.artifacts')
        if (_linked(receipt) or _linked(root) or not root.is_dir() or _linked(root / 'blobs')
                or _linked(root / 'journal.jsonl') or _linked(root / 'seal.json')):
            raise ContractError('material artifact reader is non-accepted')
        try:
            rows = [FrozenRecord(line).data() for line in (root / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
            seal = FrozenRecord((root / 'seal.json').read_text(encoding='utf-8').strip()).data()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ContractError('material artifact reader is non-accepted') from exc
        if not rows or any(r.get('schema') != 'material-qualification-artifact-event-v1' or r.get('sequence') != n for n,r in enumerate(rows)):
            raise ContractError('material artifact reader is non-accepted')
        if seal.get('schema') != 'material-qualification-artifact-seal-v1' or seal.get('journal_sha256') != hashlib.sha256((root / 'journal.jsonl').read_bytes()).hexdigest():
            raise ContractError('material artifact reader is non-accepted')
        def raw(ref):
            if (not isinstance(ref, dict) or set(ref) != {'sha256','bytes'} or type(ref['sha256']) is not str
                    or not re.fullmatch('[0-9a-f]{64}', ref['sha256']) or type(ref['bytes']) is not int or ref['bytes'] < 0): raise ContractError('material artifact reader is non-accepted')
            p = root/'blobs'/ref['sha256']
            if _linked(p): raise ContractError('material artifact reader is non-accepted')
            try: value = p.read_bytes()
            except OSError as exc: raise ContractError('material artifact reader is non-accepted') from exc
            if len(value) != ref['bytes'] or hashlib.sha256(value).hexdigest() != ref['sha256']: raise ContractError('material artifact reader is non-accepted')
            return value
        # Check every file reference even for a rejected/failed qualification.
        for row in rows:
            data = row['data']
            for key in ('request', 'binding', 'material', 'cell_binding', 'return', 'response', 'snapshot', 'receipt'):
                if key in data and data[key] is not None: raw(data[key])
            for source in data.get('producer_sources', []):
                if set(source) != {'path','snapshot'} or not isinstance(source['path'], str): raise ContractError('material artifact reader is non-accepted')
                raw(source['snapshot'])
        return root, rows, seal, raw

    @classmethod
    def verify(cls, receipt: Path, *, request: FrozenRecord, binding: FrozenRecord,
               material: FrozenRecord, cell_binding: FrozenRecord):
        receipt = Path(receipt)
        try:
            root, rows, seal, raw = cls.inspect(receipt)
            final = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, ValueError, json.JSONDecodeError, ContractError) as exc:
            raise ContractError('material artifact reader is non-accepted') from exc
        begin = rows[0]
        if begin['kind'] != 'begin' or set(begin['data']) != {'attempt_id','request','binding','material','cell_binding','producer_sources'}:
            raise ContractError('material artifact reader is non-accepted')
        if (set(seal) != {'schema','attempt_id','journal_sha256'} or type(begin['data']['attempt_id']) is not str
                or not re.fullmatch('[0-9a-f]{32}', begin['data']['attempt_id']) or seal['attempt_id'] != begin['data']['attempt_id']):
            raise ContractError('material artifact reader is non-accepted')
        expected = [request, binding, material, cell_binding]
        if [raw(begin['data'][k]) for k in ('request','binding','material','cell_binding')] != [x.encoded.encode('utf-8') for x in expected]:
            raise ContractError('material artifact reader is non-accepted')
        expected_kinds = ['begin'] + sum((['sidecar_snapshot','reserved','returned','checked','sidecar_snapshot'] for _ in range(2)), []) + ['terminal']
        if [r['kind'] for r in rows] != expected_kinds or not isinstance(final, dict) or not isinstance(final.get('calls'), list) or len(final['calls']) != 2:
            raise ContractError('material artifact reader is non-accepted')
        for n, final_row in enumerate(final['calls']):
            reserved, returned, checked = rows[2 + n * 5], rows[3 + n * 5], rows[4 + n * 5]
            authority = final_row.get('authority')
            if (reserved['data'].get('authority') != authority or raw(reserved['data']['request']) != request.encoded.encode('utf-8')
                    or returned['data'].get('authority') != authority or checked['data'].get('authority') != authority
                    or checked['data'].get('status') != final_row.get('status')
                    or type(checked['data'].get('cost_units')) is not type(final_row.get('cost_units'))
                    or checked['data'].get('cost_units') != final_row.get('cost_units')
                    or checked['data'].get('cost_unknown') is not (final_row.get('cost_units') is None)):
                raise ContractError('material artifact reader is non-accepted')
            response = final_row.get('response')
            if response is None:
                if checked['data'].get('response') is not None: raise ContractError('material artifact reader is non-accepted')
            else:
                encoded = FrozenRecord.from_dict(response).encoded.encode('utf-8')
                if checked['data'].get('response') is None or raw(checked['data']['response']) != encoded: raise ContractError('material artifact reader is non-accepted')
                if returned['data'].get('typed') is not True or raw(returned['data'].get('return')) != encoded: raise ContractError('material artifact reader is non-accepted')
        snapshots = [r for r in rows if r['kind'] == 'sidecar_snapshot']
        terminal = [r for r in rows if r['kind'] == 'terminal']
        expected_status = 'accepted' if all(c.get('status') == 'verified' for c in final['calls']) else 'incomplete'
        if (len(terminal) != 1 or set(terminal[0]['data']) != {'status','outcome','receipt'} or terminal[0]['data'].get('status') != 'completed' or terminal[0]['data'].get('outcome') != expected_status or not snapshots
                or raw(terminal[0]['data']['receipt']) != receipt.read_bytes() or raw(snapshots[-1]['data']['snapshot']) != receipt.read_bytes()):
            raise ContractError('material artifact reader is non-accepted')
        # Each snapshot is an immutable copy of the sidecar state at the exact
        # reservation/check transition; a rehashed journal cannot add or omit a
        # call and still claim the same final receipt.
        for n in range(2):
            for phase, count in (('reserved-', n + 1), ('checked-', n + 1)):
                position = 1 + n * 5 if phase == 'reserved-' else 5 + n * 5
                row = rows[position]
                if row['data'].get('label') != phase + str(n): raise ContractError('material artifact reader is non-accepted')
                expected_calls = final['calls'][:count]
                if phase == 'reserved-':
                    expected_calls = [dict(v) for v in expected_calls]
                    expected_calls[-1].update(status='reserved', response=None, cost_units=None, cost_unknown=True)
                    expected_calls[-1].pop('error_type', None)
                expected = {'request': final.get('request'), 'binding': final.get('binding'), 'calls': expected_calls}
                if raw(row['data']['snapshot']) != canonical(expected).encode('utf-8'):
                    raise ContractError('material artifact reader is non-accepted')
        return FrozenRecord.from_dict({'attempt_id': seal['attempt_id'], 'journal_sha256': seal['journal_sha256'],
            'snapshot_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()})
