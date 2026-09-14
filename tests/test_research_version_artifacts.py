from types import SimpleNamespace

import pytest

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier, RuntimeReceipt, opaque_panel_cell_binding
from research_loop.modular import research_versions
from research_loop.modular.research_versions import ResearchVersionBoundary, verify_research_version_artifacts
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError
from test_modular_retrieval_panel_drivers import _task


def _session(root):
    task = _task("blade")
    return RunSession(task, package_digest="public", arm=default_compatibility("a" * 64).arm(("M1", "M6")),
        objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=root, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))


def _authorization(session):
    subject = FrozenRecord.from_dict({"kind": "source_request", "identity": session.task.identity.data(),
        "task_digest": session.task.content_hash, "source_bundle_digest": "b" * 64,
        "visible_source_ids": ["method"], "request": {"source_id": "method", "operation": "request_new_version", "caller_authorized": True,
        "proposed_objective": {"question": "new"}}})
    receipt = FrozenRecord.from_dict({"schema": "q8-origin-qualification-v1", "subject_digest": subject.content_hash,
        "caller_public_train_qualified": True, "scientific_verified": False})
    session._record("q86_source_authority", {"subject": subject.data(), "receipt": receipt.data()})
    return FrozenRecord.from_dict({"schema": "q86-origin-authorization-v1", "subject": subject.data(), "receipt": receipt.data(),
        "authority_artifact": session._event_artifacts[-1]})


def _authority(subject):
    return FrozenRecord.from_dict({"schema": "independent-research-version-freeze-v1", "subject_digest": subject.content_hash,
        "authorized": True, "scientific_verified": False})


def test_paused_child_has_exact_disk_catalogue_and_authority_edges(tmp_path):
    session = _session(tmp_path)
    boundary = ResearchVersionBoundary(session)
    boundary.pause_and_freeze(FrozenRecord.from_dict({"question": "new"}), SimpleNamespace(freeze_version=_authority), _authorization(session))
    session.artifacts.seal()
    assert boundary.data()["state"] == "paused" and boundary.data()["child"] is not None


def test_child_mutation_blocks_the_actual_reporting_only_model_entry_before_io(tmp_path):
    session = _session(tmp_path)
    boundary = ResearchVersionBoundary(session)
    boundary.pause_and_freeze(FrozenRecord.from_dict({"question": "new"}), SimpleNamespace(freeze_version=_authority), _authorization(session))
    boundary.child_path.write_text('{"tampered":true}\n', encoding="utf-8")
    called = []
    with pytest.raises(ContractError, match="disk bytes"):
        session.invoke("final", lambda _: called.append("model"), instruction="Report only.", reporting_only=True)
    assert called == []


def test_publish_failure_retains_partial_prefix_without_replacing_a_final(tmp_path, monkeypatch):
    record = FrozenRecord.from_dict({"schema": "research-version-v1", "test": "partial"})
    final = tmp_path / "research-version-parent.json"
    monkeypatch.setattr(research_versions.os, "link", lambda *_: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError, match="injected"):
        research_versions._publish(final, record)
    partial = final.with_name(final.name + ".partial")
    assert not final.exists() and partial.read_bytes() == (record.encoded + "\n").encode("utf-8")


def test_running_version_requires_no_child_and_preserves_the_parent_descriptor_edge(tmp_path):
    session = _session(tmp_path)
    ResearchVersionBoundary(session)
    session.artifacts.seal()
    assert not (tmp_path / "research-version-child.json").exists()


def test_panel_receipt_verifier_consumes_the_sealed_q86_parent_before_return(tmp_path):
    session = _session(tmp_path)
    cell = PanelCell("Q8.6", session.task.identity, "r1", "conflict", "a", session.arm,
        session.task.content_hash, "b" * 64, "c" * 64, "d" * 64)
    session = RunSession(session.task, package_digest=cell.package_digest, arm=cell.runtime_arm,
        objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=tmp_path / "receipt", verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    ResearchVersionBoundary(session)
    response = session.invoke("final", lambda request: FrozenRecord.from_dict({"objective_digest": request.data()["objective"] and session.objective.content_hash,
        "outcome": "unknown", "evidence_ids": [], "conclusion": "report", "programme_complete": False}), instruction="Report only.",
        reporting_only=True, module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell)}))
    terminal = session.finish(response)
    session.artifacts.seal()
    trace = (tmp_path / "receipt" / "trace.jsonl")
    receipt = RuntimeReceipt(cell.key, "succeeded", trace, FrozenRecord(trace.read_text(encoding="utf-8").splitlines()[-1]).content_hash,
        FrozenRecord.from_dict({"responses": [response.data()], "terminal": terminal.data()}).content_hash, None)
    with pytest.raises(ContractError, match="retained compiled scenario"):
        PanelReceiptVerifier()._verify_runtime(receipt, cell)


@pytest.mark.parametrize("coverage_id", ("Q8.5", "Q8.7"))
def test_q85_q87_receipt_controls_do_not_require_research_version_outputs(tmp_path, coverage_id):
    initial = _session(tmp_path)
    cell = PanelCell(coverage_id, initial.task.identity, "r1", "control", "a", initial.arm,
        initial.task.content_hash, "b" * 64, "c" * 64, "d" * 64)
    session = RunSession(initial.task, package_digest=cell.package_digest, arm=cell.runtime_arm,
        objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=tmp_path / coverage_id, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    response = session.invoke("final", lambda request: FrozenRecord.from_dict({"objective_digest": session.objective.content_hash,
        "outcome": "unknown", "evidence_ids": [], "conclusion": "control", "programme_complete": False}), instruction="Report.",
        module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell)}))
    terminal = session.finish(response)
    trace = tmp_path / coverage_id / "trace.jsonl"
    receipt = RuntimeReceipt(cell.key, "succeeded", trace, FrozenRecord(trace.read_text(encoding="utf-8").splitlines()[-1]).content_hash,
        FrozenRecord.from_dict({"responses": [response.data()], "terminal": terminal.data()}).content_hash, None)
    PanelReceiptVerifier()._verify_runtime(receipt, cell)
    assert not (tmp_path / coverage_id / "research-version-parent.json").exists()
