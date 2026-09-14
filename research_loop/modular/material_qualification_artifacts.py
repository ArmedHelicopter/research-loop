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
import stat
import math

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical


def _error_chain(exc):
    values = []
    while exc is not None and len(values) < 8:
        name = type(exc).__name__
        values.append(name if re.fullmatch(r'[A-Za-z_]\w{0,79}', name) else 'Exception')
        exc = exc.__cause__ or exc.__context__
    return values


def _linked(path: Path):
    """Reject the path and every existing ancestor if it is a link/junction."""
    path = Path(path).absolute()
    current = path
    while True:
        try:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return True
        except FileNotFoundError:
            pass
        except OSError:
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


_SOURCES = ('material_qualification_artifacts.py', 'lineage_combination_material.py', 'admission_combination.py')
_READER_ERROR = 'material artifact reader is non-accepted'


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ContractError(_READER_ERROR)


def _read(path):
    if _linked(path) or not path.is_file(): raise ContractError(_READER_ERROR)
    return path.read_bytes()


def _ref(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _storage_files(root):
    # Check the entire inventory before the first content read; never traverse
    # an unexpected directory, symlink, or Windows junction.
    if _linked(root) or not root.is_dir(): raise ContractError(_READER_ERROR)
    files = {}
    for path in root.iterdir():
        if _linked(path): raise ContractError(_READER_ERROR)
        if path.name == 'blobs' and path.is_dir():
            for blob in path.iterdir():
                if _linked(blob) or not blob.is_file() or re.fullmatch('[0-9a-f]{64}', blob.name) is None:
                    raise ContractError(_READER_ERROR)
                files['blobs/' + blob.name] = blob
        elif path.name in {'attempt.json', 'journal.jsonl', 'seal.json', 'failure.json'} and path.is_file():
            files[path.name] = path
        else: raise ContractError(_READER_ERROR)
    return files


def _errors(value, required=False):
    if (type(value) is not list or len(value) > 8 or required and not value
            or any(type(v) is not str or re.fullmatch(r'[A-Za-z_]\w{0,79}', v) is None for v in value)):
        raise ContractError(_READER_ERROR)


def _complete_attempt_id(root):
    path = root/'attempt.json'
    if not path.exists(): return None
    raw = _read(path)
    try:
        body = json.loads(raw)
        _fields(body, 'schema attempt_id request binding material cell_binding')
        if (body['schema'] != 'material-qualification-attempt-v1' or type(body['attempt_id']) is not str
                or re.fullmatch('[0-9a-f]{32}', body['attempt_id']) is None
                or raw != (FrozenRecord.from_dict(body).encoded+'\n').encode()): return None
        return body['attempt_id']
    except (ValueError, TypeError, ContractError): return None


def _json_value(value, depth=0):
    if depth > 16: return False
    if value is None or type(value) in {bool, int}: return True
    if type(value) is float: return math.isfinite(value)
    if type(value) is str: return len(value.encode('utf-8')) <= 65536
    if type(value) is list: return len(value) <= 128 and all(_json_value(v, depth+1) for v in value)
    if type(value) is dict:
        return len(value) <= 128 and all(type(k) is str and _json_value(k, depth+1) and _json_value(v, depth+1) for k,v in value.items())
    return False


class MaterialQualificationArtifacts:
    """Write-once custody companion for a single receipt path."""

    def __init__(self, receipt: Path, *, request: FrozenRecord, binding: FrozenRecord,
                 material: FrozenRecord, cell_binding: FrozenRecord):
        self.receipt = Path(receipt)
        self.root = self.receipt.with_name(self.receipt.name + '.artifacts')
        self.attempt_id = uuid.uuid4().hex
        self.blobs = self.root / 'blobs'
        self.journal = self.root / 'journal.jsonl'
        self._closed = False
        if _linked(self.receipt) or _linked(self.root) or self.root.exists():
            raise ContractError('material artifact storage path is unsafe or already used')
        self.root.mkdir(parents=False)
        try:
            attempt = FrozenRecord.from_dict({'schema': 'material-qualification-attempt-v1', 'attempt_id': self.attempt_id,
                'request': request.data(), 'binding': binding.data(), 'material': material.data(), 'cell_binding': cell_binding.data()})
            if _linked(self.root/'attempt.json'): raise ContractError('material attempt storage path is unsafe')
            with (self.root / 'attempt.json').open('xb') as stream:
                stream.write((attempt.encoded + '\n').encode()); stream.flush(); os.fsync(stream.fileno())
            self.blobs.mkdir()
            inputs = {name: self._put_record(value) for name, value in (
                ('request', request), ('binding', binding), ('material', material), ('cell_binding', cell_binding))}
            sources = []
            for name in _SOURCES:
                producer = Path(__file__).with_name(name)
                sources.append({'path': str(producer.absolute()), 'snapshot': self._put(_read(producer))})
            self._event('begin', {'attempt_id': self.attempt_id, **inputs, 'producer_sources': sources})
        except Exception as exc:
            try: self.abort(exc)
            except Exception as storage_error:
                exc.add_note('material failure storage incomplete: ' + type(storage_error).__name__)
            raise ContractError('material artifact initialization failed') from exc

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
        if self._closed: raise ContractError('material artifact custody already closed')
        if _linked(self.root) or _linked(self.journal): raise ContractError('material artifact storage path is unsafe')
        row = FrozenRecord.from_dict({'schema': 'material-qualification-artifact-event-v1',
            'sequence': len(_read(self.journal).splitlines()) if self.journal.exists() else 0,
            'kind': kind, 'data': data})
        try:
            with self.journal.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(row.encoded + '\n'); stream.flush(); os.fsync(stream.fileno())
        except OSError as exc:
            raise ContractError('material artifact journal write failed') from exc

    def reserve(self, authority, request):
        self._event('reserved', {'authority': authority, 'request': self._put_record(request)})

    def returned(self, authority, value):
        if type(value) is FrozenRecord:
            self._event('returned', {'authority': authority, 'typed': True, 'return': self._put_record(value)})
        else:
            data = {'authority': authority, 'typed': False, 'return_type': type(value).__name__,
                'capture': 'type_only', 'return': None}
            record = None
            try:
                if _json_value(value):
                    candidate = FrozenRecord.from_dict({'value': value})
                    if len(candidate.encoded.encode()) <= 262144: record = candidate
            except (ValueError, TypeError, OverflowError):
                pass
            if record is not None:
                data['capture'] = 'bounded_json'; data['return'] = self._put_record(record)
            self._event('returned', data)

    def checked(self, authority, status, response, cost_units, error=None):
        data = {'authority': authority, 'status': status, 'response': self._put_record(response)
                if type(response) is FrozenRecord else None, 'cost_units': cost_units,
                'cost_unknown': cost_units is None, 'error_chain': _error_chain(error) if error else []}
        self._event('checked', data)

    def snapshot(self, label):
        if _linked(self.receipt):
            raise ContractError('material sidecar snapshot failed')
        try: raw = _read(self.receipt)
        except OSError as exc: raise ContractError('material sidecar snapshot failed') from exc
        self._event('sidecar_snapshot', {'label': label, 'snapshot': self._put(raw)})

    def terminal(self, status):
        if status not in {'accepted', 'rejected'}: raise ContractError('material artifact terminal outcome invalid')
        if _linked(self.receipt) or _linked(self.root / 'seal.json'):
            raise ContractError('material artifact seal write failed')
        self._event('terminal', {'status': 'completed', 'outcome': status, 'receipt': self._put(_read(self.receipt))})
        seal = FrozenRecord.from_dict({'schema': 'material-qualification-artifact-seal-v1',
            'attempt_id': self.attempt_id, 'journal_sha256': hashlib.sha256(_read(self.journal)).hexdigest()})
        try:
            with (self.root / 'seal.json').open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(seal.encoded + '\n'); stream.flush(); os.fsync(stream.fileno())
        except OSError as exc: raise ContractError('material artifact seal write failed') from exc
        self._closed = True

    def abort(self, exc):
        self._closed = True
        try:
            target = self.root / 'failure.json'
            if _linked(target): raise ContractError('material failure storage path is unsafe')
            if target.exists(): return
            inventory = {name: _ref(_read(path)) for name, path in _storage_files(self.root).items()}
            bound_attempt = _complete_attempt_id(self.root)
            if bound_attempt is not None and bound_attempt != self.attempt_id: raise ContractError('material failure attempt binding differs')
            sidecars = {}
            for name, path in (('receipt', self.receipt), ('temporary', self.receipt.with_suffix(self.receipt.suffix+'.tmp'))):
                if _linked(path): raise ContractError('material failure storage path is unsafe')
                sidecars[name] = _ref(_read(path)) if path.exists() else None
            body = FrozenRecord.from_dict({'schema': 'material-qualification-artifact-failure-v1', 'attempt_id': self.attempt_id,
                'inventory': inventory, 'sidecars': sidecars, 'error_chain': _error_chain(exc)})
            with target.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(body.encoded + '\n'); stream.flush(); os.fsync(stream.fileno())
        except Exception as storage_error:
            raise ContractError('material failure storage incomplete') from storage_error

    @classmethod
    def inspect(cls, receipt: Path):
        """Read custody without interpreting it as an accepted qualification."""
        try: return cls._inspect(Path(receipt))
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, ContractError) as exc:
            raise ContractError(_READER_ERROR) from exc

    @classmethod
    def _inspect(cls, receipt):
        receipt = Path(receipt); root = receipt.with_name(receipt.name + '.artifacts')
        if (_linked(receipt) or _linked(root) or not root.is_dir() or _linked(root / 'blobs')
                or _linked(root / 'journal.jsonl') or _linked(root / 'seal.json')):
            raise ContractError('material artifact reader is non-accepted')
        inventory = _storage_files(root)
        seen = set()
        def raw(ref):
            _fields(ref, 'sha256 bytes')
            if (type(ref['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', ref['sha256']) is None
                    or type(ref['bytes']) is not int or ref['bytes'] < 0): raise ContractError(_READER_ERROR)
            name = 'blobs/' + ref['sha256']; value = _read(root/name)
            if _ref(value) != ref: raise ContractError(_READER_ERROR)
            seen.add(name)
            return value
        if 'failure.json' in inventory:
            failure_raw = _read(inventory['failure.json']); failure = json.loads(failure_raw)
            _fields(failure, 'schema attempt_id inventory sidecars error_chain')
            if (failure['schema'] != 'material-qualification-artifact-failure-v1' or type(failure['attempt_id']) is not str
                    or re.fullmatch('[0-9a-f]{32}', failure['attempt_id']) is None
                    or type(failure['inventory']) is not dict or set(failure['inventory']) != set(inventory)-{'failure.json'}):
                raise ContractError(_READER_ERROR)
            _errors(failure['error_chain'], required=True)
            if failure_raw != (FrozenRecord.from_dict(failure).encoded+'\n').encode(): raise ContractError(_READER_ERROR)
            bound_attempt = _complete_attempt_id(root)
            if bound_attempt is not None and bound_attempt != failure['attempt_id']: raise ContractError(_READER_ERROR)
            _fields(failure['sidecars'], 'receipt temporary')
            for name, path in (('receipt', receipt), ('temporary', receipt.with_suffix(receipt.suffix+'.tmp'))):
                if _linked(path): raise ContractError(_READER_ERROR)
                ref = failure['sidecars'][name]
                if ref is None:
                    if path.exists(): raise ContractError(_READER_ERROR)
                else:
                    _fields(ref, 'sha256 bytes')
                    if type(ref['bytes']) is not int or _ref(_read(path)) != ref: raise ContractError(_READER_ERROR)
            for name, ref in failure['inventory'].items():
                _fields(ref, 'sha256 bytes')
                if type(ref['bytes']) is not int or _ref(_read(inventory[name])) != ref: raise ContractError(_READER_ERROR)
            # A failed write may leave a truncated journal/blob/seal. The
            # independent inventory attests retained bytes, not parsed success.
            prefix = []
            if 'journal.jsonl' in inventory:
                for line in _read(inventory['journal.jsonl']).splitlines():
                    try: prefix.append(FrozenRecord(line.decode('utf-8')).data())
                    except (ValueError, ContractError): break
            if prefix and prefix[0].get('kind') == 'begin' and type(prefix[0].get('data')) is dict:
                if prefix[0]['data'].get('attempt_id') != failure['attempt_id']: raise ContractError(_READER_ERROR)
            return root, prefix, None, raw
        try:
            journal = _read(root/'journal.jsonl')
            rows = [FrozenRecord(line).data() for line in journal.decode('utf-8').splitlines()]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ContractError('material artifact reader is non-accepted') from exc
        if (not rows or len(rows) > 12 or journal != b''.join((FrozenRecord.from_dict(r).encoded+'\n').encode() for r in rows)
                or any(r.get('schema') != 'material-qualification-artifact-event-v1' or type(r.get('sequence')) is not int or r.get('sequence') != n for n,r in enumerate(rows))):
            raise ContractError('material artifact reader is non-accepted')
        seal = None
        if (root / 'seal.json').exists():
            try:
                seal_raw = _read(root/'seal.json'); seal = FrozenRecord(seal_raw.decode().strip()).data()
            except (OSError, ValueError, json.JSONDecodeError) as exc: raise ContractError('material artifact reader is non-accepted') from exc
            _fields(seal, 'schema attempt_id journal_sha256')
            if seal_raw != (FrozenRecord.from_dict(seal).encoded+'\n').encode(): raise ContractError(_READER_ERROR)
            if seal.get('schema') != 'material-qualification-artifact-seal-v1' or seal.get('journal_sha256') != hashlib.sha256(journal).hexdigest():
                raise ContractError('material artifact reader is non-accepted')
        # Check every file reference even for a rejected/failed qualification.
        for n, row in enumerate(rows):
            _fields(row, 'schema sequence kind data')
            data = row['data']
            kind = row['kind']
            if kind == 'begin':
                _fields(data, 'attempt_id request binding material cell_binding producer_sources')
                if n != 0 or type(data['attempt_id']) is not str or re.fullmatch('[0-9a-f]{32}', data['attempt_id']) is None: raise ContractError(_READER_ERROR)
                if type(data['producer_sources']) is not list or len(data['producer_sources']) != len(_SOURCES): raise ContractError(_READER_ERROR)
                for source, name in zip(data['producer_sources'], _SOURCES):
                    _fields(source, 'path snapshot')
                    if type(source['path']) is not str or Path(source['path']).name != name: raise ContractError(_READER_ERROR)
            elif kind == 'reserved': _fields(data, 'authority request')
            elif kind == 'returned':
                if type(data) is not dict or type(data.get('typed')) is not bool: raise ContractError(_READER_ERROR)
                _fields(data, 'authority typed return' if data['typed'] else 'authority typed return_type capture return')
                if not data['typed'] and (data['capture'] not in {'type_only','bounded_json'} or (data['return'] is None) != (data['capture']=='type_only')):
                    raise ContractError(_READER_ERROR)
                if not data['typed'] and (type(data['return_type']) is not str or not data['return_type'] or len(data['return_type']) > 160): raise ContractError(_READER_ERROR)
                if not data['typed'] and data['capture']=='bounded_json':
                    retained = raw(data['return'])
                    value = json.loads(retained); _fields(value, 'value')
                    if (len(retained)>262144 or not _json_value(value['value'])
                            or type(value['value']).__name__ != data['return_type']): raise ContractError(_READER_ERROR)
            elif kind == 'checked':
                _fields(data, 'authority status response cost_units cost_unknown error_chain')
                if data['status'] not in {'verified','rejected','unknown','failed'}: raise ContractError(_READER_ERROR)
                if data['cost_units'] is not None and (type(data['cost_units']) is not int or data['cost_units'] < 0): raise ContractError(_READER_ERROR)
                if data['cost_unknown'] is not (data['cost_units'] is None): raise ContractError(_READER_ERROR)
                _errors(data['error_chain'], required=data['status']=='failed')
                if data['status'] != 'failed' and data['error_chain']: raise ContractError(_READER_ERROR)
            elif kind == 'sidecar_snapshot':
                _fields(data, 'label snapshot')
                if data['label'] not in {'reserved-0','checked-0','reserved-1','checked-1'}: raise ContractError(_READER_ERROR)
            elif kind == 'terminal':
                _fields(data, 'status outcome receipt')
                if n != len(rows)-1 or data['status'] != 'completed' or data['outcome'] not in {'accepted','rejected'}: raise ContractError(_READER_ERROR)
            else: raise ContractError(_READER_ERROR)
            if 'authority' in data and (type(data['authority']) is not str or not data['authority']): raise ContractError(_READER_ERROR)
            for key in ('request', 'binding', 'material', 'cell_binding', 'return', 'response', 'snapshot', 'receipt'):
                if key in data and data[key] is not None: raw(data[key])
            for source in data.get('producer_sources', []):
                if set(source) != {'path','snapshot'} or not isinstance(source['path'], str): raise ContractError('material artifact reader is non-accepted')
                raw(source['snapshot'])
        if rows[0]['kind'] != 'begin' or seal is None: raise ContractError(_READER_ERROR)
        if seal and (seal['attempt_id'] != rows[0]['data']['attempt_id'] or rows[-1]['kind'] != 'terminal'): raise ContractError(_READER_ERROR)
        attempt_raw = _read(root/'attempt.json'); attempt = json.loads(attempt_raw)
        _fields(attempt, 'schema attempt_id request binding material cell_binding')
        if (attempt['schema'] != 'material-qualification-attempt-v1' or attempt['attempt_id'] != rows[0]['data']['attempt_id']
                or attempt_raw != (FrozenRecord.from_dict(attempt).encoded+'\n').encode()): raise ContractError(_READER_ERROR)
        for name in ('request','binding','material','cell_binding'):
            if raw(rows[0]['data'][name]) != FrozenRecord.from_dict(attempt[name]).encoded.encode(): raise ContractError(_READER_ERROR)
        if set(inventory) != seen | {'attempt.json','journal.jsonl'} | ({'seal.json'} if seal else set()): raise ContractError(_READER_ERROR)
        return root, rows, seal, raw

    @classmethod
    def verify(cls, receipt: Path, *, request: FrozenRecord, binding: FrozenRecord,
               material: FrozenRecord, cell_binding: FrozenRecord):
        try:
            return cls._verify(receipt, request=request, binding=binding, material=material, cell_binding=cell_binding)
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, ContractError) as exc:
            raise ContractError(_READER_ERROR) from exc

    @classmethod
    def _verify(cls, receipt, *, request, binding, material, cell_binding):
        receipt = Path(receipt)
        try:
            root, rows, seal, raw = cls.inspect(receipt)
            final = json.loads(_read(receipt))
        except (OSError, ValueError, json.JSONDecodeError, ContractError) as exc:
            raise ContractError('material artifact reader is non-accepted') from exc
        begin = rows[0]
        if begin['kind'] != 'begin' or set(begin['data']) != {'attempt_id','request','binding','material','cell_binding','producer_sources'}:
            raise ContractError('material artifact reader is non-accepted')
        if (seal is None or set(seal) != {'schema','attempt_id','journal_sha256'} or type(begin['data']['attempt_id']) is not str
                or not re.fullmatch('[0-9a-f]{32}', begin['data']['attempt_id']) or seal['attempt_id'] != begin['data']['attempt_id']):
            raise ContractError('material artifact reader is non-accepted')
        sources = begin['data']['producer_sources']
        if type(sources) is not list or len(sources) != len(_SOURCES):
            raise ContractError('material artifact reader is non-accepted')
        for source, name in zip(sources, _SOURCES):
            trusted = Path(__file__).with_name(name)
            if source['path'] != str(trusted.absolute()) or raw(source['snapshot']) != _read(trusted): raise ContractError(_READER_ERROR)
        expected = [request, binding, material, cell_binding]
        if [raw(begin['data'][k]) for k in ('request','binding','material','cell_binding')] != [x.encoded.encode('utf-8') for x in expected]:
            raise ContractError('material artifact reader is non-accepted')
        expected_kinds = ['begin'] + sum((['sidecar_snapshot','reserved','returned','checked','sidecar_snapshot'] for _ in range(2)), []) + ['terminal']
        if [r['kind'] for r in rows] != expected_kinds or not isinstance(final, dict) or not isinstance(final.get('calls'), list) or len(final['calls']) != 2:
            raise ContractError('material artifact reader is non-accepted')
        _fields(final, 'request binding calls')
        if FrozenRecord.from_dict(final['request']) != request or FrozenRecord.from_dict(final['binding']) != binding:
            raise ContractError(_READER_ERROR)
        for n, final_row in enumerate(final['calls']):
            _fields(final_row, 'authority request_digest limits status response cost_units cost_unknown')
            if (type(final_row['response']) is not dict or final_row['authority'] != binding.data()['authorities'][n]['authority']
                    or final_row['request_digest'] != request.content_hash
                    or FrozenRecord.from_dict(final_row['limits']) != FrozenRecord.from_dict(request.data()['limits'])
                    or final_row['cost_unknown'] is not (final_row['cost_units'] is None)
                    or final_row['cost_units'] is not None and (type(final_row['cost_units']) is not int
                        or not 0 <= final_row['cost_units'] <= request.data()['limits']['cost_units'])):
                raise ContractError(_READER_ERROR)
            reserved, returned, checked = rows[2 + n * 5], rows[3 + n * 5], rows[4 + n * 5]
            authority = final_row.get('authority')
            if (reserved['data'].get('authority') != authority or raw(reserved['data']['request']) != request.encoded.encode('utf-8')
                    or returned['data'].get('authority') != authority or checked['data'].get('authority') != authority
                    or checked['data'].get('status') != final_row.get('status')
                    or type(checked['data'].get('cost_units')) is not type(final_row.get('cost_units'))
                    or checked['data'].get('cost_units') != final_row.get('cost_units')
                    or checked['data'].get('cost_unknown') is not (final_row.get('cost_units') is None)):
                raise ContractError('material artifact reader is non-accepted')
            if checked['data'].get('error_chain') != [] and final_row.get('status') == 'verified':
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
        expected_status = 'accepted'
        if not all(c.get('status') == 'verified' for c in final['calls']): raise ContractError(_READER_ERROR)
        if (len(terminal) != 1 or set(terminal[0]['data']) != {'status','outcome','receipt'} or terminal[0]['data'].get('status') != 'completed' or terminal[0]['data'].get('outcome') != expected_status or not snapshots
                or raw(terminal[0]['data']['receipt']) != _read(receipt) or raw(snapshots[-1]['data']['snapshot']) != _read(receipt)):
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
            'snapshot_sha256': hashlib.sha256(_read(receipt)).hexdigest()})
