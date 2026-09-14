"""Per-file M7/M8 witnesses for an already-bound exploration phase.

The bridge is deliberately optional: it records bytes only after the phase
writer has made them durable and never supplies data back to a worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from types import MappingProxyType

from research_loop.ontology import ContractError
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular(path: Path) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ContractError('regular phase artifact required')
    return path.read_bytes()


def _verify_witness_metadata(body):
    fields = {'phase_allocation':set(), 'phase_program':{'job'}, 'phase_return':{'job'},
        'phase_scheduler_event':{'sequence','event'}, 'phase_scheduler_sqlite':set(), 'phase_receipt':set()}
    payload = body.get('payload',{}).get('canonical')
    extra = payload.get('extra') if type(payload) is dict else None
    if (body['kind'] not in fields or type(extra) is not dict or set(extra) != fields[body['kind']]
            or body['cost'] != {'known':False,'units':None} or body['optimizer_visible']
            or body['control_sources'] or body['checks']):
        raise ContractError('phase witness cost, visibility or extra metadata differs')


@dataclass(frozen=True)
class PhaseArtifactContext:
    """Authenticated catalogue parents supplied by the stage owner."""
    catalogue: ArtifactCatalogue
    artifact_root: Path
    parents: Mapping[str, str]

    def __post_init__(self) -> None:
        if type(self.catalogue) is not ArtifactCatalogue or not isinstance(self.artifact_root, Path):
            raise ContractError('typed phase artifact context required')
        roles = ({'inputs': ('execution_phase_inputs', 'P0')} if set(self.parents) == {'inputs'} else
            {'invocation': ('model_context', 'M3'), 'selection': ('c4_choice_frozen', 'M7'),
             'source': ('retrieval_result', 'M6')})
        if set(self.parents) != set(roles) or any(type(v) is not str for v in self.parents.values()):
            raise ContractError('phase bridge requires actual bound phase inputs or C4 parents')
        known = {record.content_hash: record.data() for record in self.catalogue.records()}
        if len(set(self.parents.values())) != len(roles) or any(value not in known for value in self.parents.values()):
            raise ContractError('phase artifact parent is not in the authenticated catalogue')
        for role, (kind, module) in roles.items():
            body = known[self.parents[role]]
            if body['kind'] != kind or body['module'] != module or body['identity'] != self.catalogue.identity.data():
                raise ContractError('phase artifact parent has the wrong semantic role')
        object.__setattr__(self, 'parents', MappingProxyType({role: self.parents[role]
            for role in roles}))
        root = self.artifact_root.resolve()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise ContractError('phase artifact root must be a regular directory')


class PhaseArtifactBridge:
    """Append source-bound descriptors and immutable byte copies for one phase."""
    def __init__(self, context: PhaseArtifactContext, *, phase_root: Path, enabled: set[str]):
        if type(context) is not PhaseArtifactContext or not isinstance(phase_root, Path) or type(enabled) is not set or any(type(item) is not str for item in enabled):
            raise ContractError('typed M7/M8 artifact bridge required')
        self.context, self.phase_root, self.enabled = context, phase_root.resolve(), frozenset(enabled & {'M7', 'M8'})
        self.root = context.artifact_root.resolve()
        self.blobs = self.root / 'blobs'
        self._allocation: str | None = None
        self._programs: dict[str, str] = {}
        self._returns: dict[str, str] = {}
        self._sqlite: str | None = None
        self._last_event: str | None = None
        self._files: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    @property
    def source(self) -> dict:
        return source_snapshot(Path(__file__).with_name('exploration_scheduler_combination.py'))

    @property
    def bridge_source_ref(self) -> dict:
        body = source_snapshot(Path(__file__))
        return {'kind': 'phase_artifact_bridge_source', 'digest': FrozenRecord.from_dict(body).content_hash, 'canonical': body}

    def _relative(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.phase_root).as_posix()
        except ValueError as exc:
            raise ContractError('phase artifact escapes owned phase root') from exc

    def _blob(self, raw: bytes) -> FrozenRecord:
        digest = _digest(raw)
        self.blobs.mkdir(parents=True, exist_ok=True)
        target = self.blobs / digest
        if target.exists():
            if target.is_symlink() or _regular(target) != raw:
                raise ContractError('immutable phase blob collision or link')
        else:
            try:
                with target.open('xb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            except FileExistsError:
                if target.is_symlink() or _regular(target) != raw:
                    raise ContractError('immutable phase blob race differs')
        return FrozenRecord.from_dict({'schema': 'phase-artifact-bytes-v1', 'relative_path': None,
            'sha256': digest, 'byte_count': len(raw)})

    def _append(self, *, kind: str, module: str, status: str, path: Path, parents: tuple[str, ...], extra: dict | None = None,
                raw: bytes | None = None, relative_path: str | None = None) -> str:
        with self._lock:
            raw = _regular(path) if raw is None else raw; blob = self._blob(raw).data()
            blob['relative_path'] = self._relative(path) if relative_path is None else relative_path
            payload = {'schema': 'phase-artifact-witness-v1', 'kind': kind, 'bytes': blob, 'extra': extra or {}}
            record = self.context.catalogue.append(kind=kind, module=module, payload=payload, parents=parents,
                status=status, producer_source=self.source, config_refs=(self.bridge_source_ref,))
            self._files.append((blob['relative_path'], blob['sha256']))
            return record.content_hash

    def allocation(self, path: Path) -> None:
        if self._allocation is not None:
            raise ContractError('phase allocation witness duplicated')
        self._allocation = self._append(kind='phase_allocation', module='M7',
            status='produced' if 'M7' in self.enabled else 'not_applied', path=path,
            parents=tuple(self.context.parents.values()))

    def program(self, path: Path, job: str) -> None:
        if self._allocation is None or job in self._programs: raise ContractError('phase program lacks unique allocation witness')
        self._programs[job] = self._append(kind='phase_program', module='M7', status='produced' if 'M7' in self.enabled else 'not_applied',
            path=path, parents=(self._allocation,), extra={'job': job})

    def returned(self, path: Path, job: str) -> None:
        if self._allocation is None or job not in self._programs or job in self._returns: raise ContractError('phase return lacks unique program witness')
        self._returns[job] = self._append(kind='phase_return', module='M7', status='produced' if 'M7' in self.enabled else 'not_applied',
            path=path, parents=(self._allocation, self._programs[job]), extra={'job': job})

    def event(self, path: Path, row: dict) -> None:
        if self._allocation is None: raise ContractError('phase event lacks allocation witness')
        parents = (self._allocation,) if self._last_event is None else (self._allocation, self._last_event)
        self._last_event = self._append(kind='phase_scheduler_event', module='M8',
            status='produced' if 'M8' in self.enabled else 'not_applied', path=path, parents=parents,
            raw=(FrozenRecord.from_dict(row).encoded + '\n').encode('utf-8'),
            relative_path='events.jsonl#' + str(row.get('sequence')),
            extra={'sequence': row.get('sequence'), 'event': row})

    def sqlite_snapshot(self, path: Path) -> None:
        if 'M8' not in self.enabled or self._allocation is None or self._last_event is None:
            raise ContractError('SQLite witness requires an enabled completed scheduler phase')
        self._sqlite = self._append(kind='phase_scheduler_sqlite', module='M8', status='produced', path=path,
            parents=(self._allocation, self._last_event))

    def receipt(self, path: Path) -> None:
        if self._allocation is None or self._last_event is None or not self._returns:
            raise ContractError('phase receipt lacks durable prefix witnesses')
        receipt = FrozenRecord(_regular(path).decode('utf-8')).data()
        fifo = receipt.get('fifo_order')
        if not isinstance(fifo, list) or set(fifo) != set(self._returns):
            raise ContractError('phase receipt lacks exact returned FIFO jobs')
        parents = (self._allocation, *[self._returns[job] for job in fifo], self._last_event)
        if 'M8' in self.enabled:
            if self._sqlite is None: raise ContractError('M8 receipt lacks SQLite witness')
            parents += (self._sqlite,)
        self._append(kind='phase_receipt', module='M7', status='produced' if 'M7' in self.enabled else 'not_applied',
            path=path, parents=parents)


def verify_phase_artifacts(*, bridge: PhaseArtifactBridge, material, cell, objective, root: Path,
                           image: str, timeout_seconds: int, inputs: Mapping[str, Path], selected_job_id=None):
    """Re-read phase sources and exact blobs after the ordinary phase replay."""
    from research_loop.modular.exploration_scheduler_combination import verify_phase
    if type(bridge) is not PhaseArtifactBridge or Path(root).resolve() != bridge.phase_root:
        raise ContractError('phase artifact verifier requires the original bridge and root')
    report = verify_phase(material=material, cell=cell, objective=objective, root=root, image=image,
        timeout_seconds=timeout_seconds, inputs=inputs, selected_job_id=selected_job_id)
    bridge.context.catalogue.verify()
    all_records = {record.content_hash: record.data() for record in bridge.context.catalogue.records()}
    descriptors = [(digest, body) for digest, body in all_records.items() if body['kind'].startswith('phase_')]
    expected_paths = {'allocation.json', 'events.jsonl', 'receipt.json'}
    chosen = report.data()['fifo_order']
    expected_paths.update({job + suffix for job in chosen for suffix in ('.py', '.json')})
    if 'M8' in bridge.enabled: expected_paths.add('queue.sqlite')
    elif (Path(root) / 'queue.sqlite').exists(): raise ContractError('serial phase has SQLite source')
    source_paths = {p.relative_to(root).as_posix() for p in Path(root).iterdir() if p.is_file()}
    if source_paths != expected_paths: raise ContractError('phase source files do not have exact artifact coverage')
    expected: list[tuple[str, str, str]] = []
    expected_source = source_snapshot(Path(__file__).with_name('exploration_scheduler_combination.py'))
    expected_ref = {'kind': 'phase_artifact_bridge_source',
        'digest': FrozenRecord.from_dict(source_snapshot(Path(__file__))).content_hash,
        'canonical': source_snapshot(Path(__file__))}
    allocation = programs = returns = sqlite = receipt = None
    events: list[tuple[int, str, dict]] = []
    for digest, body in descriptors:
        _verify_witness_metadata(body)
        if body['producer_source'] != expected_source:
            raise ContractError('phase witness producer source differs')
        if body['config_refs'] != [expected_ref]: raise ContractError('phase witness bridge source differs')
        payload = body['payload']['canonical']
        if set(payload) != {'schema','kind','bytes','extra'} or payload['schema'] != 'phase-artifact-witness-v1' or payload['kind'] != body['kind']:
            raise ContractError('phase witness schema or kind differs')
        bytes_body = payload['bytes']; relative = bytes_body.get('relative_path')
        if payload['kind'] == 'phase_scheduler_event':
            sequence = payload['extra'].get('sequence')
            if type(sequence) is not int or sequence < 0: raise ContractError('phase event witness sequence differs')
            event_source = _regular(Path(root) / 'events.jsonl').splitlines(keepends=True)
            if relative != 'events.jsonl#' + str(sequence) or sequence >= len(event_source):
                raise ContractError('phase event witness path differs')
            raw = event_source[sequence]
            if payload['extra'].get('event') != FrozenRecord(raw.decode('utf-8').rstrip('\n')).data():
                raise ContractError('phase event witness body differs')
        else:
            if not isinstance(relative, str) or relative not in expected_paths: raise ContractError('phase witness path differs')
            raw = _regular(Path(root) / relative)
        expected_module = 'M8' if payload['kind'] in {'phase_scheduler_event', 'phase_scheduler_sqlite'} else 'M7'
        expected_status = 'produced' if expected_module in bridge.enabled else 'not_applied'
        if body['module'] != expected_module or body['status'] != expected_status:
            raise ContractError('phase witness module activation differs')
        if bytes_body != {'schema': 'phase-artifact-bytes-v1', 'relative_path': relative, 'sha256': _digest(raw), 'byte_count': len(raw)}:
            raise ContractError('phase witness differs from actual source bytes')
        blob = bridge.blobs / bytes_body['sha256']
        if _regular(blob) != raw: raise ContractError('phase immutable blob differs from source')
        expected.append((payload['kind'], relative, bytes_body['sha256']))
        if payload['kind'] == 'phase_allocation':
            if body['parents'] != list(bridge.context.parents.values()): raise ContractError('allocation parent graph differs')
            allocation = digest
        elif payload['kind'] == 'phase_program':
            if payload['extra'] != {'job': relative.removesuffix('.py')} or body['parents'] != [allocation]:
                raise ContractError('program parent or job binding differs')
            programs = (programs or {}) | {payload['extra']['job']: digest}
        elif payload['kind'] == 'phase_return':
            job = relative.removesuffix('.json')
            if payload['extra'] != {'job': job} or body['parents'] != [allocation, (programs or {}).get(job)]:
                raise ContractError('return parent or job binding differs')
            returns = (returns or {}) | {job: digest}
        elif payload['kind'] == 'phase_scheduler_event':
            events.append((payload['extra']['sequence'], digest, body))
        elif payload['kind'] == 'phase_scheduler_sqlite':
            sqlite = digest
        elif payload['kind'] == 'phase_receipt':
            receipt = digest
        else: raise ContractError('unknown phase witness kind')
    actual_event_lines = _regular(Path(root) / 'events.jsonl').splitlines(keepends=True)
    event_rows = [FrozenRecord(line.decode('utf-8').rstrip('\n')).data() for line in actual_event_lines]
    program_paths = {('phase_program', job + '.py') for job in chosen}
    return_paths = {('phase_return', job + '.json') for job in chosen}
    if (len([item for item in expected if item[0] == 'phase_allocation']) != 1 or len([item for item in expected if item[0] == 'phase_receipt']) != 1
            or len([item for item in expected if item[0] == 'phase_program']) != len(chosen)
            or len([item for item in expected if item[0] == 'phase_return']) != len(chosen)
            or {(kind,path) for kind,path,_ in expected if kind == 'phase_program'} != program_paths
            or {(kind,path) for kind,path,_ in expected if kind == 'phase_return'} != return_paths
            or len(programs or {}) != len(chosen) or len(returns or {}) != len(chosen)
            or (sqlite is not None) != ('M8' in bridge.enabled)):
        raise ContractError('phase program or return witnesses are not an exact bijection')
    if [sequence for sequence, _, _ in events] != list(range(len(event_rows))):
        raise ContractError('phase event witnesses are unordered, duplicated or incomplete')
    previous = None
    for sequence, digest, body in events:
        parents = [allocation] if previous is None else [allocation, previous]
        if body['parents'] != parents: raise ContractError('phase event parent chronology differs')
        previous = digest
    if sqlite is not None and (('M8' not in bridge.enabled) or all_records[sqlite]['parents'] != [allocation, previous]):
        raise ContractError('SQLite witness parent graph differs')
    expected_receipt_parents = [allocation, *[returns[job] for job in chosen], previous]
    if 'M8' in bridge.enabled: expected_receipt_parents.append(sqlite)
    if receipt is None or all_records[receipt]['parents'] != expected_receipt_parents:
        raise ContractError('phase receipt parent graph differs')
    if any((Path(root) / ('queue.sqlite' + suffix)).exists() for suffix in ('-wal', '-shm')):
        raise ContractError('sealed phase retains SQLite journal files')
    blobs = {p.name for p in bridge.blobs.iterdir() if p.is_file()} if bridge.blobs.exists() else set()
    referenced = {digest for _, _, digest in expected}
    if blobs != referenced or any(p.is_symlink() for p in bridge.blobs.iterdir()):
        raise ContractError('phase blob store has unreferenced or linked data')
    return report


def verify_phase_artifact_prefix(*, bridge: PhaseArtifactBridge) -> None:
    """Check durable witnesses left by an interrupted phase without claiming completion."""
    if type(bridge) is not PhaseArtifactBridge:
        raise ContractError('typed phase artifact prefix bridge required')
    bridge.context.catalogue.verify()
    expected_source = source_snapshot(Path(__file__).with_name('exploration_scheduler_combination.py'))
    expected_ref = {'kind': 'phase_artifact_bridge_source',
        'digest': FrozenRecord.from_dict(source_snapshot(Path(__file__))).content_hash,
        'canonical': source_snapshot(Path(__file__))}
    for descriptor in bridge.context.catalogue.records():
        body = descriptor.data()
        if not body['kind'].startswith('phase_'):
            continue
        _verify_witness_metadata(body)
        payload = body['payload']['canonical']
        expected_module = 'M8' if body['kind'] in {'phase_scheduler_event','phase_scheduler_sqlite'} else 'M7'
        expected_status = 'produced' if expected_module in bridge.enabled else 'not_applied'
        if (body['producer_source'] != expected_source or body['config_refs'] != [expected_ref]
                or body['module'] != expected_module or body['status'] != expected_status
                or set(payload) != {'schema','kind','bytes','extra'} or payload.get('schema') != 'phase-artifact-witness-v1'
                or payload.get('kind') != body['kind']):
            raise ContractError('phase prefix witness source or schema differs')
        item = payload['bytes']; relative = item.get('relative_path')
        if payload['kind'] == 'phase_scheduler_event':
            sequence = payload['extra'].get('sequence')
            lines = _regular(bridge.phase_root / 'events.jsonl').splitlines(keepends=True)
            if type(sequence) is not int or sequence < 0 or relative != 'events.jsonl#' + str(sequence) or sequence >= len(lines): raise ContractError('phase prefix event is absent')
            raw = lines[sequence]
        else:
            if (not isinstance(relative,str) or not relative or '/' in relative or '\\' in relative
                    or relative in {'.','..'} or Path(relative).name != relative):
                raise ContractError('phase prefix path escapes owned root')
            raw = _regular(bridge.phase_root / relative)
        if item != {'schema':'phase-artifact-bytes-v1','relative_path':relative,'sha256':_digest(raw),'byte_count':len(raw)} or _regular(bridge.blobs / item['sha256']) != raw:
            raise ContractError('phase prefix witness byte binding differs')
