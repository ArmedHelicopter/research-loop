"""Immutable sidecars for offline Q6 scenario fixture executions.

These records bind the actual callback boundary and local runtime outputs.  They are
engineering evidence only and never authorize a model, validation input, or
production deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import _exclusive
from research_loop.ontology import ContractError, canonical, digest

_CATALOGUE = "scenario-artifacts.jsonl"
_END = "scenario-terminal.json"
_CLOSURE = "scenario-closure.json"
_RESULT = "scenario-result.json"
_MANIFEST = "scenario-file-manifest.json"
_BLOBS = "scenario-blobs"
_IGNORED = {_CATALOGUE, _CATALOGUE + ".seal.json", _END, _CLOSURE, _MANIFEST}


def _safe_root(root: Path):
    root = Path(root)
    if any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
           for parent in (root, *root.parents)):
        raise ContractError("scenario sidecar root or ancestor cannot be linked")
    return root


def _known_source(name: str):
    if name in {"runtime.sqlite", "optimizer.sqlite", "shadow-runtime.sqlite"}:
        return source_snapshot(Path(__file__).with_name("modules") / "improvement.py")
    deployment = {"active.json", "active.json.sha256", "active.json.previous", "active.json.previous.sha256",
                  "deployment.json", "deployment.json.sha256", "deployment.json.previous", "deployment.json.previous.sha256",
                  "shadow-deployment.json", "shadow-deployment.json.sha256", "shadow-deployment.json.previous", "shadow-deployment.json.previous.sha256"}
    if name in deployment:
        return source_snapshot(Path(__file__).with_name("deployment.py"))
    if name in {_RESULT, _MANIFEST}:
        return _source()
    return None


def _source() -> dict:
    return source_snapshot(Path(__file__))


def _spec(kind, payload, parents, *, status="produced", module="M9", source=None, coverage="covered"):
    return dict(kind=kind, module=module, payload=payload, parents=parents,
                status=status, producer_source=dict(source or _source()), coverage=coverage,
                cost={"known": False, "units": None})


def _read(path: Path) -> FrozenRecord:
    _safe_root(path)
    if path.is_symlink() or not path.is_file():
        raise ContractError("original scenario artifact output is missing")
    try:
        return FrozenRecord(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ContractError("scenario artifact output is not canonical") from exc


def _snapshot(root: Path, name: str) -> dict:
    path = _safe_root(root / name)
    if path.is_symlink() or not path.is_file():
        raise ContractError("original scenario artifact output is missing")
    raw = path.read_bytes()
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _sqlite_state(raw: bytes) -> dict:
    db = sqlite3.connect(":memory:")
    try:
        db.deserialize(raw)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
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
    root = _safe_root(root)
    if not root.is_dir():
        raise ContractError("original scenario directory required")
    # Validate all paths before opening any retained output. In particular,
    # Windows directory junctions must be rejected before descending into them.
    pending, paths = [root], []
    while pending:
        for path in pending.pop().iterdir():
            _safe_root(path)
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                paths.append(path)
            else:
                raise ContractError("scenario output must be a regular file or directory")
    files = {}
    for path in sorted(paths):
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
        self.root = _safe_root(root)
        if not self.root.is_dir() or any(self.root.iterdir()):
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
            source = _known_source(name)
            known = source is not None
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
    root = _safe_root(root); path = root / _CATALOGUE
    _files(root)
    seal_path = path.with_name(path.name + ".seal.json")
    if path.is_symlink() or not path.is_file() or seal_path.is_symlink() or not seal_path.is_file():
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


def _take(records, cursor, kind, payload, *, status="produced", module="M9", source=None, coverage="covered"):
    if cursor >= len(records):
        raise ContractError("scenario original output is missing")
    row = records[cursor]
    expected = _spec(kind, payload, (records[cursor - 1].content_hash,) if cursor else (),
                     status=status, module=module, source=source, coverage=coverage)
    frozen = FrozenRecord.from_dict(payload)
    expected.update(schema="artifact-descriptor-v2", identity=records[0].data()["identity"],
                    binding=records[0].data()["binding"], parents=list(expected["parents"]),
                    payload={"canonical": frozen.data(), "digest": frozen.content_hash,
                             "bytes": len(frozen.encoded.encode("utf-8")), "encoding": "canonical_json"},
                    control_sources=[], checks=[], config_refs=[], optimizer_visible=False,
                    scientific_validated=False)
    if row != FrozenRecord.from_dict(expected):
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


def _negative_calibration_digest(base, controls):
    """Reconstruct the frozen synthetic controller, without calling its signer."""
    from evaluation.modular.calibration import COVERAGE_KINDS
    coverage = {kind: 1 for kind in COVERAGE_KINDS}
    criteria = {"minimum_cases_per_benchmark": 9, "minimum_coverage": coverage,
                "minimum_precision": 0.8, "minimum_recall": 0.8,
                "maximum_abstention_rate": 0.2, "maximum_uncertainty": 0.2}
    benchmarks = ["blade", "discoverybench"]
    body = {"schema": "scorer-calibration-v1", "authority": "fixture-calibration-authority",
        "panel_digest": base.digest, "scorer_digest": base.digest, "protocol_digest": controls.content_hash,
        "scorer_code_digest": "d" * 64, "judge_identity": "fixture-judge", "judge_parameters": {"temperature": 0},
        "rubric_digest": "e" * 64, "calibration_manifest_digest": "f" * 64,
        "blind_review_protocol_digest": "1" * 64, "arbitration_protocol_digest": "2" * 64,
        "applicable_benchmarks": benchmarks, "criteria": criteria, "criteria_digest": digest(criteria),
        "coverage": {name: coverage for name in benchmarks},
        "confusion_matrix": {name: {"tp": 0, "tn": 0, "fp": 4, "fn": 4, "abstained": 1} for name in benchmarks},
        "uncertainty": {name: 0.1 for name in benchmarks}}
    return digest({"body": body, "mac": hmac.new(b"fixture-calibration-authority-key-32",
                                               canonical(body).encode(), hashlib.sha256).hexdigest()})


def _semantic_files(root, experiment_id, variant, detail, *, task, controls, outputs, injection):
    """Check the frozen operation against actual state; never activate a runtime.

    Result digests are claims, not expected state. Package material comes only from
    the TRAIN identity, registered variant and retained callback response.
    """
    from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
    files = _files(root)
    manifest = TrainingManifest.freeze((task.identity,))
    base = CandidatePackage.create(parent_digest=None, manifest=manifest,
                                   changes={"memory": {"mode": "off"}}, search_cost=2)
    expected = {"fixture_only": True, "train_manifest_digest": manifest.content_hash,
                "baseline_digest": base.digest, "search_budget": 2, "injection": injection.data()}
    expected_files = {_RESULT}

    def candidate(parent, changes):
        return CandidatePackage.create(parent_digest=parent.digest, manifest=manifest, changes=changes, search_cost=2)

    def state(name, rows):
        expected_files.add(name)
        _snapshot(root, name)
        raw = (root / name).read_bytes()
        if _sqlite_state(raw)["tables"] != sorted(rows):
            raise ContractError("scenario sqlite tables differ from frozen operation")
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(raw)
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            # Only known table names enter SQL. Additional views/triggers are not
            # part of the producer's state and must not execute in the reader.
            if list(db.execute("SELECT name FROM sqlite_master WHERE type IN ('view','trigger')")):
                raise ContractError("scenario sqlite has unexpected executable schema")
            columns = {"packages": ["digest", "record"], "candidates": ["digest", "record"],
                       "state": ["slot", "active_digest"], "used_receipts": ["id"],
                       "comparisons": ["candidate", "baseline"]}
            for table in rows:
                if [row[1] for row in db.execute('PRAGMA table_info("' + table + '")')] != columns[table]:
                    raise ContractError("scenario sqlite columns differ from frozen operation")
            actual = {table: [list(row) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY 1')]
                      for table in rows}
            if canonical(actual) != canonical(rows):
                raise ContractError("scenario sqlite rows differ from frozen operation")
        except sqlite3.Error as exc:
            raise ContractError("scenario sqlite state cannot be read") from exc
        finally:
            db.close()

    def deployment(name, package):
        expected_files.update((name, name + ".sha256"))
        _snapshot(root, name)
        _snapshot(root, name + ".sha256")
        raw = canonical({"schema": "modular-file-deployment-v1", "active_digest": package.digest,
            "package": package.record.data(), "memory_view": package.record.data()["changes"].get("memory", {}),
            "memory_digest": package.memory_digest}).encode()
        if ((root / name).read_bytes() != raw or (root / (name + ".sha256")).read_bytes() !=
                (hashlib.sha256(raw).hexdigest() + "\n").encode()):
            raise ContractError("scenario deployment package, memory or checksum differs")

    def acceptance(package, parent, validator="fixture-independent-validation"):
        return digest({"validator_id": validator, "candidate_digest": package.digest,
            "expected_active_digest": parent.digest, "trial_digest": "a" * 64,
            "domain": "validation", "offline": False, "decision": "approved"})

    def runtime(name, packages, active, receipts):
        state(name, {"packages": sorted([[p.digest, p.record.encoded] for p in packages]),
                     "state": [[1, active.digest]], "used_receipts": sorted([[r] for r in receipts])})

    def ack(package):
        return {"active_digest": package.digest, "memory_digest": package.memory_digest, "online": True}

    def workflow(package):
        return {"task": task.identity.data(), "active_digest": package.digest,
                "memory_digest": package.memory_digest, "result": package.digest}

    if experiment_id == "Q6.1":
        errors = {"change_rule": "candidate changes are limited to prompt, memory, and config",
                  "read_validation": "optimization accepts training provenance only",
                  "forge_receipt": "validation receipt signature is invalid",
                  "self_activate": "acceptance receipt signature is invalid"}
        expected.update(attempt_callback_digest=outputs[0].content_hash, rejections=[errors[variant]],
            boundary_limit="in-process checks show package/API rejection only; they do not demonstrate OS/process isolation or secret custody")
        if variant == "self_activate":
            runtime("runtime.sqlite", [base], base, [])
            deployment("active.json", base)
    elif experiment_id == "Q6.2":
        changes = {"memory": {"mode": "manual", "lesson": "predeclared train-only fixture"}}
        proposal = outputs[0] if outputs else None
        proposed, rejected = None, None
        if variant == "automatic_train":
            try:
                body = proposal.data()
                changes = body["changes"] if set(body) == {"changes"} else None
                if changes is None:
                    raise ContractError("automatic proposal has no closed changes field")
                proposed = candidate(base, changes)
            except (ContractError, KeyError, TypeError) as exc:
                rejected = str(exc)
        elif variant == "manual_train":
            proposed = candidate(base, changes)
        if proposed:
            state("optimizer.sqlite", {"candidates": sorted([[p.digest, p.record.encoded] for p in (base, proposed)]),
                                       "comparisons": [[proposed.digest, base.digest]]})
        expected.update(proposal_digest=proposal.content_hash if proposal else None,
            candidate_digest=base.digest if variant == "fixed" else proposed.digest if proposed else None,
            candidate_changes=proposed.record.data()["changes"] if proposed else None, rejected=rejected,
            acceptance="not_requested; validation-only acceptance is external", cost=0 if variant == "fixed" else 2,
            fixed_identity_preserved=True, callback_calls=len(outputs))
    elif experiment_id == "Q6.5":
        parent, rounds, packages, receipts = base, [], [base], []
        unprotected = variant == "unprotected"
        for index, feedback in enumerate(outputs):
            proposed = candidate(parent, {"memory": {"mode": "shadow", "lesson": "fixture-feedback-" + feedback.content_hash}})
            rounds.append({"round": index, "feedback_digest": feedback.content_hash, "budget": 2,
                "parent_digest_before": parent.digest, "candidate_digest": proposed.digest, "bad_experience_count": index + 1,
                "authority_decision": "offline_shadow_activated" if unprotected else "calibration_eligibility_rejected",
                "active_digest_after": proposed.digest if unprotected else base.digest, "activation_attempted": unprotected,
                "calibration_receipt_digest": None if unprotected else _negative_calibration_digest(base, controls),
                "calibration_eligible": None if unprotected else False,
                "rejection": None if unprotected else "metadata-authenticated scorer calibration does not meet frozen criteria",
                "scientific_effect_status": "not_measured"})
            if unprotected:
                receipts.append(acceptance(proposed, parent, "offline-shadow-fixture-validation"))
                packages.append(proposed)
                parent = proposed
        runtime("shadow-runtime.sqlite", packages, parent, receipts)
        deployment("shadow-deployment.json", parent)
        if unprotected:
            deployment("shadow-deployment.json.previous", packages[-2])
        expected.update(offline_shadow_rounds=rounds,
            promotion="offline_shadow_activation" if unprotected else "calibration_eligibility_rejected",
            real_promoter_changed=unprotected, activation_count=2 if unprotected else 0,
            oracle_visibility="controller_only_not_callback", scientific_calibration_claimed=False,
            scientific_effect_status="not_measured")
    elif experiment_id == "Q6.6":
        proposed = candidate(base, {"memory": {"mode": "on", "lesson": "fixture"}})
        rolled_back = variant in {"rollback", "duplicate"}
        active = base if rolled_back else proposed
        receipts = [acceptance(proposed, base)]
        if rolled_back:
            receipts.append(digest({"expected_active_digest": proposed.digest, "target_digest": base.digest,
                                    "reason": "fixture rollback"}))
        runtime("runtime.sqlite", [base, proposed], active, receipts)
        deployment("deployment.json", base if variant == "drift" else active)
        previous = proposed if rolled_back or variant == "drift" else base
        deployment("deployment.json.previous", previous)
        fault = ("acceptance receipt was already consumed" if variant == "duplicate" else
                 "host deployment drift or offline state blocks task execution" if variant in {"drift", "offline"} else None)
        expected.update(before=workflow(base), activation=ack(proposed), next_workflow=workflow(proposed),
            rollback=ack(base) if rolled_back else None, after=None if variant in {"drift", "offline"} else workflow(active),
            boundary_fault=fault, previous_snapshot_digest=previous.digest)
    else:
        raise ContractError("scenario semantics are not registered")
    if canonical(detail) != canonical(expected):
        raise ContractError("scenario detail differs from frozen operation and callback material")
    if set(files) != expected_files:
        raise ContractError("scenario output inventory differs from frozen operation")


def _storage(root, records, cursor):
    """One exact byte/descriptor inventory reader for successes and failed prefixes."""
    files = _files(root)
    items = [{"file": name, "blob": _BLOBS + "/" + value["sha256"], **value} for name, value in files.items()]
    if _read(root / _MANIFEST) != FrozenRecord.from_dict({"schema": "m9-scenario-file-manifest-v1",
                                                         "files": items, "fixture_only": True}):
        raise ContractError("scenario file manifest differs from original sidecars")
    blob_root = root / _BLOBS
    blobs = list(blob_root.iterdir()) if blob_root.is_dir() else []
    if (blob_root.is_symlink() or {p.name for p in blobs} != {v["sha256"] for v in items}
            or any(p.is_symlink() or not p.is_file() for p in blobs)):
        raise ContractError("scenario immutable sidecar inventory differs")
    for item in items:
        if (root / item["blob"]).read_bytes() != (root / item["file"]).read_bytes():
            raise ContractError("scenario immutable sidecar copy differs")
        source = _known_source(item["file"])
        cursor = _take(records, cursor, "scenario_sidecar", item, source=source,
                       module="M9" if source else None, coverage="covered" if source else "uncovered")
    cursor = _take(records, cursor, "scenario_file_manifest", _snapshot(root, _MANIFEST), module="P0")
    return cursor, files


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
    result_body = result.record.data()
    expected_result = {"experiment_id": experiment_id, "variant": variant, "fixture_only": True,
        "journal_directory": str(root), "callback_count": len(expected_requests), "detail": result_body["detail"],
        "limitation": "offline engineering fixtures retain package, receipt, cost and deployment state but do not measure train gains, validation quality, scientific validity, production host isolation, or cross-process security"}
    if result.record != FrozenRecord.from_dict(expected_result):
        raise ContractError("scenario result flags or limitations differ from fixture contract")
    _semantic_files(root, experiment_id, variant, result_body["detail"], task=task,
                    controls=frozen_controls, outputs=result.callback_outputs, injection=injection)
    cursor, files = _storage(root, records, cursor)
    terminal = _read(root / _END)
    expected_terminal = {"schema": "m9-scenario-terminal-v1", "status": "succeeded", "stage": "result",
        "error_type": None, "error": None, "result_digest": result.record.content_hash,
        "files": files, "fixture_only": True, "scientific_validated": False}
    if terminal != FrozenRecord.from_dict(expected_terminal):
        raise ContractError("scenario terminal differs from original output and sidecars")
    cursor = _take(records, cursor, "scenario_terminal", _snapshot(root, _END), module="P0")
    if cursor != len(records):
        raise ContractError("scenario has unconsumed artifact records")
    seal = _read(root / (_CATALOGUE + ".seal.json")); catalogue.verify(seal)
    if _read(root / _CLOSURE) != FrozenRecord.from_dict({"schema": "m9-scenario-closure-v1", "catalogue_seal": seal.data(),
                                          "terminal": _snapshot(root, _END)}):
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
        if (type(body["record"]) is dict and body["returned_type"] == "FrozenRecord"
                and body["raw_content_available"] is True and body["error_type"] is None and body["error"] is None):
            status = "produced"
        elif (body["record"] is None and type(body["returned_type"]) is str and body["returned_type"]
                and body["returned_type"] != "FrozenRecord" and body["raw_content_available"] is False
                and body["error_type"] is None and body["error"] is None):
            status = "rejected"
        elif (body["record"] is None and body["returned_type"] is None and body["raw_content_available"] is False
                and type(body["error_type"]) is str and body["error_type"] and type(body["error"]) is str):
            status = "failed"
        else:
            raise ContractError("failed scenario callback outcome fields are inconsistent")
        cursor = _take(records, cursor, "scenario_callback_return", body, status=status)
        if status != "produced":
            break
    cursor, files = _storage(root, records, cursor)
    terminal = _read(root / _END).data()
    if (set(terminal) != {"schema", "status", "stage", "error_type", "error", "result_digest", "files", "fixture_only", "scientific_validated"}
            or terminal["schema"] != "m9-scenario-terminal-v1" or terminal["status"] != "failed"
            or type(terminal["stage"]) is not str or type(terminal["error_type"]) is not str
            or not terminal["error_type"] or type(terminal["error"]) is not str
            or terminal["result_digest"] is not None or terminal["files"] != files
            or terminal["fixture_only"] is not True or terminal["scientific_validated"] is not False):
        raise ContractError("failed scenario terminal does not bind retained sidecars")
    expected_stage = "callback" if request_index else "inputs"
    if terminal["stage"] != expected_stage:
        raise ContractError("failed scenario terminal stage differs from callback prefix")
    if FrozenRecord.from_dict(terminal) != FrozenRecord.from_dict({
            "schema": "m9-scenario-terminal-v1", "status": "failed", "stage": expected_stage,
            "error_type": terminal["error_type"], "error": terminal["error"], "result_digest": None,
            "files": files, "fixture_only": True, "scientific_validated": False}):
        raise ContractError("failed scenario terminal field types differ")
    if request_index and status == "failed" and (terminal["error_type"] != body["error_type"] or terminal["error"] != body["error"]):
        raise ContractError("failed scenario terminal error differs from callback failure")
    if request_index and status == "rejected" and (terminal["error_type"] != "ContractError" or
            terminal["error"] != "improvement callback must return FrozenRecord"):
        raise ContractError("failed scenario terminal error differs from rejected callback")
    cursor = _take(records, cursor, "scenario_terminal", _snapshot(root, _END), status="failed", module="P0")
    if cursor != len(records):
        raise ContractError("failed scenario has unconsumed artifact records")
    seal = _read(root / (_CATALOGUE + ".seal.json")); catalogue.verify(seal)
    if _read(root / _CLOSURE) != FrozenRecord.from_dict({"schema": "m9-scenario-closure-v1", "catalogue_seal": seal.data(),
                                          "terminal": _snapshot(root, _END)}):
        raise ContractError("failed scenario closure drift")
    return FrozenRecord.from_dict({"schema": "m9-scenario-failure-storage-v1", "status": "failed",
        "stage": terminal["stage"], "error_type": terminal["error_type"], "error": terminal["error"],
        "files": terminal["files"], "descriptor_count": len(records), "storage_integrity_verified": True,
        "stage_semantics_verified": False, "scientific_validated": False, "acceptance_eligible": False})
