"""Durable per-event M6 witnesses; no provider or model calls in readers."""
from __future__ import annotations

from pathlib import Path

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular import runtime as runtime_module
from research_loop.modular.modules import evidence as evidence_module
from research_loop.ontology import ContractError, canonical


def _is_retrieval(stage):
    return stage.startswith(('q8_', 'q84_')) or stage == 'retrieval_review_sources'


def _read_rows(path):
    if not path.is_file():
        raise ContractError('retrieval source journal is missing')
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ContractError('retrieval source journal has an incomplete final line')
    import json
    rows = []
    for line in raw.decode('utf-8').splitlines():
        row = json.loads(line)
        if not isinstance(row, dict) or canonical(row) != line:
            raise ContractError('retrieval source journal is not canonical')
        rows.append(row)
    return rows


def _assert_public(payload):
    if 'data/labels/' in FrozenRecord.from_dict(payload).encoded.replace('\\', '/'):
        raise ContractError('retrieval artifact would expose isolated labels')


class RetrievalArtifactBridge:
    """Observe each trace append, even when later work fails.

    Q8.4 also attaches source_ledger directly to its dedicated ledger. The
    common scientific evidence ledger and Q8.4 source ledger remain distinct.
    """
    def __init__(self, session):
        self.session = session
        self.previous = {'trace': None, 'source_ledger': None}
        self.indices = {'trace': 0, 'source_ledger': 0}
        self.sources = {'trace': source_snapshot(Path(runtime_module.__file__)),
                        'source_ledger': source_snapshot(Path(evidence_module.__file__))}
        self.bridge_source = source_snapshot(Path(__file__))

    def trace(self, event):
        if _is_retrieval(event.data()['stage']):
            self._append('trace', event)

    def source_ledger(self, event):
        self._append('source_ledger', event)

    def _append(self, stream, event):
        try:
            payload = _payload(stream, self.indices[stream], event.data(), self.session.arm.data()['enabled'],
                               self.sources[stream], self.bridge_source)
            _assert_public(payload)
            previous = self.previous[stream]
            descriptor = self.session.record_artifact(kind=_kind(stream), module='M6', payload=payload,
                parents=(() if previous is None else (previous,)),
                status='produced' if 'M6' in self.session.arm.data()['enabled'] else 'not_applied',
                producer_source=self.sources[stream])
            self.previous[stream] = descriptor.content_hash
            self.indices[stream] += 1
        except Exception:
            self.session._audit_failure()
            raise


def _kind(stream):
    return 'retrieval_event' if stream == 'trace' else 'q84_source_ledger_event'


def _payload(stream, index, event, enabled, source, bridge_source):
    return {'schema': 'm6-durable-event-artifact-v2', 'stream': stream, 'stream_index': index,
            'event': event, 'm2_enabled': 'M2' in enabled, 'm6_enabled': 'M6' in enabled,
            'module_source': source, 'bridge_source': bridge_source}


def _verify_stream(catalogue, *, rows, stream, enabled):
    descriptors = catalogue.records()
    wanted, latest_trace, previous, consumed = list(rows), None, None, 0
    source = source_snapshot(Path((runtime_module if stream == 'trace' else evidence_module).__file__))
    bridge_source = source_snapshot(Path(__file__))
    pending_trace = None
    for descriptor in descriptors:
        body = descriptor.data()
        if body['kind'] == 'trace_event':
            if stream == 'trace' and pending_trace is not None:
                raise ContractError('retrieval artifact was not recorded at its durable source event')
            latest_trace = descriptor.content_hash
            if stream == 'trace' and _is_retrieval(body['payload']['canonical']['stage']):
                pending_trace = body['payload']['canonical']
            continue
        if body['kind'] != _kind(stream):
            continue
        if consumed >= len(wanted) or latest_trace is None:
            raise ContractError('unexpected retrieval artifact or missing trace anchor')
        row = wanted[consumed]
        expected = _payload(stream, consumed, row, enabled, source, bridge_source)
        parents = ([] if previous is None else [previous]) + [latest_trace]
        if (body['module'] != 'M6' or body['payload']['canonical'] != expected
                or body['parents'] != parents or body['producer_source'] != source
                or body['status'] != ('produced' if 'M6' in enabled else 'not_applied')
                or stream == 'trace' and pending_trace != row):
            raise ContractError('retrieval artifact source, event, activation or causal parents differ')
        _assert_public(expected)
        pending_trace = None
        previous = descriptor.content_hash
        consumed += 1
    if consumed != len(wanted) or pending_trace is not None:
        raise ContractError('retrieval artifact coverage differs from durable source events')
    return consumed


