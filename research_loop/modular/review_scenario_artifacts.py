"""Durable fixture provenance with complete, memory-only Q4 event replay."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical

_INPUTS = "review-inputs.json"
_ATTEMPTS = "review-attempts.jsonl"
_OUTPUTS = "review-outputs.json"
_TERMINAL = "review-terminal.json"
_EXTERNAL = "review-engine-log.jsonl"


def _plain(path):
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ContractError("review artifact path traverses a link")
    return path


def _write_bytes_new(path, raw):
    with _plain(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_new(path, record):
    _write_bytes_new(path, (record.encoded + "\n").encode("utf-8"))


def _record(path):
    raw = _plain(path).read_bytes()
    record = FrozenRecord(raw.decode("utf-8").strip())
    if raw != (record.encoded + "\n").encode("utf-8"):
        raise ContractError("review artifact record is incomplete or noncanonical")
    return record


def _rows(path):
    raw = _plain(path).read_bytes()
    rows = [FrozenRecord(line) for line in raw.decode("utf-8").splitlines()]
    if not rows or raw != _bytes(rows):
        raise ContractError("review artifact journal is incomplete or noncanonical")
    return rows


def _bytes(rows):
    return b"".join((row.encoded + "\n").encode("utf-8") for row in rows)


def inventory(root, *, include_terminal=True):
    root = _plain(root)
    if not root.is_dir():
        raise ContractError("review artifact root is missing")
    rows = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            _plain(Path(directory) / name)
        for name in names:
            path = _plain(Path(directory) / name)
            relative = path.relative_to(root).as_posix()
            if include_terminal or relative != _TERMINAL:
                raw = path.read_bytes()
                rows[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return dict(sorted(rows.items()))


def _sources():
    here = Path(__file__).parent
    paths = [Path(__file__), here / "scenarios_review.py", here / "contracts.py",
             here / "artifact_catalogue.py", here / "modules/review.py",
             here / "modules/predictions.py", here.parent / "ontology.py"]
    return [source_snapshot(_plain(path)) for path in paths]


def _inputs(task, controls, experiment_id, variant, identities, review_log_path):
    from research_loop.modular.scenarios_review import _design, _freeze_call_plan
    roles, costs, _, _ = _design(experiment_id, variant)
    return FrozenRecord.from_dict({"schema": "q4-review-artifact-inputs-v3", "fixture_only": True,
        "task": task.data(), "cell": task.identity.data(), "controls": controls.data(),
        "experiment_id": experiment_id, "variant": variant,
        "call_plan": _freeze_call_plan(experiment_id, variant, roles, costs),
        "reviewer_identities": identities,
        "review_log_path": str(review_log_path) if review_log_path is not None else None,
        "sources": _sources()})


def _raw_record(value):
    if type(value) is FrozenRecord:
        return {"encoding": "frozen_record", "value": value.data()}
    if value is None or isinstance(value, Mapping) or type(value) in (str, bool, int, float, list):
        try:
            return FrozenRecord.from_dict({"encoding": "json", "value": dict(value) if isinstance(value, Mapping) else value}).data()
        except (TypeError, ValueError, ContractError):
            pass
    return {"encoding": "unsupported_python", "type": type(value).__name__}


def _error(exc):
    return {"exception_type": type(exc).__name__, "message": str(exc)}


def _output(result):
    return FrozenRecord.from_dict({"schema": "q4-review-artifact-outputs-v3", "fixture_only": True,
        "result": result.record.data(), "mechanism_trace": result.mechanism_trace.data(),
        "callback_payloads": [x.data() for x in result.callback_payloads],
        "callback_responses": [x.data() for x in result.callback_responses]})


class _ReplayEnd(Exception):
    pass


class _RecordedFailure(Exception):
    pass


class _ReplayMismatch(ContractError):
    pass


class _Records:
    def __init__(self, run_id):
        self.run_id, self.entries, self.replay_responses = run_id, [], None

    def _event(self, event, **data):
        module = "M5" if event in {"review_engine_event", "review_reveal"} else "M4" if event in {"prediction_registry_event", "prediction_frozen_plan"} else "P0"
        record = FrozenRecord.from_dict({"sequence": len(self.entries), "event": event,
            "run_id": self.run_id, "module": module,
            "previous": self.entries[-1].content_hash if self.entries else None, **data})
        self._persist(record)
        self.entries.append(record)

    def _persist(self, record):
        pass

    def initialize(self, inputs):
        self.inputs = inputs
        self._event("audit_open", input_digest=inputs.content_hash, fixture_only=True)

    def reserve(self, allocation):
        self._event("callback_reserved", allocation=dict(allocation), reserved_before_callback=True)

    def callback_payload(self, payload):
        self._event("callback_payload", payload=payload.data(), payload_digest=payload.content_hash)

    def callback_raw(self, value):
        self._event("callback_raw", raw=_raw_record(value))

    def callback_response(self, *, typed, candidate):
        self._event("callback_response", typed_response=typed.data(), typed_digest=typed.content_hash,
                    prediction_candidate=candidate)

    def callback_failure(self, exc):
        self._event("callback_failure", **_error(exc))

    def review_event(self, event):
        self._event("review_engine_event", review_event=event.data(), review_event_digest=event.content_hash)

    def reveal_event(self, event):
        self._event("review_reveal", reveal=event.data(), reveal_digest=event.content_hash)

    def prediction_event(self, event):
        self._event("prediction_registry_event", prediction_event=event.data(), prediction_event_digest=event.content_hash)

    def prediction_plan(self, payload):
        self._event("prediction_frozen_plan", payload=payload.data(), payload_digest=payload.content_hash)

    def output(self, result):
        self._event("output", output=_output(result).data())

    def before_callback(self):
        pass

    def replay_response(self):
        if not self.replay_responses:
            raise _ReplayEnd()
        row = self.replay_responses.pop(0)
        if row["event"] == "callback_failure":
            if not all(type(row[key]) is str for key in ("exception_type", "message")):
                raise _ReplayMismatch("malformed retained callback failure")
            self._event("callback_failure", exception_type=row["exception_type"], message=row["message"])
            raise _RecordedFailure()
        raw = row["raw"]
        if set(raw) == {"encoding", "value"} and raw["encoding"] == "frozen_record":
            return FrozenRecord.from_dict(raw["value"])
        if set(raw) == {"encoding", "value"} and raw["encoding"] == "json":
            return raw["value"]
        if set(raw) == {"encoding", "type"} and raw["encoding"] == "unsupported_python" and type(raw["type"]) is str:
            self._event("callback_raw", raw=raw)
            raise _RecordedFailure()
        raise _ReplayMismatch("malformed retained raw value")


class ReviewArtifactSession(_Records):
    """Write exact input and attempt binding before the first callback."""
    def __init__(self, root, *, task, controls, experiment_id, variant, call_plan, identities, review_log_path):
        super().__init__(uuid4().hex)
        self.root, self._closed = _plain(root), False
        self.external = _plain(review_log_path) if review_log_path is not None else None
        if self.root.exists():
            raise ContractError("review artifact root must be new")
        if self.external is not None:
            if self.external.exists():
                raise ContractError("review log must be fresh")
            if self.external == self.root or self.root in self.external.parents:
                raise ContractError("external review log must be outside the artifact root")
        self.root.mkdir(parents=True)
        self.external_ready = False
        try:
            inputs = _inputs(task, controls, experiment_id, variant, identities, review_log_path)
            if call_plan != inputs.data()["call_plan"]:
                raise ContractError("review allocation plan differs from independent design")
            _write_new(self.root / _INPUTS, inputs)
            self.initialize(inputs)
        except BaseException as exc:
            self.fail(exc)
            raise

    def prepare_external(self):
        if self.external is not None:
            _plain(self.external.parent).mkdir(parents=True, exist_ok=True)
            _write_bytes_new(self.external, b"")
            self.external_ready = True

    def _external_bytes(self):
        return b"".join((canonical(r.data()["review_event"]) + "\n").encode("utf-8")
            for r in self.entries if r.data()["event"] == "review_engine_event")

    def _check_prefix(self):
        if _record(self.root / _INPUTS) != self.inputs:
            raise ContractError("review inputs changed during production")
        path = _plain(self.root / _ATTEMPTS)
        if (path.read_bytes() if path.exists() else b"") != _bytes(self.entries):
            raise ContractError("review journal changed during production")

    def _check_external(self):
        if self.external_ready and _plain(self.external).read_bytes() != self._external_bytes():
            raise ContractError("external review log changed during production")

    def _persist(self, record):
        if self._closed:
            raise ContractError("review artifact audit is already closed")
        self._check_prefix()
        with _plain(self.root / _ATTEMPTS).open("ab") as stream:
            stream.write((record.encoded + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    def before_callback(self):
        self._check_prefix()
        self._check_external()
        if _sources() != self.inputs.data()["sources"]:
            raise ContractError("review source changed before callback")

    def review_event(self, event):
        self._check_external()
        super().review_event(event)
        if self.external_ready:
            with _plain(self.external).open("ab") as stream:
                stream.write((event.encoded + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())

    def complete(self, result):
        self.before_callback()
        _write_new(self.root / _OUTPUTS, _output(result))
        self._terminal("succeeded", None)

    def fail(self, exc):
        # Failure closure must never overwrite partial writes or mask the cause.
        try:
            if self._closed or (self.root / _TERMINAL).exists():
                _write_new(self.root / "review-delivery-failure.json", FrozenRecord.from_dict(_error(exc)))
                return
            try:
                self._event("producer_failure", **_error(exc))
            except BaseException:
                pass
            self._terminal("failed", _error(exc))
        except BaseException:
            pass

    def _terminal(self, status, failure):
        if self.external_ready:
            _write_bytes_new(self.root / _EXTERNAL, _plain(self.external).read_bytes())
        _write_new(self.root / _TERMINAL, FrozenRecord.from_dict({"schema": "q4-review-artifact-terminal-v3",
            "fixture_only": True, "run_id": self.run_id, "input_digest": self.inputs.content_hash,
            "entry_count": len(self.entries), "status": status, "failure": failure,
            "files": inventory(self.root, include_terminal=False), "scientific_validated": False}))
        self._closed = True


class _ReplayRecords(_Records):
    def __init__(self, run_id, observed):
        super().__init__(run_id)
        self.observed = observed

    def _persist(self, record):
        if len(self.entries) >= len(self.observed):
            raise _ReplayEnd()
        if record != self.observed[len(self.entries)]:
            raise _ReplayMismatch("review semantic event differs from independently reconstructed fixture")


def verify_review_artifacts(root, *, task, controls, experiment_id, variant, result=None,
                            reviewer_identities=None, review_log_path=None, expected_run_id=None):
    """Read producer bytes and reconstruct every event; never open the external log.

    Failed attempts certify an exact retained prefix, not successful completion
    or the provenance of an arbitrary external exception's message.
    """
    from research_loop.modular.scenarios_review import _controls, _validate, _design, _identities, _evaluate_review_scenario
    try:
        _validate(experiment_id, variant)
        _controls(task, controls)
        task.identity.require_train()
        root = _plain(root)
        files = inventory(root)
        inputs = _record(root / _INPUTS)
        roles, _, _, _ = _design(experiment_id, variant)
        identities = _identities(roles, reviewer_identities, heterogeneous=(experiment_id == "Q4.5" and variant == "heterogeneous"))
        expected_inputs = _inputs(task, controls, experiment_id, variant, identities, review_log_path)
        if inputs != expected_inputs:
            raise ContractError("review artifact independent inputs or exact producer source differ")
        entries = _rows(root / _ATTEMPTS)
        run_id = entries[0].data()["run_id"]
        if type(run_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", run_id) or (expected_run_id is not None and run_id != expected_run_id):
            raise ContractError("review attempt binding differs")
        terminal = _record(root / _TERMINAL).data()
        if (set(terminal) != {"schema", "fixture_only", "run_id", "input_digest", "entry_count", "status", "failure", "files", "scientific_validated"}
                or terminal["schema"] != "q4-review-artifact-terminal-v3" or terminal["fixture_only"] is not True
                or terminal["scientific_validated"] is not False or terminal["run_id"] != run_id
                or terminal["input_digest"] != inputs.content_hash or terminal["entry_count"] != len(entries)
                or type(terminal["entry_count"]) is not int or terminal["status"] not in {"failed", "succeeded"}
                or terminal["files"] != inventory(root, include_terminal=False)):
            raise ContractError("review terminal binding or inventory differs")
        failed = terminal["status"] == "failed"
        expected_files = {_INPUTS, _ATTEMPTS, _TERMINAL}
        if not failed:
            expected_files.add(_OUTPUTS)
        if review_log_path is not None:
            expected_files.add(_EXTERNAL)
        if set(files) != expected_files:
            raise ContractError("review literal artifact inventory differs")
        semantic_entries = entries
        if failed:
            failure = terminal["failure"]
            if type(failure) is not dict or set(failure) != {"exception_type", "message"} or not all(type(v) is str for v in failure.values()):
                raise ContractError("review failure closure is malformed")
            semantic_entries = entries[:-1]
        elif terminal["failure"] is not None:
            raise ContractError("review succeeded attempt carries a failure")
        replay = _ReplayRecords(run_id, semantic_entries)
        replay.initialize(expected_inputs)
        replay.replay_responses = [r.data() for r in semantic_entries if r.data()["event"] in {"callback_raw", "callback_failure"}]
        reconstructed = None
        try:
            reconstructed = _evaluate_review_scenario(experiment_id, variant, task=task,
                frozen_controls=controls, reviewer_identities=reviewer_identities, audit=replay)
        except _ReplayMismatch:
            raise
        except (_ReplayEnd, _RecordedFailure):
            if not failed:
                raise ContractError("review completed attempt lacks allocated operations")
        except (ContractError, ValueError, TypeError, KeyError) as exc:
            if not failed or len(replay.entries) != len(semantic_entries):
                raise
            if _error(exc) != terminal["failure"]:
                raise ContractError("review retained invalid response failure differs") from exc
        if len(replay.entries) != len(semantic_entries) or replay.replay_responses:
            raise ContractError("review journal has unconsumed semantic records")
        if failed:
            replay.observed = entries
            replay._event("producer_failure", **terminal["failure"])
        else:
            if reconstructed is None or _record(root / _OUTPUTS) != _output(reconstructed):
                raise ContractError("review output differs from full deterministic reconstruction")
            if result is not None and _output(result) != _output(reconstructed):
                raise ContractError("review consumer result differs from reconstruction")
        if review_log_path is not None:
            expected_log = b"".join((canonical(r.data()["review_event"]) + "\n").encode("utf-8")
                for r in semantic_entries if r.data()["event"] == "review_engine_event")
            if _plain(root / _EXTERNAL).read_bytes() != expected_log:
                raise ContractError("archived actual external review log differs")
        if inventory(root) != files or _sources() != expected_inputs.data()["sources"]:
            raise ContractError("review artifacts or sources changed during verification")
        return FrozenRecord.from_dict({"schema": "q4-review-artifacts-verified-v3", "run_id": run_id,
            "status": terminal["status"], "attempts": len(entries), "storage_integrity_verified": True,
            "semantic_completion_verified": not failed, "scientific_validated": False})
    except ContractError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError, _ReplayEnd) as exc:
        raise ContractError("review artifacts are incomplete or malformed") from exc
