"""Immutable sidecars for offline Q6 scenario fixture executions.

These records bind the actual callback boundary and local runtime outputs.  They are
engineering evidence only and never authorize a model, validation input, or
production deployment.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import _exclusive
from research_loop.ontology import ContractError

_CATALOGUE = "scenario-artifacts.jsonl"
_END = "scenario-terminal.json"
_CLOSURE = "scenario-closure.json"
_RESULT = "scenario-result.json"
_IGNORED = {_CATALOGUE, _CATALOGUE + ".seal.json", _END, _CLOSURE}


def _source() -> dict:
    return source_snapshot(Path(__file__))


def _spec(kind, payload, parents, *, status="produced", module="M9"):
    return dict(kind=kind, module=module, payload=payload, parents=parents,
                status=status, producer_source=_source(),
                cost={"known": False, "units": None})


def _read(path: Path) -> FrozenRecord:
    if path.is_symlink() or not path.is_file():
        raise ContractError("original scenario artifact output is missing")
    try:
        return FrozenRecord(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ContractError("scenario artifact output is not canonical") from exc


def _snapshot(root: Path, name: str) -> dict:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ContractError("original scenario artifact output is missing")
    raw = path.read_bytes()
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _sqlite_state(raw: bytes) -> dict:
    db = sqlite3.connect(":memory:")
    try:
        db.deserialize(raw)
        db.execute("PRAGMA query_only=ON")
        integrity = [row[0] for row in db.execute("PRAGMA quick_check")]
        if integrity != ["ok"]:
            raise ContractError("scenario sqlite sidecar failed quick check")
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {"quick_check": integrity, "tables": tables}
    except sqlite3.Error as exc:
        raise ContractError("scenario sqlite sidecar cannot be read") from exc
    finally:
        db.close()


def _files(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("original scenario directory required")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError("scenario output cannot be a symlink")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name in _IGNORED:
            continue
        raw = path.read_bytes()
        item = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        if name.endswith(".sqlite"):
            item["sqlite"] = _sqlite_state(raw)
        elif name.endswith(".json"):
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractError("scenario JSON sidecar cannot be read") from exc
            item["json"] = True
        files[name] = item
    return files


def _inputs(task, controls, injection, experiment_id, variant) -> FrozenRecord:
    task.identity.require_train()
    return FrozenRecord.from_dict({
        "schema": "m9-scenario-artifact-inputs-v1", "fixture_only": True,
        "task": task.data(), "controls": controls.data(), "injection": injection.data(),
        "experiment_id": experiment_id, "variant": variant,
        "scenario_source": source_snapshot(Path(__file__).with_name("scenarios_improvement.py")),
        "adapter_source": _source(),
    })


class ScenarioArtifactWriter:
    def __init__(self, root, *, task, controls, injection, experiment_id, variant):
        self.root = Path(root)
        if self.root.is_symlink() or not self.root.is_dir() or any(self.root.iterdir()):
            raise ContractError("scenario sidecar requires its newly created empty directory")
        self.inputs = _inputs(task, controls, injection, experiment_id, variant)
        self.task, self.variant, self.experiment_id = task, variant, experiment_id
        self.catalogue = ArtifactCatalogue(
            self.root / _CATALOGUE, identity=task.identity, run_id=str(uuid4()),
            experiment_id=experiment_id + ":" + variant, lock_digest=self.inputs.content_hash,
            producer_source=_source())
        self.records = []
        self.ended = False
        self.stage = "inputs"
        self.append("scenario_inputs", self.inputs.data(), module="P0")

    def append(self, kind, payload, *, status="produced", module="M9"):
        parent = (self.records[-1].content_hash,) if self.records else ()
        record = self.catalogue.append(**_spec(kind, payload, parent, status=status, module=module))
        self.records.append(record)
        return record

    def callback(self, request: FrozenRecord, response: FrozenRecord):
        self.stage = "callback"
        self.append("scenario_callback_request", request.data())
        self.append("scenario_callback_return", {"record": response.data(),
            "returned_type": "FrozenRecord", "raw_content_available": True})

    def close(self, *, result=None, error=None):
        if self.ended:
            raise ContractError("scenario sidecar already closed")
        if result is not None:
            self.stage = "result"
            _exclusive(self.root / _RESULT, result.record)
            self.append("scenario_result", _snapshot(self.root, _RESULT), module="P0")
        status = "failed" if error is not None else "succeeded"
        terminal = FrozenRecord.from_dict({
            "schema": "m9-scenario-terminal-v1", "status": status, "stage": self.stage,
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error) if error is not None else None,
            "result_digest": result.record.content_hash if result is not None else None,
            "files": _files(self.root), "fixture_only": True,
            "scientific_validated": False,
        })
        _exclusive(self.root / _END, terminal)
        self.append("scenario_terminal", _snapshot(self.root, _END),
                    status="failed" if error is not None else "produced", module="P0")
        seal = self.catalogue.seal()
        _exclusive(self.root / _CLOSURE, FrozenRecord.from_dict({
            "schema": "m9-scenario-closure-v1", "catalogue_seal": seal.data(),
            "terminal": _snapshot(self.root, _END)}))
        self.ended = True


def _open(root, task, inputs, experiment_id, variant):
    root = Path(root); path = root / _CATALOGUE
    if root.is_symlink() or path.is_symlink() or not path.is_file() or not path.with_name(path.name + ".seal.json").is_file():
        raise ContractError("original sealed scenario catalogue is missing")
    try:
        first = FrozenRecord(path.read_text(encoding="utf-8").splitlines()[0]).data()["descriptor"]
        binding = first["binding"]
        catalogue = ArtifactCatalogue(path, identity=task.identity, **binding,
                                      producer_source=first["producer_source"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ContractError("scenario catalogue has no original run binding") from exc
    if (binding["experiment_id"] != experiment_id + ":" + variant or
            binding["lock_digest"] != inputs.content_hash or not binding["run_id"]):
        raise ContractError("scenario run binding differs from original inputs")
    return root, catalogue


def _take(records, cursor, kind, payload, *, status="produced", module="M9"):
    if cursor >= len(records):
        raise ContractError("scenario original output is missing")
    row = records[cursor]
    expected = _spec(kind, payload, (records[cursor - 1].content_hash,) if cursor else (),
                     status=status, module=module)
    data = row.data()
    for key, value in expected.items():
        if key == "payload":
            if data["payload"]["canonical"] != value:
                raise ContractError("scenario original output differs from retained execution")
            continue
        if key == "parents":
            value = list(value)
        if data[key] != value:
            raise ContractError("scenario original output differs from retained execution")
    return cursor + 1


def verify_scenario_artifacts(result, *, task, frozen_controls, sidecar, experiment_id, variant):
    """Read an original successful Q6 scenario without callbacks or runtime activation."""
    from research_loop.modular.scenarios_improvement import ImprovementScenarioResult, _controls, improvement_injection
    if type(result) is not ImprovementScenarioResult:
        raise ContractError("original scenario result required")
    _controls(task, frozen_controls)
    injection = improvement_injection(experiment_id, variant)
    inputs = _inputs(task, frozen_controls, injection, experiment_id, variant)
    root, catalogue = _open(sidecar, task, inputs, experiment_id, variant)
    records = list(catalogue.records()); cursor = 0
    cursor = _take(records, cursor, "scenario_inputs", inputs.data(), module="P0")
    if len(result.callback_payloads) != len(result.callback_outputs):
        raise ContractError("scenario result callback prefix differs")
    for request, response in zip(result.callback_payloads, result.callback_outputs):
        if type(request) is not FrozenRecord or type(response) is not FrozenRecord:
            raise ContractError("scenario callback records must be frozen")
        cursor = _take(records, cursor, "scenario_callback_request", request.data())
        cursor = _take(records, cursor, "scenario_callback_return", {
            "record": response.data(), "returned_type": "FrozenRecord", "raw_content_available": True})
    if result.record.data().get("journal_directory") != str(root):
        raise ContractError("scenario result directory differs from original output")
    if _read(root / _RESULT) != result.record:
        raise ContractError("scenario result differs from original output replay")
    cursor = _take(records, cursor, "scenario_result", _snapshot(root, _RESULT), module="P0")
    terminal = _read(root / _END)
    expected_terminal = {"schema": "m9-scenario-terminal-v1", "status": "succeeded", "stage": "result",
        "error_type": None, "error": None, "result_digest": result.record.content_hash,
        "files": _files(root), "fixture_only": True, "scientific_validated": False}
    if terminal.data() != expected_terminal:
        raise ContractError("scenario terminal differs from original output and sidecars")
    cursor = _take(records, cursor, "scenario_terminal", _snapshot(root, _END), module="P0")
    if cursor != len(records):
        raise ContractError("scenario has unconsumed artifact records")
    seal = _read(root / (_CATALOGUE + ".seal.json")); catalogue.verify(seal)
    if _read(root / _CLOSURE).data() != {"schema": "m9-scenario-closure-v1", "catalogue_seal": seal.data(),
                                          "terminal": _snapshot(root, _END)}:
        raise ContractError("scenario closure does not bind original sealed outputs")
    return FrozenRecord.from_dict({"schema": "m9-scenario-artifacts-verified-v1", "status": "succeeded",
        "descriptor_count": len(records), "scientific_validated": False, "scientific_effect": "not_measured"})


def inspect_scenario_failure(*, task, frozen_controls, sidecar, experiment_id, variant):
    """Read a retained failed prefix without treating it as accepted execution."""
    from research_loop.modular.scenarios_improvement import _controls, improvement_injection
    _controls(task, frozen_controls)
    injection = improvement_injection(experiment_id, variant)
    inputs = _inputs(task, frozen_controls, injection, experiment_id, variant)
    root, catalogue = _open(sidecar, task, inputs, experiment_id, variant)
    records = list(catalogue.records())
    if len(records) < 2:
        raise ContractError("failed scenario has no retained input and terminal")
    _take(records, 0, "scenario_inputs", inputs.data(), module="P0")
    terminal = _read(root / _END).data()
    if (set(terminal) != {"schema", "status", "stage", "error_type", "error", "result_digest", "files", "fixture_only", "scientific_validated"}
            or terminal["schema"] != "m9-scenario-terminal-v1" or terminal["status"] != "failed"
            or type(terminal["stage"]) is not str or type(terminal["error_type"]) is not str
            or not terminal["error_type"] or type(terminal["error"]) is not str
            or terminal["result_digest"] is not None or terminal["files"] != _files(root)
            or terminal["fixture_only"] is not True or terminal["scientific_validated"] is not False):
        raise ContractError("failed scenario terminal does not bind retained sidecars")
    _take(records, len(records) - 1, "scenario_terminal", _snapshot(root, _END), status="failed", module="P0")
    seal = _read(root / (_CATALOGUE + ".seal.json")); catalogue.verify(seal)
    if _read(root / _CLOSURE).data() != {"schema": "m9-scenario-closure-v1", "catalogue_seal": seal.data(),
                                          "terminal": _snapshot(root, _END)}:
        raise ContractError("failed scenario closure drift")
    return FrozenRecord.from_dict({"schema": "m9-scenario-failure-storage-v1", "status": "failed",
        "stage": terminal["stage"], "error_type": terminal["error_type"], "error": terminal["error"],
        "files": terminal["files"], "descriptor_count": len(records), "storage_integrity_verified": True,
        "stage_semantics_verified": False, "scientific_validated": False, "acceptance_eligible": False})
