"""Controlled adapter checks over a real C5 selected-snapshot projection."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import research_loop.modular.joint_selected_snapshot as selected_snapshot
import research_loop.modular.c5_selected_artifact_registration as registration_module
from research_loop.modular.c5_selected_artifact_registration import (
    register_authenticated_selected_run,
    verify_registration,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from test_joint_selected_snapshot import fixture


R = FrozenRecord.from_dict


def _actual_projection(root, monkeypatch):
    panel, choice, package, parent, _, logs = fixture(root, monkeypatch)
    snapshot = selected_snapshot._project(panel.protocol, choice, package, parent, 20)
    run = SimpleNamespace(plan=SimpleNamespace(protocol=panel.protocol, data=lambda: {"timeout_seconds": 20}))
    return run, parent, snapshot, logs


def _authenticated_snapshot(monkeypatch, snapshot, calls):
    def freeze(run, *, parent, execution_authority_keys, scorer_authority_keys):
        calls.append((run, parent, dict(execution_authority_keys), dict(scorer_authority_keys)))
        return snapshot
    monkeypatch.setattr(selected_snapshot, "freeze_selected_joint_snapshot", freeze)


def _write_record(path, body):
    path.write_bytes((R(body).encoded + "\n").encode("utf-8"))


def test_register_and_verify_reauthenticate_real_projection_without_writing_verify_path(tmp_path, monkeypatch):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    calls = []
    _authenticated_snapshot(monkeypatch, snapshot, calls)
    path = tmp_path / "registered.json"
    registered = register_authenticated_selected_run(path, run, parent=parent,
        execution_authority_keys={"execution": b"e"}, scorer_authority_keys={"scorer": b"s"})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        register_authenticated_selected_run(path, run, parent=parent,
            execution_authority_keys={"execution": b"e"}, scorer_authority_keys={"scorer": b"s"})
    assert path.read_bytes() == before
    before_paths = {item.relative_to(tmp_path) for item in tmp_path.rglob("*")}
    opened = Path.open
    def no_verify_write(self, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError("verification must not write the registration")
        return opened(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", no_verify_write)
    assert verify_registration(path, run, parent=parent,
        execution_authority_keys={"execution": b"e"}, scorer_authority_keys={"scorer": b"s"}) == registered
    assert path.read_bytes() == before and {item.relative_to(tmp_path) for item in tmp_path.rglob("*")} == before_paths
    assert len(calls) == 3 and not logs


@pytest.mark.parametrize("fault", ("snapshot", "components", "edges", "provenance", "source", "falseflags"))
def test_verify_rejects_tampered_selected_registration(tmp_path, monkeypatch, fault):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    calls = []
    _authenticated_snapshot(monkeypatch, snapshot, calls)
    path = tmp_path / "registered.json"
    register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    body = FrozenRecord(path.read_text(encoding="utf-8").rstrip("\n")).data()
    if fault == "snapshot":
        body["snapshot"]["selection"]["selected_arm"] = "B0"
        body["snapshot_digest"] = R(body["snapshot"]).content_hash
    elif fault == "components":
        body["components"]["M4"] = "f" * 64
    elif fault == "edges":
        body["typed_edges"][0]["component_digest"] = "f" * 64
    elif fault == "provenance":
        body["snapshot"]["training_provenance"]["schema"] = "tampered"
        body["snapshot_digest"] = R(body["snapshot"]).content_hash
    elif fault == "source":
        body["producer_source"]["sha256"] = "f" * 64
    else:
        body["scientific_validated"] = True
    _write_record(path, body)
    with pytest.raises(ContractError):
        verify_registration(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert len(calls) == (2 if fault in {"snapshot", "provenance"} else 1) and not logs


def test_verify_rejects_crlf_registration_bytes_before_reauthentication(tmp_path, monkeypatch):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    calls = []
    _authenticated_snapshot(monkeypatch, snapshot, calls)
    path = tmp_path / "registered.json"
    register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ContractError):
        verify_registration(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert len(calls) == 1 and not logs


def test_verify_rejects_tampered_retained_selected_registration_original(tmp_path, monkeypatch):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    _authenticated_snapshot(monkeypatch, snapshot, [])
    path = tmp_path / "registered.json"
    register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    original = path.with_name(path.name + ".original")
    original.write_bytes(original.read_bytes() + b" ")
    with pytest.raises(ContractError, match="original bytes"):
        verify_registration(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert not logs


@pytest.mark.parametrize("partial", ("target_only", "original_only"))
def test_same_authenticated_registration_safely_completes_partial_retention(tmp_path, monkeypatch, partial):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    _authenticated_snapshot(monkeypatch, snapshot, [])
    path = tmp_path / "registered.json"
    registered = register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    original = path.with_name(path.name + ".original"); sidecar = path.with_name(path.name + ".provenance.json")
    if partial == "target_only":
        original.unlink(); sidecar.unlink()
    else:
        sidecar.unlink()
    assert register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={}) == registered
    assert verify_registration(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={}) == registered
    assert not logs


def test_existing_different_target_cannot_be_used_to_complete_retention(tmp_path, monkeypatch):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    _authenticated_snapshot(monkeypatch, snapshot, [])
    path = tmp_path / "registered.json"
    register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ContractError, match="existing selected registration differs"):
        register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert not logs


def test_register_rechecks_retention_before_return(tmp_path, monkeypatch):
    run, parent, snapshot, logs = _actual_projection(tmp_path, monkeypatch)
    _authenticated_snapshot(monkeypatch, snapshot, [])
    path = tmp_path / "registered.json"; original = registration_module._retain_registration_bytes
    def tamper(target, record):
        result = original(target, record)
        target.with_name(target.name + ".original").write_bytes(b"tampered")
        return result
    monkeypatch.setattr(registration_module, "_retain_registration_bytes", tamper)
    with pytest.raises(ContractError, match="original bytes"):
        register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert not logs


def test_failed_authentication_creates_no_registration(tmp_path, monkeypatch):
    run, parent, _, logs = _actual_projection(tmp_path, monkeypatch)
    def refuse(*args, **kwargs):
        raise ContractError("synthetic authentication refusal")
    monkeypatch.setattr(selected_snapshot, "freeze_selected_joint_snapshot", refuse)
    path = tmp_path / "not-created" / "registered.json"
    with pytest.raises(ContractError, match="refusal"):
        register_authenticated_selected_run(path, run, parent=parent, execution_authority_keys={}, scorer_authority_keys={})
    assert not path.exists() and not path.parent.exists() and not logs
