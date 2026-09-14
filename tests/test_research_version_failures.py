"""Failure-path contracts for the Q8.6 durable research-version seam.

These tests intentionally exercise only the public boundary API.  They are
written before the repair implementation and must remain valid without test
access to production internals beyond injected filesystem failures.
"""
from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from research_loop.modular import research_versions
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.research_versions import ResearchVersionBoundary
from research_loop.ontology import ContractError
from test_research_version_artifacts import _authority, _authorization, _session


def _objective(question="new"):
    return FrozenRecord.from_dict({"question": question})


def _malformed(authorization, kind):
    body = authorization.data()
    if kind == "schema":
        body["schema"] = "untrusted-origin-authorization"
    elif kind == "receipt_subject":
        body["receipt"] = {"schema": "q8-origin-qualification-v1", "subject_digest": "0" * 64,
                           "caller_public_train_qualified": True, "scientific_verified": False}
    elif kind == "scientific_flag":
        body["receipt"]["scientific_verified"] = True
    elif kind == "descriptor":
        body["authority_artifact"] = "f" * 64
    elif kind == "objective":
        body["subject"]["request"]["proposed_objective"] = {"question": "different"}
    else:  # pragma: no cover - test author error
        raise AssertionError(kind)
    return FrozenRecord.from_dict(body)


@pytest.mark.parametrize("kind", ("schema", "receipt_subject", "scientific_flag", "descriptor", "objective"))
def test_malformed_origin_authorization_rejected_before_freeze_or_child(tmp_path, kind):
    session = _session(tmp_path)
    boundary = ResearchVersionBoundary(session)
    authorization = _malformed(_authorization(session), kind)
    calls = []
    authority = SimpleNamespace(freeze_version=lambda subject: calls.append(subject) or _authority(subject))
    with pytest.raises(ContractError):
        boundary.pause_and_freeze(_objective(), authority, authorization)
    assert calls == []
    assert not boundary.child_path.exists()
    assert boundary.child is None and boundary.state == "running"


def test_child_trace_failure_is_terminal_and_final_callback_is_never_called(tmp_path, monkeypatch):
    session = _session(tmp_path)
    boundary = ResearchVersionBoundary(session)
    authorization = _authorization(session)
    original = session._record
    def fail_child_trace(stage, data):
        if stage == "research_version_child_persisted":
            raise OSError("injected trace failure")
        return original(stage, data)
    monkeypatch.setattr(session, "_record", fail_child_trace)
    with pytest.raises(OSError, match="injected trace failure"):
        boundary.pause_and_freeze(_objective(), SimpleNamespace(freeze_version=_authority), authorization)
    assert session._terminal is True
    assert boundary.child_path.exists()  # published prefix is evidence, never silently removed
    called = []
    with pytest.raises(ContractError):
        session.invoke("final", lambda _: called.append(True), instruction="must not run", reporting_only=True)
    assert called == []


def test_parent_catalogue_failure_is_terminal_and_retains_parent(tmp_path, monkeypatch):
    session = _session(tmp_path)
    monkeypatch.setattr(session, "record_artifact", lambda **_: (_ for _ in ()).throw(OSError("catalogue failure")))
    with pytest.raises(OSError, match="catalogue failure"):
        ResearchVersionBoundary(session)
    assert session._terminal is True
    parent = tmp_path / "research-version-parent.json"
    assert parent.exists() and parent.read_bytes().endswith(b"\n")
    called = []
    with pytest.raises(ContractError):
        session.invoke("final", lambda _: called.append(True), instruction="must not run", reporting_only=True)
    assert called == []


def test_parent_publication_failure_retains_partial_and_marks_terminal(tmp_path, monkeypatch):
    session = _session(tmp_path)
    monkeypatch.setattr(research_versions.os, "link", lambda *_: (_ for _ in ()).throw(OSError("publish failure")))
    with pytest.raises(OSError, match="publish failure"):
        ResearchVersionBoundary(session)
    assert session._terminal is True
    assert not (tmp_path / "research-version-parent.json").exists()
    assert (tmp_path / "research-version-parent.json.partial").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics are required")
def test_ancestor_windows_junction_is_refused_before_any_parent_write(tmp_path):
    target = tmp_path / "target"; target.mkdir()
    link = tmp_path / "junction"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if made.returncode:
        pytest.skip("host cannot create isolated junction: " + made.stderr)
    assert link.is_junction()
    session = _session(link / "sidecar")
    with pytest.raises(ContractError, match="link or junction"):
        ResearchVersionBoundary(session)
    assert not (target / "sidecar" / "research-version-parent.json").exists()


def test_source_prefix_change_blocks_reporting_before_callback(tmp_path, monkeypatch):
    session = _session(tmp_path)
    boundary = ResearchVersionBoundary(session)
    # A changed recorded source snapshot is equivalent to a source-prefix drift;
    # do not modify the shared worktree merely to trigger this guard.
    original = research_versions.source_snapshot
    monkeypatch.setattr(research_versions, "source_snapshot", lambda path: {**original(path), "sha256": "0" * 64})
    called = []
    with pytest.raises(ContractError, match="source changed"):
        session.invoke("final", lambda _: called.append(True), instruction="must not run", reporting_only=True)
    assert called == []
    assert session._terminal is True
