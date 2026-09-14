"""Q3.2 actual writer/consumer provenance, without granting scientific authority."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.m4_m5_artifacts import M4M5ArtifactBridge
from research_loop.modular.modules import predictions as prediction_module
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.ontology import ContractError, canonical, digest


STAGES = frozenset({'q32_plans_frozen', 'q32_public_request', 'q32_execution_seal',
    'q32_execution_binding', 'q32_observation', 'q32_comparison_ready',
    'q32_phase_failure', 'q32_phase_result'})
CLOSURE = 'q32-artifacts-seal.json'


def plain(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ContractError('Q3.2 artifact path traverses a link')
    return path


def inventory(root: Path) -> dict:
    """Literal bytes only; no callback, execution, or scientific acceptance."""
    root = plain(root)
    rows = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            plain(Path(directory) / name)
        for name in names:
            path = plain(Path(directory) / name)
            if path == root / CLOSURE:
                continue
            raw = path.read_bytes()
            rows[path.relative_to(root).as_posix()] = {
                'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return dict(sorted(rows.items()))


def write_new(path: Path, record: FrozenRecord) -> None:
    with plain(path).open('xb') as stream:
        stream.write((record.encoded + '\n').encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())


def _rows(path: Path) -> list[dict]:
    raw = plain(path).read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ContractError('Q3.2 artifact journal has an incomplete tail')
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    if raw != ''.join(canonical(row) + '\n' for row in rows).encode('utf-8'):
        raise ContractError('Q3.2 artifact journal is not canonical')
    return rows


def _parents(stage: str, data: dict, plans: list[str], saved: dict) -> list[str]:
    if stage == 'q32_plans_frozen':
        return plans
    if stage == 'q32_execution_seal':
        return [saved['q32_plans_frozen'], *saved.get('responses', [])]
    if stage == 'q32_execution_binding':
        return [saved['q32_execution_seal']]
    if stage == 'q32_observation':
        return [saved['q32_execution_binding'], saved['execution_result']]
    if stage == 'q32_comparison_ready':
        return [saved['q32_execution_seal'], *saved.get('observations', [])]
    if stage == 'q32_phase_result':
        return [saved['q32_plans_frozen'], *saved.get('observations', []), saved['final_decision']]
    return [saved['q32_plans_frozen']]


def _remember(saved: dict, stage: str, descriptor: str) -> None:
    saved[stage] = descriptor
    if stage == 'model_response':
        saved.setdefault('responses', []).append(descriptor)
    if stage == 'q32_observation':
        saved.setdefault('observations', []).append(descriptor)


class Q32ArtifactBridge:
    def __init__(self, session, compiled: FrozenRecord, cell: dict):
        self.session, self.compiled, self.cell = session, compiled, cell
        self._original_audit_failure = session._audit_failure
        session._audit_failure = self.fail
        self.predictions = M4M5ArtifactBridge(session)
        self.source = source_snapshot(Path(__file__).with_name('q32_execution.py'))

    def fail(self):
        self.session._terminal = True
        try:
            plain(self.session.sidecar / 'audit-failure.json')
            self._original_audit_failure()
        except (OSError, ContractError):
            # Do not follow a substituted directory to record its own rejection.
            pass

    def record(self, stage: str, data: dict):
        try:
            self.session._record(stage, data)
            records = self.session.artifacts.records()
            plans, saved = [], {}
            for item in records:
                row = item.data()
                value = row['payload']['canonical']
                if row['kind'] == 'journal_event' and row['module'] == 'M4':
                    plans.append(item.content_hash)
                elif row['kind'] == 'trace_event' and value['stage'] not in STAGES:
                    _remember(saved, value['stage'], item.content_hash)
                elif row['kind'] == 'q32_output':
                    _remember(saved, value['stage'], item.content_hash)
            # The current generic trace is an enclosing transaction anchor.
            # Previous q32 outputs and actual responses carry the typed edges.
            self.session.record_artifact(kind='q32_output', module='M4',
                payload={'schema': 'q32-output-artifact-v1', 'stage': stage,
                    'trace_sequence': len(self.session._events) - 1, 'data': data},
                parents=tuple(_parents(stage, data, plans, saved)),
                status='failed' if stage == 'q32_phase_failure' else 'produced',
                producer_source=self.source)
        except Exception:
            self.session._audit_failure()
            raise

    def check(self):
        try:
            return verify_q32_artifacts(self.session.sidecar, self.compiled,
                cell=self.cell, complete=False, run_id=self.session.artifacts.binding['run_id'])
        except Exception:
            self.session._audit_failure()
            raise

    def close(self):
        self.check()
        self.session.artifacts.seal()
        write_new(self.session.sidecar / CLOSURE, FrozenRecord.from_dict({
            'schema': 'q32-artifact-closure-v1', 'compiled_digest': self.compiled.content_hash,
            'cell': self.cell, 'binding': self.session.artifacts.binding,
            'files': inventory(self.session.sidecar), 'scientific_validated': False}))


def verify_q32_artifacts(sidecar: Path, compiled: FrozenRecord, *, cell: dict,
                         complete: bool = True, run_id: str | None = None) -> FrozenRecord:
    """Read disk before real consumption; never touch replay logs or invoke I/O ports."""
    try:
        return _verify(sidecar, compiled, cell=cell, complete=complete, run_id=run_id)
    except ContractError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise ContractError('Q3.2 artifacts are incomplete or malformed') from exc


def _verify(sidecar, compiled, *, cell, complete, run_id):
    if type(compiled) is not FrozenRecord or type(cell) is not dict or type(complete) is not bool:
        raise ContractError('Q3.2 artifact verifier requires typed frozen controls')
    root = plain(sidecar)
    current_files = inventory(root)
    if 'audit-failure.json' in current_files:
        raise ContractError('Q3.2 audit failure cannot authorize further consumption')
    body = compiled.data()
    if cell not in body['cells']:
        raise ContractError('Q3.2 artifact cell is outside frozen compilation')
    task = body['tasks'][cell['task_digest']]
    identity = DataIdentity.parse(task['task']['identity']); identity.require_train()
    events = _rows(root / 'trace.jsonl')
    lock = events[0]['data']
    if (events[0]['stage'] != 'objective_lock' or lock['identity'] != identity.data()
            or lock['task_digest'] != cell['task_digest'] or lock['package_digest'] != compiled.content_hash
            or lock['arm']['enabled'] != ['M4'] or lock['slots'] != ['program_1', 'program_2', 'program_3', 'final']
            or lock['execution_limit'] != 3):
        raise ContractError('Q3.2 artifact lock differs from its actual task/compilation')
    entries = _rows(root / 'artifacts.jsonl')
    binding = entries[0]['descriptor']['binding']
    if (binding['lock_digest'] != digest(lock) or binding['experiment_id'] is not None
            or not isinstance(binding['run_id'], str) or len(binding['run_id']) != 32
            or any(c not in '0123456789abcdef' for c in binding['run_id'])
            or run_id is not None and binding['run_id'] != run_id):
        raise ContractError('Q3.2 artifact run binding differs')
    catalogue = ArtifactCatalogue(root / 'artifacts.jsonl', identity=identity,
        run_id=binding['run_id'], experiment_id=binding['experiment_id'], lock_digest=digest(lock))
    records = catalogue.records()
    if [r.data()['payload']['canonical'] for r in records if r.data()['kind'] == 'trace_event'] != events:
        raise ContractError('Q3.2 trace and artifact journal differ')
    previous = None
    for i, event in enumerate(events):
        if set(event) != {'sequence', 'previous', 'lock_digest', 'stage', 'data'} or type(event['sequence']) is not int or event['sequence'] != i or event['previous'] != previous or event['lock_digest'] != digest(lock):
            raise ContractError('Q3.2 trace transaction order differs')
        previous = digest(event)
    executions = [e for e in events if e['stage'] == 'execution_request']
    allowed = {'trace.jsonl', 'artifacts.jsonl', 'predictions.jsonl', 'evidence.jsonl', 'claims.jsonl'}
    allowed.update(f'analysis-{i + 1}.py' for i in range(len(executions)))
    allowed.update(name for name in ('execution-seal.json', 'result.json', 'artifacts.jsonl.seal.json') if (root / name).exists())
    if set(current_files) != allowed or any(plain(root / name).read_bytes() for name in ('evidence.jsonl', 'claims.jsonl')):
        raise ContractError('Q3.2 has an unregistered file or unexpected evidence ledger')
    for i, event in enumerate(executions):
        if current_files[f'analysis-{i + 1}.py']['sha256'] != event['data']['program_sha256']:
            raise ContractError('Q3.2 actual program bytes differ from the execution request')
    from research_loop.modular.evidence_artifacts import verify_evidence_artifacts
    from research_loop.modular.context_artifact import verify_session_context_artifacts
    evidence = verify_evidence_artifacts(catalogue, root).data()
    snapshots = {key: {'evidence': FrozenRecord.from_dict(value['evidence_snapshot']),
        'claims': FrozenRecord.from_dict(value['claims_snapshot'])} for key, value in evidence['model_inputs'].items()}
    verify_session_context_artifacts(task=PublicTask.create(identity, task['task']['payload']),
        lock=FrozenRecord.from_dict(lock), events=events, catalogue=catalogue, invocation_snapshots=snapshots)
    expected_plans = [task['plans'][0]] if cell['variant'] == 'joint' else task['plans'][1:]
    journal = _rows(root / 'predictions.jsonl')
    registry = PredictionRegistry(identity)
    for item in journal:
        registry._apply(item, persist=False)
    expected_journal = [{'event': 'freeze', 'identity': identity.data(), **{key: plan[key]
        for key in ('plan_id', 'question', 'branches', 'budget_units')}} for plan in expected_plans]
    if journal != expected_journal:
        raise ContractError('Q3.2 prediction journal differs from original frozen plans')
    plan_ids, saved, consumed, pending, latest = [], {}, [], None, None
    source = source_snapshot(Path(__file__).with_name('q32_execution.py'))
    prediction_source = source_snapshot(Path(prediction_module.__file__))
    bridge_source = source_snapshot(Path(__file__).with_name('m4_m5_artifacts.py'))
    for item in records:
        row = item.data(); value = row['payload']['canonical']
        if (row['kind'], row['module']) not in {('trace_event', None), ('trace_event', 'P0'),
                ('journal_event', 'M4'), ('q32_output', 'M4'), ('model_context', 'M3')}:
            raise ContractError('Q3.2 has an unregistered module output')
        if row['kind'] == 'trace_event':
            if pending is not None:
                raise ContractError('Q3.2 output was not registered before the next trace')
            if row['parents'] != ([] if latest is None else [latest]):
                raise ContractError('Q3.2 trace parent differs')
            latest = item.content_hash
            if value['stage'] not in STAGES:
                _remember(saved, value['stage'], latest)
            if value['stage'] in STAGES:
                pending = value
            continue
        if row['kind'] == 'journal_event' and row['module'] == 'M4':
            index = len(plan_ids)
            if pending is not None or 'q32_plans_frozen' in saved or index >= len(journal):
                raise ContractError('Q3.2 prediction produced after consumption or outside allocation')
            expected = {'schema': 'm4-m5-journal-artifact-v1', 'journal': 'predictions',
                'journal_index': index, 'event': journal[index], 'module_enabled': True,
                'module_source': prediction_source, 'bridge_source': bridge_source}
            if value != expected or row['parents'] != [latest] or row['producer_source'] != prediction_source or row['status'] != 'produced':
                raise ContractError('Q3.2 prediction descriptor differs from its actual writer')
            plan_ids.append(item.content_hash)
        elif row['kind'] == 'q32_output':
            if pending is None:
                raise ContractError('Q3.2 output lacks its actual preceding trace')
            stage, data = pending['stage'], pending['data']
            expected = {'schema': 'q32-output-artifact-v1', 'stage': stage,
                'trace_sequence': pending['sequence'], 'data': data}
            if (value != expected or row['module'] != 'M4' or row['producer_source'] != source
                    or row['parents'] != [*_parents(stage, data, plan_ids, saved), latest]
                    or row['status'] != ('failed' if stage == 'q32_phase_failure' else 'produced')):
                raise ContractError('Q3.2 output source, value, status or dependency differs')
            if stage == 'q32_plans_frozen' and (len(plan_ids) != len(journal) or data['compiled'] != body
                    or data['compiled_digest'] != compiled.content_hash or data['cell'] != cell
                    or data['plans'] != ([task['plans'][0]] * 3 if cell['variant'] == 'joint' else expected_plans)
                    or data['input_artifact'] != task['input_artifact']):
                raise ContractError('Q3.2 actual plans do not bind the independent compilation')
            _remember(saved, stage, item.content_hash)
            consumed.append(pending); pending = None
    if pending is not None or len(plan_ids) != len(journal) or 'q32_plans_frozen' not in saved:
        raise ContractError('Q3.2 output registration is incomplete')
    if 'q32_phase_result' in saved and events[-1]['stage'] != 'q32_phase_result':
        raise ContractError('Q3.2 has events after its final output')
    for stage, name in (('q32_execution_seal', 'execution-seal.json'), ('q32_phase_result', 'result.json')):
        matches = [e for e in consumed if e['stage'] == stage]
        if len(matches) > 1 or bool(matches) != ((root / name).exists()):
            raise ContractError('Q3.2 durable output is missing or unaccounted')
        if matches and plain(root / name).read_bytes() != (canonical(matches[0]['data']) + '\n').encode():
            raise ContractError('Q3.2 durable output seal or result differs from its registered original')
    if complete:
        if not consumed or consumed[-1]['stage'] != 'q32_phase_result' or not catalogue.seal_path.is_file():
            raise ContractError('Q3.2 complete artifact closure is missing')
        expected = {'schema': 'q32-artifact-closure-v1', 'compiled_digest': compiled.content_hash,
            'cell': cell, 'binding': binding, 'files': current_files, 'scientific_validated': False}
        if plain(root / CLOSURE).read_bytes() != (canonical(expected) + '\n').encode():
            raise ContractError('Q3.2 original output inventory or closure differs')
    return FrozenRecord.from_dict({'schema': 'q32-artifact-check-v1', 'complete': complete,
        'binding': binding, 'prediction_events': len(journal), 'outputs': len(consumed),
        'scientific_validated': False})
