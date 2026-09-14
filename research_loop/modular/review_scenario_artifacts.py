"""Append-only, fixture-only Q4 review provenance."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError, canonical

_INPUTS = "review-inputs.json"
_ATTEMPTS = "review-attempts.jsonl"
_OUTPUTS = "review-outputs.json"
_TERMINAL = "review-terminal.json"
_FILES = frozenset({_INPUTS, _ATTEMPTS, _OUTPUTS, _TERMINAL})


def _plain(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try: info = part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ContractError("review artifact path traverses a link")
    return path


def _write_new(path: Path, record: FrozenRecord) -> None:
    with _plain(path).open("xb") as stream:
        stream.write((record.encoded + "\n").encode("utf-8")); stream.flush(); os.fsync(stream.fileno())


def _append(path: Path, value: Mapping[str, Any]) -> None:
    with _plain(path).open("ab") as stream:
        stream.write((canonical(dict(value)) + "\n").encode("utf-8")); stream.flush(); os.fsync(stream.fileno())


def _record(path: Path) -> FrozenRecord:
    raw = _plain(path).read_bytes()
    if not raw.endswith(b"\n"): raise ContractError("review artifact record has an incomplete tail")
    try: return FrozenRecord(raw[:-1].decode("utf-8"))
    except UnicodeDecodeError as exc: raise ContractError("review artifact record is not utf-8") from exc


def _rows(path: Path) -> list[dict[str, Any]]:
    raw = _plain(path).read_bytes()
    if not raw.endswith(b"\n"): raise ContractError("review artifact attempt journal has an incomplete tail")
    try: rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ContractError("review artifact attempt journal is malformed") from exc
    if any(type(row) is not dict for row in rows) or raw != b"".join((canonical(row) + "\n").encode("utf-8") for row in rows):
        raise ContractError("review artifact attempt journal is not canonical")
    return rows


def inventory(root: Path, *, include_terminal: bool = True) -> dict[str, dict[str, Any]]:
    root = _plain(root)
    if not root.is_dir(): raise ContractError("review artifact root is missing")
    rows = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs: _plain(Path(directory) / name)
        for name in names:
            path = _plain(Path(directory) / name); relative = path.relative_to(root).as_posix()
            if include_terminal or relative != _TERMINAL:
                rows[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    return dict(sorted(rows.items()))


class ReviewArtifactSession:
    """Writes the producer-side audit before any callback opportunity exists."""
    def __init__(self, root: Path, *, task: PublicTask, controls: FrozenRecord, experiment_id: str, variant: str) -> None:
        self.root = _plain(Path(root))
        if self.root.exists(): raise ContractError("review artifact root must be new")
        self.root.mkdir(parents=True); self._closed = False; self._sequence = 1
        self.sources = {"scenario": source_snapshot(Path(__file__).with_name("scenarios_review.py")), "artifact_writer": source_snapshot(Path(__file__))}
        _write_new(self.root / _INPUTS, FrozenRecord.from_dict({"schema": "q4-review-artifact-inputs-v2", "fixture_only": True,
            "task": task.data(), "cell": task.identity.data(), "controls": controls.data(), "experiment_id": experiment_id, "variant": variant, "sources": self.sources}))
        _append(self.root / _ATTEMPTS, {"sequence": 0, "event": "audit_open", "task_digest": task.content_hash, "controls_digest": controls.content_hash, "fixture_only": True})
    def _event(self, event: str, **data: Any) -> None:
        if self._closed: raise ContractError("review artifact audit is already closed")
        _append(self.root / _ATTEMPTS, {"sequence": self._sequence, "event": event, **data}); self._sequence += 1
    def reserve(self, allocation: Mapping[str, Any]) -> None: self._event("callback_reserved", allocation=dict(allocation), reserved_before_callback=True)
    def callback_payload(self, payload: FrozenRecord) -> None: self._event("callback_payload", payload=payload.data(), payload_digest=payload.content_hash)
    def callback_response(self, *, raw: FrozenRecord, typed: FrozenRecord, candidate: Mapping[str, Any] | None) -> None:
        self._event("callback_response", raw_response=raw.data(), raw_digest=raw.content_hash, typed_response=typed.data(), typed_digest=typed.content_hash, prediction_candidate=dict(candidate) if candidate is not None else None)
    def review_event(self, event: FrozenRecord) -> None: self._event("review_engine_event", review_event=event.data(), review_event_digest=event.content_hash)
    def complete(self, result: Any) -> None:
        _write_new(self.root / _OUTPUTS, FrozenRecord.from_dict({"schema": "q4-review-artifact-outputs-v2", "fixture_only": True,
            "result": result.record.data(), "mechanism_trace": result.mechanism_trace.data(), "callback_payloads": [x.data() for x in result.callback_payloads], "callback_responses": [x.data() for x in result.callback_responses]}))
        self._terminal("succeeded", None)
    def fail(self, exc: BaseException) -> None:
        if not self._closed:
            self._event("producer_failure", exception_type=type(exc).__name__, message=str(exc)); self._terminal("failed", {"exception_type": type(exc).__name__, "message": str(exc)})
    def _terminal(self, status: str, failure: dict[str, str] | None) -> None:
        _write_new(self.root / _TERMINAL, FrozenRecord.from_dict({"schema": "q4-review-artifact-terminal-v2", "fixture_only": True, "status": status, "failure": failure, "files": inventory(self.root, include_terminal=False), "scientific_validated": False})); self._closed = True


def verify_review_artifacts(root: Path, *, task: PublicTask, controls: FrozenRecord, experiment_id: str, variant: str, result: Any | None = None) -> FrozenRecord:
    """Strict offline consumer: compare original producer files without replaying callbacks."""
    try:
        root = _plain(Path(root)); actual_files = inventory(root)
        if set(actual_files) != _FILES and set(actual_files) != {_INPUTS, _ATTEMPTS, _TERMINAL}: raise ContractError("review artifact literal file inventory differs")
        expected_sources = {"scenario": source_snapshot(Path(__file__).with_name("scenarios_review.py")), "artifact_writer": source_snapshot(Path(__file__))}
        expected_inputs = {"schema": "q4-review-artifact-inputs-v2", "fixture_only": True, "task": task.data(), "cell": task.identity.data(), "controls": controls.data(), "experiment_id": experiment_id, "variant": variant, "sources": expected_sources}
        if _record(root / _INPUTS).data() != expected_inputs: raise ContractError("review artifact task, cell, variant, controls, or producer source differs")
        attempts = _rows(root / _ATTEMPTS); _verify_attempts(attempts, task=task, controls=controls)
        terminal = _record(root / _TERMINAL).data()
        if terminal.get("files") != inventory(root, include_terminal=False) or terminal.get("scientific_validated") is not False: raise ContractError("review artifact terminal inventory differs")
        if terminal.get("status") == "failed":
            if terminal.get("failure") is None or (root / _OUTPUTS).exists(): raise ContractError("review artifact failed closure is malformed")
            return FrozenRecord.from_dict({"schema": "q4-review-artifacts-verified-v2", "status": "failed", "scientific_validated": False})
        if terminal.get("status") != "succeeded" or terminal.get("failure") is not None: raise ContractError("review artifact terminal status is malformed")
        outputs = _record(root / _OUTPUTS).data()
        if set(outputs) != {"schema", "fixture_only", "result", "mechanism_trace", "callback_payloads", "callback_responses"} or outputs["schema"] != "q4-review-artifact-outputs-v2" or outputs["fixture_only"] is not True: raise ContractError("review artifact outputs are malformed")
        if result is not None and (outputs["result"] != result.record.data() or outputs["mechanism_trace"] != result.mechanism_trace.data() or outputs["callback_payloads"] != [x.data() for x in result.callback_payloads] or outputs["callback_responses"] != [x.data() for x in result.callback_responses]): raise ContractError("review artifact outputs differ from the consumer result")
        _verify_semantics(attempts, outputs, task=task, controls=controls, experiment_id=experiment_id, variant=variant)
        return FrozenRecord.from_dict({"schema": "q4-review-artifacts-verified-v2", "status": "succeeded", "attempts": len(attempts), "scientific_validated": False})
    except ContractError: raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc: raise ContractError("review artifacts are incomplete or malformed") from exc


def _verify_attempts(rows: list[dict[str, Any]], *, task: PublicTask, controls: FrozenRecord) -> None:
    if not rows or rows[0] != {"sequence": 0, "event": "audit_open", "task_digest": task.content_hash, "controls_digest": controls.content_hash, "fixture_only": True}: raise ContractError("review artifact audit does not bind independent inputs")
    reservations, outstanding = set(), None
    for index, row in enumerate(rows):
        if row.get("sequence") != index or type(row.get("event")) is not str: raise ContractError("review artifact attempt sequence differs")
        event = row["event"]
        if event == "callback_reserved":
            allocation = row.get("allocation")
            if set(row) != {"sequence", "event", "allocation", "reserved_before_callback"} or not isinstance(allocation, dict) or set(allocation) != {"phase", "role_id", "fixture_units"} or row["reserved_before_callback"] is not True: raise ContractError("review callback reservation is malformed")
            key = (allocation["phase"], allocation["role_id"])
            if key in reservations or outstanding is not None: raise ContractError("review callback reservation order differs")
            reservations.add(key); outstanding = key
        elif event == "callback_payload":
            if outstanding is None or set(row) != {"sequence", "event", "payload", "payload_digest"} or FrozenRecord.from_dict(row["payload"]).content_hash != row["payload_digest"]: raise ContractError("review callback payload lacks a prior reservation")
        elif event == "callback_response":
            if outstanding is None or set(row) != {"sequence", "event", "raw_response", "raw_digest", "typed_response", "typed_digest", "prediction_candidate"}: raise ContractError("review callback response is malformed")
            if FrozenRecord.from_dict(row["raw_response"]).content_hash != row["raw_digest"] or FrozenRecord.from_dict(row["typed_response"]).content_hash != row["typed_digest"]: raise ContractError("review callback response digest differs")
            outstanding = None
        elif event == "review_engine_event":
            if set(row) != {"sequence", "event", "review_event", "review_event_digest"} or FrozenRecord.from_dict(row["review_event"]).content_hash != row["review_event_digest"]: raise ContractError("review engine journal event differs")
        elif event == "producer_failure":
            if set(row) != {"sequence", "event", "exception_type", "message"} or type(row["exception_type"]) is not str or type(row["message"]) is not str: raise ContractError("review producer failure is malformed")
        elif event != "audit_open": raise ContractError("review artifact event is unrecognized")


def _verify_semantics(rows: list[dict[str, Any]], outputs: dict[str, Any], *, task: PublicTask, controls: FrozenRecord, experiment_id: str, variant: str) -> None:
    """Rebuild allowed fixture requests and consume the persisted M5 journal in memory only."""
    from research_loop.modular.modules.review import ReviewEngine
    from research_loop.modular.scenarios_review import _design, _freeze_call_plan
    roles, costs, visibility, case = _design(experiment_id, variant)
    plan = _freeze_call_plan(experiment_id, variant, roles, costs)
    payload_rows = [row for row in rows if row["event"] == "callback_payload"]
    response_rows = [row for row in rows if row["event"] == "callback_response"]
    engine_rows = [row["review_event"] for row in rows if row["event"] == "review_engine_event"]
    expected_phases = [(item["phase"], item["role_id"]) for item in plan]
    if len(payload_rows) != len(plan) or len(response_rows) != len(plan): raise ContractError("review callback journal omits a planned opportunity")
    review_id = None
    for index, (payload_row, expected) in enumerate(zip(payload_rows, expected_phases)):
        payload = payload_row["payload"]
        phase, role_id = expected
        if (payload.get("task") != task.data() or payload.get("frozen_controls") != controls.data() or payload.get("fixture_only") is not True
                or payload.get("public_case") != case or payload.get("invocation") != phase or payload.get("role") != next(role for role in roles if role["role_id"] == role_id)):
            raise ContractError("review callback request differs from independent fixture inputs")
        if review_id is None: review_id = payload.get("review_id")
        if payload.get("review_id") != review_id: raise ContractError("review callback requests use different sessions")
        prior = payload.get("prior_visible_submission")
        if phase == "initial" and ((visibility == "sealed" and prior is not None) or (visibility == "sequential" and index == 0 and prior is not None)):
            raise ContractError("review initial visibility differs from registered variant")
        if phase == "revision" and not isinstance(prior, list): raise ContractError("review revision lacks revealed submissions")
    engine = ReviewEngine(task.identity)
    for event in engine_rows: engine._apply(event, persist=False)
    session = engine.session(review_id)
    if [role.data() for role in session.roles] != roles or session.task_binding != task.content_hash or session.evidence_snapshot != controls.data()["evidence_digest"]:
        raise ContractError("persisted review engine journal differs from independent inputs")
    revealed = engine.reveal(review_id)
    if len(revealed) != len(roles) or (experiment_id in {"Q4.3", "Q4.5"}) != bool(engine._revisions):
        raise ContractError("persisted reveal or revision journal differs from registered variant")
    typed = [row["typed_response"] for row in response_rows]
    if outputs["callback_payloads"] != [row["payload"] for row in payload_rows] or outputs["callback_responses"] != typed:
        raise ContractError("review outputs do not retain original callback records")
    record = outputs["result"]
    if record.get("callback_plan") != plan or record.get("callback_payload_digests") != [FrozenRecord.from_dict(row["payload"]).content_hash for row in payload_rows] or record.get("callback_response_digests") != [FrozenRecord.from_dict(value).content_hash for value in typed]:
        raise ContractError("review result does not bind original callback contents")
    trace = outputs["mechanism_trace"].get("events")
    if not isinstance(trace, list) or not any(event.get("event") == "sealed_barrier_revealed" for event in trace) or not any(event.get("event") == "independent_fixture_oracle" for event in trace) or not any(event.get("event") == "callback_prediction_extraction" for event in trace):
        raise ContractError("review reveal, score, or prediction extraction output is missing")
