"""Per-output M6 provenance derived from durable retrieval journals.

This bridge never calls a provider or model.  Producers append descriptors only
after the trace/ledger write has completed; readers reconstruct the original
selection with the existing retrieval verifier before trusting the catalogue.
"""
from __future__ import annotations

from pathlib import Path

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.lineage_combination_driver import _read_events
from research_loop.modular.modules.evidence import EvidenceLedger
from research_loop.modular.retrieval_review_combination_driver import _verify_sources
from research_loop.ontology import ContractError

_STAGES = frozenset({
    'q8_source_admission', 'q8_retrieval_request', 'q8_retrieval_item',
    'q8_retrieval_result', 'q8_retrieval_failure', 'q8_retrieval_selection',
    'q8_retrieval_budget', 'retrieval_review_sources',
})


def _activation(enabled: bool) -> str:
    return 'applied' if enabled else 'not_applied'


def _assert_public(value) -> None:
    # Labels must remain in the isolated scorer tree and never enter retrieval
    # descriptors, even when a caller accidentally places a path in a source.
    if 'data/labels/' in FrozenRecord.from_dict({'value': value}).encoded.replace('\\', '/'):
        raise ContractError('retrieval artifact would expose isolated labels')


def _retrieval_events(trace_path: Path):
    rows = _read_events(trace_path)
    return rows, [(index, row) for index, row in enumerate(rows) if row['stage'] in _STAGES]

def _replay_scope(rows):
    """Keep earlier C4 model calls out, but retain post-retrieval calls.

    A failure followed by a model call must still be rejected by _verify_sources.
    """
    start = next((index for index, row in enumerate(rows) if row['stage'] == 'q8_source_admission'), None)
    return rows[start:] if start is not None else rows


def append_retrieval_artifacts(catalogue: ArtifactCatalogue, *, trace_path: Path, task: PublicTask,
                               material: FrozenRecord, enabled: bool) -> tuple[FrozenRecord, ...]:
    """Append one M6 descriptor per fsynced source event, in trace order."""
    if type(catalogue) is not ArtifactCatalogue or not isinstance(task, PublicTask) or type(material) is not FrozenRecord or type(enabled) is not bool:
        raise ContractError('exact catalogue, task, material and activation required')
    rows, events = _retrieval_events(Path(trace_path))
    # Independent replay catches substitution, missing/extra events, and a
    # provider failure that improperly reaches model I/O before we append.
    _verify_sources(_replay_scope(rows), task, material, enabled)
    source = source_snapshot(Path(__file__)); parents = [] ; out = []
    for index, row in events:
        payload = {'schema': 'm6-retrieval-event-v1', 'trace_index': index,
                   'event': row, 'activation': _activation(enabled)}
        _assert_public(payload)
        status = 'produced' if enabled else 'not_applied'
        descriptor = catalogue.append(kind='m6_'+row['stage'], module='M6', payload=payload,
            parents=parents, status=status, producer_source=source,
            cost={'known': False, 'units': None})
        parents = [descriptor.content_hash]; out.append(descriptor)
    return tuple(out)


def verify_retrieval_artifacts(catalogue: ArtifactCatalogue, *, trace_path: Path, task: PublicTask,
                               material: FrozenRecord, enabled: bool) -> FrozenRecord:
    """Independently replay M6 and require exact descriptor correspondence."""
    if type(catalogue) is not ArtifactCatalogue:
        raise ContractError('exact retrieval artifact catalogue required')
    rows, events = _retrieval_events(Path(trace_path)); projection = _verify_sources(_replay_scope(rows), task, material, enabled)
    expected = []
    for index, row in events:
        expected.append({'schema': 'm6-retrieval-event-v1', 'trace_index': index,
                         'event': row, 'activation': _activation(enabled)})
    actual = [d.data() for d in catalogue.records() if d.data()['kind'].startswith('m6_q8_') or d.data()['kind'] == 'm6_retrieval_review_sources']
    if len(actual) != len(expected):
        raise ContractError('M6 descriptor count differs from durable retrieval events')
    for descriptor, payload in zip(actual, expected, strict=True):
        if (descriptor['module'] != 'M6' or descriptor['status'] != ('produced' if enabled else 'not_applied')
                or descriptor['payload']['canonical'] != payload):
            raise ContractError('M6 descriptor differs from durable retrieval event')
        _assert_public(payload)
    return FrozenRecord.from_dict({'schema': 'm6-retrieval-artifacts-verified-v1',
        'descriptor_count': len(actual), 'projection_digest': FrozenRecord.from_dict(projection).content_hash if projection else None,
        'activation': _activation(enabled), 'scientific_effect': 'not_measured'})


def append_q84_source_ledger_artifacts(catalogue: ArtifactCatalogue, *, ledger_path: Path,
                                       task: PublicTask, m2_enabled: bool, m6_enabled: bool) -> tuple[FrozenRecord, ...]:
    """Persist every Q8.4 source-ledger append with its own file snapshot."""
    if type(catalogue) is not ArtifactCatalogue or type(m2_enabled) is not bool or type(m6_enabled) is not bool:
        raise ContractError('exact Q8.4 ledger inputs required')
    ledger_path = Path(ledger_path)
    if not ledger_path.is_file(): raise ContractError('Q8.4 source ledger is missing')
    ledger = EvidenceLedger(task.identity, storage_path=ledger_path)
    rows = _read_events(ledger_path); source = source_snapshot(ledger_path)
    parents = []; out = []
    for index, row in enumerate(rows):
        payload = {'schema': 'q84-source-ledger-event-v1', 'ledger_index': index, 'event': row,
                   'm2_activation': _activation(m2_enabled), 'm6_activation': _activation(m6_enabled),
                   'ledger_version': ledger.version}
        _assert_public(payload)
        descriptor = catalogue.append(kind='m6_q84_source_ledger_append', module='M6', payload=payload,
            parents=parents, status='produced' if m6_enabled else 'not_applied', producer_source=source_snapshot(Path(__file__)),
            cost={'known': False, 'units': None})
        parents = [descriptor.content_hash]; out.append(descriptor)
    return tuple(out)


def verify_q84_source_ledger_artifacts(catalogue: ArtifactCatalogue, *, ledger_path: Path,
                                       task: PublicTask, m2_enabled: bool, m6_enabled: bool) -> FrozenRecord:
    ledger_path = Path(ledger_path)
    if not ledger_path.is_file(): raise ContractError('Q8.4 source ledger is missing')
    ledger = EvidenceLedger(task.identity, storage_path=ledger_path)
    rows = _read_events(ledger_path)
    actual = [d.data() for d in catalogue.records() if d.data()['kind'] == 'm6_q84_source_ledger_append']
    if len(actual) != len(rows):
        raise ContractError('Q8.4 source-ledger descriptor count differs from ledger')
    for index, (descriptor, row) in enumerate(zip(actual, rows, strict=True)):
        payload = {'schema': 'q84-source-ledger-event-v1', 'ledger_index': index, 'event': row,
                   'm2_activation': _activation(m2_enabled), 'm6_activation': _activation(m6_enabled),
                   'ledger_version': ledger.version}
        if (descriptor['status'] != ('produced' if m6_enabled else 'not_applied')
                or descriptor['payload']['canonical'] != payload):
            raise ContractError('Q8.4 source-ledger descriptor differs from persisted ledger')
        _assert_public(payload)
    return FrozenRecord.from_dict({'schema': 'q84-source-ledger-artifacts-verified-v1',
        'descriptor_count': len(actual), 'ledger_version': ledger.version,
        'scientific_effect': 'not_measured'})