def verify_retrieval_event_stream(catalogue, *, trace_path, task):
    """Check exact source correspondence; policy replay is a separate step."""
    try:
        catalogue.verify()
        rows = _read_rows(Path(trace_path))
        traces = [d.data()['payload']['canonical'] for d in catalogue.records() if d.data()['kind'] == 'trace_event']
        if rows != traces or not rows or rows[0]['stage'] != 'objective_lock':
            raise ContractError('retrieval stream lacks its original lock and trace')
        lock = rows[0]['data']
        if catalogue.identity != task.identity or lock['identity'] != task.identity.data() or lock['task_digest'] != task.content_hash:
            raise ContractError('retrieval stream subject differs')
        count = _verify_stream(catalogue, rows=[r for r in rows if _is_retrieval(r['stage'])],
                               stream='trace', enabled=lock['arm']['enabled'])
        return FrozenRecord.from_dict({'schema': 'm6-event-stream-check-v2', 'descriptor_count': count,
                                       'scientific_validated': False})
    except ContractError:
        raise
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise ContractError('malformed retrieval event cannot be replayed') from exc


def verify_retrieval_artifacts(catalogue, *, trace_path, task, material, enabled):
    from research_loop.modular.retrieval_review_combination_driver import _verify_sources
    result = verify_retrieval_event_stream(catalogue, trace_path=trace_path, task=task)
    rows = _read_rows(Path(trace_path))
    if type(enabled) is not bool or enabled != ('M6' in rows[0]['data']['arm']['enabled']):
        raise ContractError('retrieval replay activation differs from the original lock')
    start = next((i for i, row in enumerate(rows) if row['stage'] == 'q8_source_admission'), None)
    # Earlier C4 critiques are legal. Later calls remain in scope so failed
    # retrieval cannot authorize them.
    projection = _verify_sources(rows[start:] if start is not None else rows, task, material, enabled)
    return FrozenRecord.from_dict({'schema': 'm6-retrieval-artifacts-verified-v2',
        'descriptor_count': result.data()['descriptor_count'],
        'projection_digest': FrozenRecord.from_dict(projection).content_hash if projection else None,
        'scientific_effect': 'not_measured'})


def verify_q84_source_ledger_artifacts(catalogue, *, ledger_path, task, m2_enabled, m6_enabled):
    ledger_path = Path(ledger_path)
    rows = _read_rows(ledger_path)
    # Check existence before the public reader's writable initialization mode.
    ledger = EvidenceLedger(task.identity, storage_path=ledger_path)
    traces = [d.data()['payload']['canonical'] for d in catalogue.records() if d.data()['kind'] == 'trace_event']
    if not traces or traces[0]['stage'] != 'objective_lock' or traces[0]['data']['identity'] != task.identity.data():
        raise ContractError('Q8.4 source ledger lacks its subject lock')
    enabled = traces[0]['data']['arm']['enabled']
    if type(m2_enabled) is not bool or type(m6_enabled) is not bool or m2_enabled != ('M2' in enabled) or m6_enabled != ('M6' in enabled):
        raise ContractError('Q8.4 source ledger activation differs')
    catalogue.verify()
    count = _verify_stream(catalogue, rows=rows, stream='source_ledger', enabled=enabled)
    return FrozenRecord.from_dict({'schema': 'q84-source-ledger-artifacts-verified-v2',
        'descriptor_count': count, 'ledger_version': ledger.version, 'scientific_effect': 'not_measured'})
