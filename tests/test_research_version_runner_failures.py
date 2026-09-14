"""Actual Q8.6 runner failure and visibility boundaries, with synthetic ports."""
from types import SimpleNamespace
import os
import subprocess

import pytest

from research_loop.modular import research_versions
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError
from test_modular_retrieval_panel_drivers import _task, admission
from test_modular_q85_q86_q87_train_controller import bundle, Provider, response
from test_research_version_artifacts import _authority, _authorization, _session


def _case(tmp_path, *, context_bytes=4096):
    task = _task("blade")
    csv = tmp_path / "public.csv"; csv.write_bytes(b"x,y\r\n1,2\r\n")
    material = bundle(SimpleNamespace(task=task, csv_path=csv)).data()
    material["budget"]["context_bytes"] = context_bytes
    if context_bytes == 1024:
        next(doc for doc in material["sources"] if doc["source_id"] == "method")["text"]["text"] += " public text" * 500
    material = FrozenRecord.from_dict(material)
    scenario = FrozenRecord.from_dict({"experiment_id": "Q8.6", "variant": "pause_new_version",
        "controller_input": {"schema": "retrieval-final-controller-v1", "bundle": material.data()},
        "base": {"task": task.content_hash, "evidence": material.content_hash, "budget": "a" * 64},
        "controls": {"same_task": True, "same_evidence": True, "same_budget": True}})
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]),
        changes={"prompt": {"instructions": "public train package"}}, search_cost=0)
    arm = default_compatibility("a" * 64).arm(("M1", "M6"))
    cell = PanelCell("Q8.6", task.identity, "r1", "pause_new_version", "joint", arm,
        task.content_hash, scenario.content_hash, package.digest, "a" * 64)
    calls = []
    authority = SimpleNamespace(qualify_origin=lambda subject: FrozenRecord.from_dict({"schema": "q8-origin-qualification-v1",
        "subject_digest": subject.content_hash, "caller_public_train_qualified": True, "scientific_verified": False}), freeze_version=_authority)
    return cell, scenario, calls, dict(task=task, scenario=scenario, package=package,
        objective=FrozenRecord.from_dict({"question": "fixed"}), sidecar=tmp_path / "runtime",
        model=lambda request: calls.append(request.data()["slot"]) or response(request),
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), retrieval_provider=Provider(),
        retrieval_admission_port=admission, retrieval_final_authority=authority)


@pytest.mark.parametrize("fault", ("seal", "consumer", "origin", "child_catalogue"))
def test_actual_runner_retains_failed_attempt_and_never_returns_success(tmp_path, monkeypatch, fault):
    cell, scenario, calls, kwargs = _case(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("injected " + fault)
    if fault == "seal":
        monkeypatch.setattr(ArtifactCatalogue, "seal", fail)
    elif fault == "consumer":
        monkeypatch.setattr(research_versions, "verify_research_version_artifacts", fail)
    elif fault == "origin":
        kwargs["retrieval_final_authority"].qualify_origin = fail
    else:
        original = ArtifactCatalogue.append
        def append(self, **args):
            if args["kind"] == "research_version_child":
                return fail()
            return original(self, **args)
        monkeypatch.setattr(ArtifactCatalogue, "append", append)
    result = run_train_cell(cell, **kwargs)
    assert result.runtime.status == "failed" and result.runtime.output_digest is None and result.scorer is None
    assert calls == ([] if fault == "origin" else ["review"] if fault == "child_catalogue" else ["review", "final"])
    sidecar = result.runtime.trace_path.parent
    assert (sidecar / "research-version-failure.json").is_file()
    events = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
    if fault in {"seal", "consumer"}:
        assert events[-1]["stage"] == "final_decision"  # Original final decision is retained, not rewritten.
    if fault == "origin":
        assert any(row["stage"] == "research_version_origin_failure" for row in events)
    if fault == "child_catalogue":
        assert (sidecar / "research-version-child.json").is_file()
    monkeypatch.undo()
    PanelReceiptVerifier()._verify_runtime(result.runtime, cell, scenario=scenario)
    with pytest.raises(ContractError):
        research_versions.verify_research_version_artifacts(sidecar, cell=cell, scenario=scenario,
            identity=cell.identity, task_digest=cell.task_digest, lock=events[0]["data"], events=tuple(events))


@pytest.mark.parametrize("mode", ("empty", "missing_request", "context_exclusion"))
def test_m6_enabled_does_not_imply_new_version_request_is_visible(tmp_path, mode):
    cell, scenario, calls, kwargs = _case(tmp_path, context_bytes=1024 if mode == "context_exclusion" else 4096)
    if mode != "context_exclusion":
        kwargs["retrieval_provider"] = SimpleNamespace(search=lambda **kw: iter(
            [] if mode == "empty" else [doc for doc in kw["source_bundle"].documents if doc.lane == kw["lane"] and doc.source_id != "method"][:1]))
    result = run_train_cell(cell, **kwargs)
    assert result.runtime.status == "succeeded", result.runtime.failure_reason
    assert calls == ["review", "final"]
    events = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
    origin = next(row["data"]["subject"] for row in events if row["stage"] == "q86_source_authority")
    assert origin["request"] is None
    assert not (result.runtime.trace_path.parent / "research-version-child.json").exists()
    PanelReceiptVerifier()._verify_runtime(result.runtime, cell, scenario=scenario)


def test_raw_invalid_freeze_receipt_is_retained_and_reporting_is_terminal(tmp_path):
    session = _session(tmp_path)
    boundary = research_versions.ResearchVersionBoundary(session)
    invalid = FrozenRecord.from_dict({"authorized": True, "unqualified": "literal returned material"})
    with pytest.raises(ContractError, match="independent authorization"):
        boundary.pause_and_freeze(FrozenRecord.from_dict({"question": "new"}),
            SimpleNamespace(freeze_version=lambda _: invalid), _authorization(session))
    results = [row.data()["data"] for row in session._events if row.data()["stage"] == "research_version_freeze_result"]
    assert results[0]["receipt"] == invalid.data() and session._terminal
    called = []
    with pytest.raises(ContractError):
        session.invoke("final", lambda _: called.append(True), instruction="Report", reporting_only=True)
    assert called == [] and not boundary.child_path.exists()


def test_coherently_rehashed_live_journal_is_rejected_before_reporting(tmp_path):
    session = _session(tmp_path)
    boundary = research_versions.ResearchVersionBoundary(session)
    path = tmp_path / "trace.jsonl"
    rows = [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["data"]["reason"] = "rewritten"
    path.write_bytes(("\n".join(FrozenRecord.from_dict(row).encoded for row in rows) + "\n").encode())
    called = []
    with pytest.raises(ContractError, match="prefix changed"):
        session.invoke("final", lambda _: called.append(True), instruction="Report", reporting_only=True)
    assert called == [] and session._terminal


@pytest.mark.skipif(os.name != "nt", reason="requires Windows junction semantics")
def test_actual_runner_rejects_junction_before_session_writes(tmp_path):
    cell, _, calls, kwargs = _case(tmp_path)
    target = tmp_path / "outside"; target.mkdir()
    link = tmp_path / "junction"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    assert made.returncode == 0 and link.is_junction()
    kwargs["sidecar"] = link / "session"
    with pytest.raises(ContractError, match="link or junction"):
        run_train_cell(cell, **kwargs)
    assert calls == [] and not (target / "session").exists()
