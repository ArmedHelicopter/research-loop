"""Durable records and memory-only semantic replay for prediction fixtures."""
from __future__ import annotations
import hashlib
import os
import re
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

_JOURNAL = "prediction-scenario-artifacts.jsonl"
_TERMINAL = "prediction-scenario-terminal.json"
_CLOSURE = "prediction-scenario-closure.json"


def _plain(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            stat = item.lstat()
        except FileNotFoundError:
            continue
        if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ContractError("prediction artifact path traverses a link")
    return path


def _write_new(path, record):
    with _plain(path).open("xb") as stream:
        stream.write((record.encoded + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def _read_one(path):
    raw = _plain(path).read_bytes()
    record = FrozenRecord(raw.decode().strip())
    if raw != (record.encoded + "\n").encode():
        raise ContractError("prediction record is incomplete or noncanonical")
    return record


def _inventory(root):
    root = _plain(root)
    if not root.is_dir():
        raise ContractError("prediction artifact root is missing")
    files = {}
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            _plain(Path(base) / name)
        for name in names:
            file = _plain(Path(base) / name)
            raw = file.read_bytes()
            files[file.relative_to(root).as_posix()] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return dict(sorted(files.items()))


def _sources():
    here = Path(__file__).parent
    paths = [Path(__file__), here / "scenarios_predictions.py", here / "contracts.py",
             here / "artifact_catalogue.py", here / "modules/predictions.py",
             here / "modules/exploration.py", here.parent / "ontology.py"]
    return [source_snapshot(_plain(path)) for path in paths]


def _inputs(task, controls, experiment_id, variant):
    return FrozenRecord.from_dict({"schema": "prediction-scenario-input-v2", "fixture_only": True,
        "task": task.data(), "controls": controls.data(), "experiment_id": experiment_id,
        "variant": variant, "sources": _sources()})


def _raw_record(raw):
    if type(raw) is FrozenRecord:
        return {"encoding": "frozen_record", "value": raw.data()}
    if raw is None or isinstance(raw, Mapping) or type(raw) in (str, bool, int, float, list):
        try:
            return FrozenRecord.from_dict({"encoding": "json", "value": dict(raw) if isinstance(raw, Mapping) else raw}).data()
        except (TypeError, ValueError, ContractError):
            pass
    # Unsupported Python objects have no canonical bytes; never invent a repr.
    return {"encoding": "unsupported_python", "type": type(raw).__name__}


def _error(exc):
    return {"error_type": type(exc).__name__, "error": str(exc)}


class _ReplayEnd(Exception):
    pass


class _RecordedFailure(Exception):
    pass


class _Records:
    """Memory-only mechanism sink, shared by the durable producer."""
    def __init__(self, run_id):
        self.run_id, self.entries, self.replay_responses = run_id, [], None

    def _parents(self, kind, data):
        def matching(kinds):
            return [r for r in self.entries if r.data()["kind"] in kinds]
        if kind == "attempt":
            return []
        if kind == "inputs":
            rows = matching({"attempt"})
        elif kind == "registry_event" and data["event"] == "freeze":
            rows = matching({"inputs"})
        elif kind == "frozen_plan":
            rows = [r for r in matching({"registry_event"}) if r.data()["data"].get("plan_id") == data.get("plan_id")]
            rows = rows or matching({"inputs"})
        elif kind == "callback_request":
            rows = matching({"frozen_plan"})[-1:]
        elif kind in {"callback_raw", "callback_failure"}:
            rows = matching({"callback_request"})[-1:]
        elif kind == "callback_return":
            rows = matching({"callback_raw"})[-1:]
        elif kind == "mechanism_output":
            rows = matching({"inputs"})
            if data["port"] == "assess_feasibility":
                rows += matching({"frozen_plan"})[-1:] + matching({"callback_return"})[-1:]
        elif kind == "registry_event":
            rows = [r for r in matching({"registry_event"}) if r.data()["data"].get("event") == "freeze"
                    and r.data()["data"].get("plan_id") == data["plan_id"]]
            # Unknown classifications follow all allocated fixture returns.
            rows += matching({"callback_return"})
        elif kind == "mechanism_trace":
            rows = matching({"inputs", "registry_event", "callback_return", "frozen_plan", "mechanism_output"})
        elif kind == "outcome":
            rows = matching({"mechanism_trace", "callback_return"})
        else:
            raise ContractError("unknown prediction artifact kind")
        return [r.content_hash for r in rows]

    def append(self, kind, data, *, status="produced"):
        module = "P0" if kind in {"attempt", "inputs"} else ("M4" if kind in {"registry_event", "frozen_plan"} else None)
        if kind == "mechanism_output":
            module = "M4" if data["port"] in {"deduplicate_mechanism_predictions", "deduplicate_titles"} else "M7"
        record = FrozenRecord.from_dict({"schema": "prediction-scenario-artifact-v2",
            "sequence": len(self.entries), "previous": self.entries[-1].content_hash if self.entries else None,
            "kind": kind, "module": module, "status": status, "run_id": self.run_id,
            "parents": self._parents(kind, data), "data": data})
        self._persist(record)
        self.entries.append(record)
        return record

    def _persist(self, record):
        pass

    def initialize(self, task, controls, experiment_id, variant):
        self.inputs = _inputs(task, controls, experiment_id, variant)
        self.append("attempt", {"run_id": self.run_id, "input_digest": self.inputs.content_hash,
            "task_digest": task.content_hash, "identity": task.identity.data(),
            "experiment_id": experiment_id, "variant": variant})
        self.append("inputs", self.inputs.data())

    def registry_event(self, event):
        self.append("registry_event", event.data())

    def plan(self, payload):
        self.append("frozen_plan", payload.data(), status="rejected" if payload.data().get("m4_decision") == "rejected" else "produced")

    def callback_request(self, payload):
        self.append("callback_request", payload.data())

    def callback_raw(self, raw):
        self.append("callback_raw", _raw_record(raw))

    def callback_return(self, typed):
        self.append("callback_return", {"typed": typed.data(), "typed_digest": typed.content_hash})

    def callback_failure(self, exc):
        self.append("callback_failure", _error(exc), status="failed")

    def trace(self, trace):
        self.append("mechanism_trace", trace.data())

    def outcome(self, record):
        self.append("outcome", record.data())

    def mechanism_output(self, port, inputs, result):
        self.append("mechanism_output", {"port": port, "inputs": inputs, "result": result})

    def replay_response(self):
        if not self.replay_responses:
            raise _ReplayEnd()
        kind, data = self.replay_responses.pop(0)
        if kind == "callback_failure":
            if set(data) != {"error_type", "error"} or not all(type(v) is str for v in data.values()):
                raise ContractError("invalid callback failure")
            self.append(kind, data, status="failed")
            raise _RecordedFailure()
        if data.get("encoding") == "frozen_record" and set(data) == {"encoding", "value"}:
            return FrozenRecord.from_dict(data["value"])
        if data.get("encoding") == "json" and set(data) == {"encoding", "value"}:
            return data["value"]
        if data.get("encoding") == "unsupported_python" and set(data) == {"encoding", "type"} and type(data["type"]) is str:
            self.append("callback_raw", data)
            raise _RecordedFailure()
        raise ContractError("invalid raw callback representation")


class PredictionScenarioArtifactWriter(_Records):
    def __init__(self, root, *, task, controls, experiment_id, variant):
        super().__init__(uuid4().hex)
        self.root, self.closed = _plain(root), False
        if self.root.exists():
            raise ContractError("prediction artifact root must be a new directory")
        self.root.mkdir(parents=True, exist_ok=False)
        self.initialize(task, controls, experiment_id, variant)

    def _persist(self, record):
        if self.closed:
            raise ContractError("prediction writer is closed")
        path = _plain(self.root / _JOURNAL)
        expected = b"".join((r.encoded + "\n").encode() for r in self.entries)
        if (path.read_bytes() if path.exists() else b"") != expected:
            raise ContractError("prediction journal changed during production")
        with path.open("ab") as stream:
            stream.write((record.encoded + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

    def before_callback(self):
        if _sources() != self.inputs.data()["sources"]:
            raise ContractError("prediction source changed before callback")
        if _plain(self.root / _JOURNAL).read_bytes() != b"".join((r.encoded + "\n").encode() for r in self.entries):
            raise ContractError("prediction journal changed before callback")

    def close(self, result, error=None):
        if self.closed:
            return
        terminal = FrozenRecord.from_dict({"schema": "prediction-scenario-terminal-v2",
            "status": "failed" if error else "succeeded", "run_id": self.run_id, "input_digest": self.inputs.content_hash,
            "result": result.data() if result else None, "result_digest": result.content_hash if result else None,
            **(_error(error) if error else {"error_type": None, "error": None}),
            "entry_count": len(self.entries), "fixture_only": True, "scientific_validated": False})
        _write_new(self.root / _TERMINAL, terminal)
        _write_new(self.root / _CLOSURE, FrozenRecord.from_dict({"schema": "prediction-scenario-closure-v2",
            "inputs": self.inputs.data(), "terminal": terminal.data(), "files": _inventory(self.root),
            "fixture_only": True, "scientific_validated": False}))
        self.closed = True

    def close_failure(self, exc):
        try:
            if not self.closed and not (self.root / _TERMINAL).exists():
                self.close(None, exc)
            else:
                _write_new(self.root / "prediction-scenario-delivery-failure.json", FrozenRecord.from_dict({
                    "schema": "prediction-scenario-delivery-failure-v1", "run_id": self.run_id,
                    **_error(exc), "scientific_validated": False}))
        except (OSError, ContractError):
            # Keep partial bytes and original error; incomplete storage is refused.
            pass


class _ReplayRecords(_Records):
    def __init__(self, run_id, observed):
        super().__init__(run_id)
        self.observed = observed

    def _persist(self, record):
        if len(self.entries) >= len(self.observed):
            raise _ReplayEnd()
        if record != self.observed[len(self.entries)]:
            raise ContractError("prediction semantic record differs from expected experiment")


def verify_prediction_scenario_artifacts(root, *, task, controls, experiment_id, variant,
                                         complete=True, expected_run_id=None):
    """Reconstruct mechanism events in memory; never invoke user callbacks or write files."""
    from research_loop.modular.scenarios_predictions import _controls, _validate, _evaluate_prediction_scenario
    try:
        _validate(experiment_id, variant)
        _controls(task, controls)
        task.identity.require_train()
        root = _plain(root)
        files = _inventory(root)
        if set(files) != {_JOURNAL, _TERMINAL, _CLOSURE}:
            raise ContractError("prediction artifact inventory is incomplete or has extra files")
        raw = _plain(root / _JOURNAL).read_bytes()
        entries = [FrozenRecord(line) for line in raw.decode().splitlines()]
        if not entries or raw != b"".join((r.encoded + "\n").encode() for r in entries):
            raise ContractError("prediction journal is incomplete or noncanonical")
        run_id = entries[0].data()["run_id"]
        if type(run_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", run_id) or (expected_run_id is not None and run_id != expected_run_id):
            raise ContractError("prediction run binding differs")
        expected_inputs = _inputs(task, controls, experiment_id, variant)
        terminal = _read_one(root / _TERMINAL).data()
        if (set(terminal) != {"schema", "status", "run_id", "input_digest", "result", "result_digest", "error_type", "error",
                "entry_count", "fixture_only", "scientific_validated"} or terminal["schema"] != "prediction-scenario-terminal-v2"
                or terminal["run_id"] != run_id or terminal["input_digest"] != expected_inputs.content_hash
                or terminal["entry_count"] != len(entries) or type(terminal["entry_count"]) is not int
                or terminal["fixture_only"] is not True or terminal["scientific_validated"] is not False
                or terminal["status"] not in {"succeeded", "failed"}):
            raise ContractError("prediction terminal binding differs")
        closed_files = dict(files)
        closed_files.pop(_CLOSURE)
        if _read_one(root / _CLOSURE).data() != {"schema": "prediction-scenario-closure-v2", "inputs": expected_inputs.data(),
                "terminal": terminal, "files": closed_files, "fixture_only": True, "scientific_validated": False}:
            raise ContractError("prediction closure differs from independent inputs or inventory")
        failed = terminal["status"] == "failed"
        if complete and failed:
            raise ContractError("prediction attempt did not complete")
        if failed:
            if terminal["result"] is not None or terminal["result_digest"] is not None or not all(type(terminal[k]) is str for k in ("error_type", "error")):
                raise ContractError("prediction failure terminal is invalid")
        elif terminal["error"] is not None or terminal["error_type"] is not None:
            raise ContractError("prediction success carries a failure")
        replay = _ReplayRecords(run_id, entries)
        replay.initialize(task, controls, experiment_id, variant)
        responses = [(r.data()["kind"], r.data()["data"]) for r in entries if r.data()["kind"] in {"callback_raw", "callback_failure"}]
        result = None
        try:
            result = _evaluate_prediction_scenario(experiment_id, variant, task=task, frozen_controls=controls,
                writer=replay, replay_responses=responses)
        except (_ReplayEnd, _RecordedFailure):
            if not failed:
                raise ContractError("prediction completed output lacks allocated operations")
        except ContractError:
            # Invalid captured JSON is allowed only as an exact failed prefix.
            if not failed or len(replay.entries) != len(entries):
                raise
        if len(replay.entries) != len(entries) or responses:
            raise ContractError("prediction journal contains unconsumed semantic records")
        if not failed and (result is None or terminal["result"] != result.record.data() or terminal["result_digest"] != result.record.content_hash):
            raise ContractError("prediction result differs from reconstructed fixture")
        if _inventory(root) != files or _sources() != expected_inputs.data()["sources"]:
            raise ContractError("prediction artifacts changed during verification")
        return FrozenRecord.from_dict({"schema": "prediction-scenario-artifact-check-v2", "run_id": run_id,
            "callback_count": sum(r.data()["kind"] == "callback_request" for r in entries),
            "status": terminal["status"], "storage_integrity_verified": True,
            "semantic_completion_verified": not failed, "scientific_validated": False})
    except ContractError:
        raise
    except (OSError, KeyError, TypeError, ValueError, UnicodeError, IndexError, _ReplayEnd) as exc:
        raise ContractError("prediction artifacts are malformed") from exc
