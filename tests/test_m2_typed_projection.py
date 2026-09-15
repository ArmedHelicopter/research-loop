import pytest

from pathlib import Path

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular import evidence_artifacts
from research_loop.modular.evidence_relation_projection import (
    project_m2_typed_edges,
    query_m2_withdrawal_observations,
)
from research_loop.ontology import ContractError
from test_evidence_artifacts import history, rewrite_catalogue


def _files(session):
    paths = (session.artifacts.path, session.artifacts.seal_path, session.sidecar / 'trace.jsonl',
             session.sidecar / 'evidence.jsonl', session.sidecar / 'claims.jsonl')
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def test_actual_m2_withdrawal_projection_is_readonly_and_observational(tmp_path):
    session = history(tmp_path / 'actual-withdrawal')
    seal = session.artifacts.seal()
    before = _files(session)
    projection = project_m2_typed_edges(session.artifacts, session.sidecar, seal=seal)
    body = projection.data()
    assert body['semantic_replay_source'] == source_snapshot(
        Path(__file__).parents[1] / 'research_loop/modular/evidence_artifacts.py')
    withdrawal = next(row['descriptor_digest'] for row in body['nodes'] if row['event'] == 'withdraw')
    assert any(edge['relation'] == 'withdraws' and edge['from_descriptor_digest'] == withdrawal for edge in body['edges'])
    observed = query_m2_withdrawal_observations(withdrawal, ((session.artifacts, session.sidecar, seal),)).data()
    assert observed['complete'] is False and observed['unknown_scope'] is True
    assert observed['withdrawn_roots']
    assert observed['observed'] and all(row['event'] == 'withdrawal_refresh' for row in observed['observed'])
    assert all(row['status'] == 'produced' and row['module_enabled'] is True for row in observed['observed'])
    assert all(row['needs_review'] is True for row in observed['observed'])
    assert _files(session) == before


def test_projection_rejects_rehashed_m2_relation_forgery(tmp_path):
    session = history(tmp_path / 'rehashed-relation')
    def mutate(rows):
        ledger = next(row['descriptor'] for row in rows if row['descriptor']['kind'] == 'ledger_event'
                      and row['descriptor']['payload']['canonical']['event']['event'] == 'withdraw')
        ledger['payload']['canonical']['relations'][0]['relation'] = 'consumes'
    rewrite_catalogue(session, mutate)
    seal = session.artifacts.seal()
    with pytest.raises(ContractError):
        project_m2_typed_edges(session.artifacts, session.sidecar, seal=seal)


def test_projection_rejects_resealed_catalogue_changed_during_replay(tmp_path, monkeypatch):
    session = history(tmp_path / 'changed-during-replay')
    seal = session.artifacts.seal()
    verify = evidence_artifacts.verify_evidence_artifacts

    def change_after_verified(catalogue, sidecar):
        checked = verify(catalogue, sidecar)
        catalogue.seal_path.unlink()
        def mutate(rows):
            ledger = next(row['descriptor'] for row in rows if row['descriptor']['kind'] == 'ledger_event')
            ledger['payload']['canonical']['output']['needs_review'] = True
        rewrite_catalogue(session, mutate)
        catalogue.seal()
        return checked

    monkeypatch.setattr(evidence_artifacts, 'verify_evidence_artifacts', change_after_verified)
    with pytest.raises(ContractError, match='changed during semantic replay|seal does not bind'):
        project_m2_typed_edges(session.artifacts, session.sidecar, seal=seal)
