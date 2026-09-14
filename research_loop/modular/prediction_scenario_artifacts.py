"""Durable, read-only-verifiable records for offline prediction fixtures."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical, digest

_JOURNAL = "prediction-scenario-artifacts.jsonl"
_TERMINAL = "prediction-scenario-terminal.json"
_CLOSURE = "prediction-scenario-closure.json"


def _plain(path: Path) -> Path:
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            stat = item.lstat()
        except FileNotFoundError:
            continue
        if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ContractError("prediction scenario artifact path traverses a link")
    return path


def _write_new(path: Path, record: FrozenRecord) -> None:
    with _plain(path).open("xb") as stream:
        stream.write((record.encoded + "\n").encode("utf-8")); stream.flush(); os.fsync(stream.fileno())


def _read_one(path: Path) -> FrozenRecord:
    raw = _plain(path).read_bytes()
    if not raw.endswith(b"\n"):
        raise ContractError("prediction scenario artifact has an incomplete tail")
    try:
        value = FrozenRecord(raw.decode("utf-8").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError("prediction scenario artifact is malformed") from exc
    if raw != (value.encoded + "\n").encode("utf-8"):
        raise ContractError("prediction scenario artifact is not canonical")
    return value


def _inventory(root: Path) -> dict:
    root = _plain(root)
    if not root.is_dir():
        raise ContractError("prediction scenario artifact root is missing")
    files = {}
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            _plain(Path(base) / name)
        for name in names:
            file = _plain(Path(base) / name)
            raw = file.read_bytes()
            files[file.relative_to(root).as_posix()] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return dict(sorted(files.items()))


class PredictionScenarioArtifactWriter:
    """Append records before each callback; failures remain closed evidence."""
    def __init__(self, root, *, task, controls, experiment_id, variant):
        self.root = _plain(Path(root))
        if self.root.exists():
            if not self.root.is_dir() or any(self.root.iterdir()):
                raise ContractError("prediction scenario artifact root must be a new empty directory")
        else:
            self.root.mkdir(parents=True)
        self.task, self.controls = task, controls
        self.experiment_id, self.variant = experiment_id, variant
        self.run_id = uuid4().hex
        self.entries: list[FrozenRecord] = []
        self.closed = False
        self.inputs = FrozenRecord.from_dict({"schema": "prediction-scenario-input-v1", "fixture_only": True,
            "task": task.data(), "controls": controls.data(), "experiment_id": experiment_id, "variant": variant,
            "scenario_source": source_snapshot(Path(__file__).with_name("scenarios_predictions.py")),
            "artifact_source": source_snapshot(Path(__file__))})
        self.append("attempt", {"run_id": self.run_id, "input_digest": self.inputs.content_hash,
            "task_digest": task.content_hash, "identity": task.identity.data(), "experiment_id": experiment_id, "variant": variant})
        self.append("inputs", self.inputs.data())

    def append(self, kind: str, data: dict, *, status="produced") -> FrozenRecord:
        if self.closed: raise ContractError("prediction scenario artifact writer is closed")
        previous = self.entries[-1].content_hash if self.entries else None
        record = FrozenRecord.from_dict({"schema": "prediction-scenario-artifact-v1", "sequence": len(self.entries),
            "previous": previous, "kind": kind, "status": status, "run_id": self.run_id, "data": data})
        with _plain(self.root / _JOURNAL).open("ab") as stream:
            stream.write((record.encoded + "\n").encode("utf-8")); stream.flush(); os.fsync(stream.fileno())
        self.entries.append(record); return record

    def plan(self, payload: FrozenRecord) -> None: self.append("frozen_plan", payload.data())
    def callback_request(self, payload: FrozenRecord) -> None: self.append("callback_request", payload.data())
    def callback_return(self, raw, typed: FrozenRecord) -> None:
        self.append("callback_return", {"raw": raw.data() if type(raw) is FrozenRecord else raw,
            "typed": typed.data(), "typed_digest": typed.content_hash})
    def callback_failure(self, error: Exception) -> None:
        self.append("callback_failure", {"error_type": type(error).__name__, "error": str(error)}, status="failed")
    def trace(self, trace: FrozenRecord) -> None: self.append("mechanism_trace", trace.data())
    def outcome(self, record: FrozenRecord) -> None: self.append("outcome", record.data())

    def close(self, result: FrozenRecord | None, error: Exception | None = None) -> None:
        if self.closed: return
        terminal = FrozenRecord.from_dict({"schema": "prediction-scenario-terminal-v1", "status": "failed" if error else "succeeded",
            "result": result.data() if result else None, "result_digest": result.content_hash if result else None,
            "error_type": type(error).__name__ if error else None, "error": str(error) if error else None,
            "entry_count": len(self.entries), "fixture_only": True, "scientific_validated": False})
        _write_new(self.root / _TERMINAL, terminal)
        files = _inventory(self.root)
        _write_new(self.root / _CLOSURE, FrozenRecord.from_dict({"schema": "prediction-scenario-closure-v1", "inputs": self.inputs.data(),
            "terminal": terminal.data(), "files": files, "fixture_only": True, "scientific_validated": False}))
        self.closed = True


def verify_prediction_scenario_artifacts(root, *, task, controls, experiment_id, variant, complete=True) -> FrozenRecord:
    """Read artifacts only.  It neither invokes callbacks nor repairs storage."""
    try:
        root = _plain(Path(root)); expected = {_JOURNAL, _TERMINAL, _CLOSURE}
        if _inventory(root).keys() != expected:
            raise ContractError("prediction scenario artifact inventory is incomplete or has extra files")
        raw = _plain(root / _JOURNAL).read_bytes()
        if not raw.endswith(b"\n"): raise ContractError("prediction scenario journal has incomplete tail")
        entries = [FrozenRecord(line) for line in raw.decode("utf-8").splitlines()]
        if raw != "".join(item.encoded + "\n" for item in entries).encode("utf-8") or not entries:
            raise ContractError("prediction scenario journal is not canonical")
        run_id = entries[0].data()["run_id"]
        previous = None
        for index, entry in enumerate(entries):
            row = entry.data()
            if set(row) != {"schema", "sequence", "previous", "kind", "status", "run_id", "data"} or row["schema"] != "prediction-scenario-artifact-v1" or row["sequence"] != index or row["previous"] != previous or row["run_id"] != run_id:
                raise ContractError("prediction scenario journal chain differs")
            previous = entry.content_hash
        attempt, inputs = entries[:2]
        body = inputs.data()["data"]
        if (attempt.data()["kind"] != "attempt" or inputs.data()["kind"] != "inputs" or body["task"] != task.data() or
            body["controls"] != controls.data() or body["experiment_id"] != experiment_id or body["variant"] != variant or
            body["task"]["identity"] != task.identity.data() or attempt.data()["data"]["input_digest"] != digest(body)):
            raise ContractError("prediction scenario input subject binding differs")
        for source in (body["scenario_source"], body["artifact_source"]):
            if source_snapshot(Path(source["path"])) != source: raise ContractError("prediction scenario producer source differs")
        terminal = _read_one(root / _TERMINAL).data(); closure = _read_one(root / _CLOSURE).data()
        if terminal["entry_count"] != len(entries) or terminal["fixture_only"] is not True or terminal["scientific_validated"] is not False:
            raise ContractError("prediction scenario terminal differs")
        closed_files = _inventory(root); closed_files.pop(_CLOSURE)
        if closure != {"schema": "prediction-scenario-closure-v1", "inputs": body, "terminal": terminal,
                       "files": closed_files, "fixture_only": True, "scientific_validated": False}:
            raise ContractError("prediction scenario closure or inventory differs")
        if complete and terminal["status"] != "succeeded": raise ContractError("prediction scenario attempt did not complete")
        requests = [e.data()["data"] for e in entries if e.data()["kind"] == "callback_request"]
        returns = [e.data()["data"] for e in entries if e.data()["kind"] == "callback_return"]
        failures = [e for e in entries if e.data()["kind"] == "callback_failure"]
        if ((terminal["status"] == "succeeded" and len(requests) != len(returns)) or
            (terminal["status"] == "failed" and len(requests) != len(returns) + len(failures)) or
            any(r["typed_digest"] != FrozenRecord.from_dict(r["typed"]).content_hash for r in returns)):
            raise ContractError("prediction scenario callback records differ")
        outcomes = [e.data()["data"] for e in entries if e.data()["kind"] == "outcome"]
        if terminal["status"] == "succeeded" and (len(outcomes) != 1 or terminal["result"] != outcomes[0]):
            raise ContractError("prediction scenario completed output is missing")
        return FrozenRecord.from_dict({"schema": "prediction-scenario-artifact-check-v1", "run_id": run_id,
            "callback_count": len(requests), "status": terminal["status"], "storage_integrity_verified": True,
            "scientific_validated": False})
    except ContractError: raise
    except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ContractError("prediction scenario artifacts are malformed") from exc
