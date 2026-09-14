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
_MANIFEST = "scenario-file-manifest.json"
_BLOBS = "scenario-blobs"
_IGNORED = {_CATALOGUE, _CATALOGUE + ".seal.json", _END, _CLOSURE, _MANIFEST}


def _source() -> dict:
    return source_snapshot(Path(__file__))


def _spec(kind, payload, parents, *, status="produced", module="M9", source=None, coverage="covered"):
    return dict(kind=kind, module=module, payload=payload, parents=parents,
                status=status, producer_source=dict(source or _source()), coverage=coverage,
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
        if name in _IGNORED or name.startswith(_BLOBS + "/"):
            continue
        raw = path.read_bytes()
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
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

    def append(self, kind, payload, *, status="produced", module="M9", source=None, coverage="covered"):
        parent = (self.records[-1].content_hash,) if self.records else ()
        record = self.catalogue.append(**_spec(kind, payload, parent, status=status, module=module,
                                               source=source, coverage=coverage))
        self.records.append(record)
        return record

    def callback_request(self, request: FrozenRecord):
        self.stage = "callback"
        self.append("scenario_callback_request", request.data())

    def callback_return(self, response):
        self.append("scenario_callback_return", {"record": response.data() if type(response) is FrozenRecord else None,
            "returned_type": type(response).__name__, "raw_content_available": type(response) is FrozenRecord,
            "error_type": None, "error": None}, status="produced" if type(response) is FrozenRecord else "rejected")

    def callback_failure(self, error):
        self.append("scenario_callback_return", {"record": None, "returned_type": None,
            "raw_content_available": False, "error_type": type(error).__name__, "error": str(error)}, status="failed")

    def _capture_outputs(self):
        files = _files(self.root)
        rows = []
        for name, snapshot in files.items():
            raw = (self.root / name).read_bytes(); digest = snapshot["sha256"]
            blob = self.root / _BLOBS / digest
            blob.parent.mkdir(exist_ok=True)
            if not blob.exists():
                with blob.open("xb") as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            if blob.is_symlink() or blob.read_bytes() != raw:
                raise ContractError("scenario immutable sidecar copy differs")
            source = source_snapshot(Path(__file__).with_name("deployment.py")) if name.endswith((".json", ".sha256", ".previous")) else source_snapshot(Path(__file__).with_name("modules") / "improvement.py") if name.endswith(".sqlite") else _source()
            known = name.endswith((".sqlite", ".json", ".sha256", ".previous"))
            payload = {"file": name, "blob": _BLOBS + "/" + digest, **snapshot}
            self.append("scenario_sidecar", payload, source=source,
                        module="M9" if known else None, coverage="covered" if known else "uncovered")
            rows.append(payload)
        manifest = FrozenRecord.from_dict({"schema": "m9-scenario-file-manifest-v1", "files": rows,
                                            "fixture_only": True})
        _exclusive(self.root / _MANIFEST, manifest)
        self.append("scenario_file_manifest", _snapshot(self.root, _MANIFEST), module="P0")
        return files

    def close(self, *, result=None, error=None):
        if self.ended:
            raise ContractError("scenario sidecar already closed")
        if result is not None:
            self.stage = "result"
            _exclusive(self.root / _RESULT, result.record)
            self.append("scenario_result", _snapshot(self.root, _RESULT), module="P0")
        files = self._capture_outputs()
        status = "failed" if error is not None else "succeeded"
        terminal = FrozenRecord.from_dict({
            "schema": "m9-scenario-terminal-v1", "status": status, "stage": self.stage,
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error) if error is not None else None,
            "result_digest": result.record.content_hash if result is not None else None,
            "files": files, "fixture_only": True,
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


def _expected_requests(task, injection, experiment_id, variant):
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    manifest = TrainingManifest.freeze((task.identity,))
    base = CandidatePackage.create(parent_digest=None, manifest=manifest,
                                   changes={"memory": {"mode": "off"}}, search_cost=2)
    def request(kind, body):
        return FrozenRecord.from_dict({"schema": "m9-public-fixture-callback-v1", "task": task.data(),
            "kind": kind, "fixture": injection.data(), "body": body})
    if experiment_id == "Q6.1":
        return (request("privilege_attempt", {"attempt": variant, "package_parent": base.digest}),)
    if experiment_id == "Q6.2":
        return () if variant == "fixed" else (request("train_candidate_proposal", {"arm": variant,
            "fixed_base_digest": base.digest, "manual_changes": {"memory": {"mode": "manual", "lesson": "predeclared train-only fixture"}}, "matched_search_budget": 2}),)
    if experiment_id == "Q6.5":
        return tuple(request("offline_scoring_feedback", {"round": round_id, "variant": variant,
            "feedback": "intentionally faulty fixture score", "offline_replay": True, "budget": 2}) for round_id in range(2))
    return (request("validation_acceptance_request", {"candidate_digest": CandidatePackage.create(parent_digest=base.digest, manifest=manifest,
        changes={"memory": {"mode": "on", "lesson": "fixture"}}, search_cost=2).digest, "expected_active_digest": base.digest}),)


def _semantic_files(root, experiment_id, variant, detail):
    files = _files(root)
    def state(name):
        raw = (root / name).read_bytes(); info = _sqlite_state(raw)
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(raw); db.execute("PRAGMA query_only=ON")
            return info, {table: [list(row) for row in db.execute("SELECT * FROM " + table + " ORDER BY 1")]
                          for table in info["tables"]}
        finally: db.close()
    def deployment(name):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        if data.get("schema") != "modular-file-deployment-v1": raise ContractError("scenario deployment schema drift")
        return data
    if experiment_id == "Q6.1" and variant == "self_activate":
        _, rows = state("runtime.sqlite")
        if rows["state"] != [[1, detail["baseline_digest"]]] or rows["used_receipts"]: raise ContractError("Q6.1 runtime state differs")
        if deployment("active.json")["active_digest"] != detail["baseline_digest"]: raise ContractError("Q6.1 deployment differs")
    elif experiment_id == "Q6.2" and "optimizer.sqlite" in files:
        _, rows = state("optimizer.sqlite"); candidate = detail["candidate_digest"]
        if candidate not in [row[0] for row in rows["candidates"]] or rows["comparisons"] != [[candidate, detail["baseline_digest"]]]: raise ContractError("Q6.2 optimizer state differs")
    elif experiment_id == "Q6.5":
        _, rows = state("shadow-runtime.sqlite"); expected = detail["offline_shadow_rounds"][-1]["candidate_digest"] if variant == "unprotected" else detail["baseline_digest"]
        if rows["state"] != [[1, expected]] or len(rows["used_receipts"]) != (2 if variant == "unprotected" else 0): raise ContractError("Q6.5 runtime state differs")
        if deployment("shadow-deployment.json")["active_digest"] != expected: raise ContractError("Q6.5 deployment differs")
    elif experiment_id == "Q6.6":
        _, rows = state("runtime.sqlite"); expected = detail["before"]["active_digest"] if variant in {"rollback", "duplicate"} else detail["next_workflow"]["active_digest"]
        if rows["state"] != [[1, expected]]: raise ContractError("Q6.6 runtime state differs")
        deployed = deployment("deployment.json")["active_digest"]
        if deployed != (detail["before"]["active_digest"] if variant == "drift" else expected): raise ContractError("Q6.6 deployment differs")


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
    if (result.experiment_id != experiment_id or result.variant != variant or
            set(result.record.data()) != {"experiment_id", "variant", "fixture_only", "journal_directory", "callback_count", "detail", "limitation"}
            or result.record.data()["experiment_id"] != experiment_id or result.record.data()["variant"] != variant
            or result.record.data()["callback_count"] != len(result.callback_payloads)):
        raise ContractError("scenario result identity or callback count differs")
    if len(result.callback_payloads) != len(result.callback_outputs):
        raise ContractError("scenario result callback prefix differs")
    expected_requests = _expected_requests(task, injection, experiment_id, variant)
    if result.callback_payloads != expected_requests:
        raise ContractError("scenario callback requests differ from registered fixture operation")
    for request, response in zip(result.callback_payloads, result.callback_outputs):
        if type(request) is not FrozenRecord or type(response) is not FrozenRecord:
            raise ContractError("scenario callback records must be frozen")
        cursor = _take(records, cursor, "scenario_callback_request", request.data())
        cursor = _take(records, cursor, "scenario_callback_return", {
            "record": response.data(), "returned_type": "FrozenRecord", "raw_content_available": True,
            "error_type": None, "error": None})
    if result.record.data().get("journal_directory") != str(root):
        raise ContractError("scenario result directory differs from original output")
    if _read(root / _RESULT) != result.record:
        raise ContractError("scenario result differs from original output replay")
    cursor = _take(records, cursor, "scenario_result", _snapshot(root, _RESULT), module="P0")
    _semantic_files(root, experiment_id, variant, result.record.data()["detail"])
    files = _files(root)
    manifest = _read(root / _MANIFEST).data()
    if manifest != {"schema": "m9-scenario-file-manifest-v1", "files": [
            {"file": name, "blob": _BLOBS + "/" + item["sha256"], **item} for name, item in files.items()], "fixture_only": True}:
        raise ContractError("scenario file manifest differs from original sidecars")
    for item in manifest["files"]:
        blob = root / item["blob"]
        if blob.is_symlink() or not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest() != item["sha256"]:
            raise ContractError("scenario immutable sidecar copy differs")
    while cursor < len(records) and records[cursor].data()["kind"] == "scenario_sidecar":
        item = records[cursor].data()["payload"]["canonical"]
        if item not in manifest["files"]: raise ContractError("scenario sidecar descriptor differs from manifest")
        cursor += 1
    cursor = _take(records, cursor, "scenario_file_manifest", _snapshot(root, _MANIFEST), module="P0")
    terminal = _read(root / _END)
    expected_terminal = {"schema": "m9-scenario-terminal-v1", "status": "succeeded", "stage": "result",
        "error_type": None, "error": None, "result_digest": result.record.content_hash,
        "files": files, "fixture_only": True, "scientific_validated": False}
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
    cursor = _take(records, 0, "scenario_inputs", inputs.data(), module="P0")
    expected = _expected_requests(task, injection, experiment_id, variant)
    request_index = 0
    while cursor < len(records) and records[cursor].data()["kind"] == "scenario_callback_request":
        if request_index >= len(expected): raise ContractError("failed scenario has an unregistered callback request")
        cursor = _take(records, cursor, "scenario_callback_request", expected[request_index].data())
        request_index += 1
        row = records[cursor] if cursor < len(records) else None
        if row is None or row.data()["kind"] != "scenario_callback_return":
            raise ContractError("failed scenario callback request lacks retained outcome")
        body = row.data()["payload"]["canonical"]
        if set(body) != {"record", "returned_type", "raw_content_available", "error_type", "error"}:
            raise ContractError("failed scenario callback outcome schema differs")
        cursor += 1
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
