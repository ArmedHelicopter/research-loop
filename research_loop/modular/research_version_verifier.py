"""Read-only Q8.6 artifact consumption from independently retained inputs.

Replay uses recorded source items, never the provider. An external run ID is
optional for historical readers; without it the ID has only local consistency.
"""
from pathlib import Path
from types import SimpleNamespace

from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError


def _projection(bundle, events, enabled):
    from research_loop.modular.retrieval_panel_drivers import _docs, _select_sources
    docs = _docs(bundle["sources"])
    known = {FrozenRecord.from_dict(doc.data()).content_hash: doc for doc in docs}
    batches = []
    for row in events:
        if row["stage"] == "q8_retrieval_request":
            batches.append([])
        elif row["stage"] == "q8_retrieval_item":
            if not batches or row["data"].get("source_digest") not in known:
                raise ContractError("research version retrieval item is not in the frozen scenario")
            batches[-1].append(known[row["data"]["source_digest"]])
        elif row["stage"] == "q8_retrieval_failure":
            raise ContractError("completed research version contains failed retrieval")
    replay = []
    batches = iter(batches)
    provider = SimpleNamespace(search=lambda **_: iter(next(batches, ())))
    session = SimpleNamespace(_record=lambda stage, data: replay.append({"stage": stage, "data": data}))
    result, _ = _select_sources(provider, session, docs, bundle["query"], bundle["budget"], "Q8.2", "correct", enabled)
    observed = [{"stage": row["stage"], "data": row["data"]} for row in events if row["stage"].startswith("q8_retrieval_")]
    if replay != observed:
        raise ContractError("research version retrieval selection differs from recorded frozen items")
    return result


def verify_research_version_artifacts(sidecar, *, cell, scenario, identity, task_digest, lock, events, expected_run_id=None):
    try:
        return _verify(Path(sidecar), cell, scenario, identity, task_digest, lock, events, expected_run_id)
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OSError, StopIteration) as exc:
        raise ContractError("research version artifacts are incomplete or malformed") from exc


def _verify(sidecar, cell, scenario, identity, task_digest, lock, events, expected_run_id):
    from research_loop.modular.research_versions import _safe, _snapshot, _source_pins, _PARENT, _CHILD, _INPUTS
    from research_loop.modular.m6_public_inputs import M6PublicInputBoundary
    from research_loop.modular.panel_receipts import opaque_panel_cell_binding
    _safe(sidecar)
    if (not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or cell.identity != identity or cell.task_digest != task_digest or cell.coverage_id != "Q8.6"):
        raise ContractError("research version caller scenario does not match the expected panel cell")
    body = scenario.data()
    controller = body["controller_input"]
    bundle = controller["bundle"]
    if (body["experiment_id"] != "Q8.6" or body["variant"] != cell.variant
            or controller["schema"] != "retrieval-final-controller-v1" or bundle["schema"] != "retrieval-final-bundle-v1"
            or bundle["task_digest"] != task_digest or bundle["identity"] != identity.data()
            or body["base"]["evidence"] != FrozenRecord.from_dict(bundle).content_hash):
        raise ContractError("research version independent scenario binding differs")
    if (any(sidecar.glob("research-version-*.json.partial")) or (sidecar / "audit-failure.json").exists()
            or (sidecar / "research-version-failure.json").exists()):
        raise ContractError("research version has an incomplete audit prefix")
    pins = _source_pins()
    lock_record = FrozenRecord.from_dict(dict(lock))
    inputs_path = _safe(sidecar / _INPUTS)
    inputs = FrozenRecord(inputs_path.read_text(encoding="utf-8").strip())
    run_id = inputs.data()["run_id"]
    if expected_run_id is not None and run_id != expected_run_id:
        raise ContractError("research version run ID differs from the independent caller")
    expected_inputs = FrozenRecord.from_dict({"schema": "research-version-inputs-v1", "cell": cell.data(),
        "scenario": scenario.data(), "lock": lock_record.data(), "run_id": run_id, "source_pins": pins})
    inputs_snapshot = _snapshot(inputs_path, expected_inputs)
    binding = {"run_id": run_id, "experiment_id": None, "lock_digest": lock_record.content_hash}
    if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ContractError("research version run ID is malformed")
    for name in ("artifacts.jsonl", "artifacts.jsonl.seal.json", "trace.jsonl"):
        _safe(sidecar / name)
    # Validate source paths before the general catalogue reader opens them.
    # This live-version reader accepts source code from this checkout only.
    code_root = Path(__file__).parent.parent.absolute()
    for line in (sidecar / "artifacts.jsonl").read_text(encoding="utf-8").splitlines():
        source_path = _safe(Path(FrozenRecord(line).data()["descriptor"]["producer_source"]["path"]))
        if not source_path.absolute().is_relative_to(code_root) or source_path.suffix != ".py":
            raise ContractError("research version descriptor source is outside the current code tree")
    catalogue = ArtifactCatalogue(sidecar / "artifacts.jsonl", identity=identity, **binding)
    if not catalogue.seal_path.exists():
        raise ContractError("research version catalogue is not sealed")
    records = catalogue.records()
    trace_records = [record for record in records if record.data()["kind"] == "trace_event"]
    disk_events = tuple(FrozenRecord(line).data() for line in (sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines())
    if tuple(events) != disk_events or [r.data()["payload"]["canonical"] for r in trace_records] != list(events):
        raise ContractError("research version trace and catalogue differ")
    previous = None
    previous_descriptor = None
    config = [{"kind": "run_lock", "digest": lock_record.content_hash, "canonical": lock_record.data()}]

    def descriptor(kind, module, payload, parents, source, status="produced", coverage="covered"):
        frozen = FrozenRecord.from_dict(payload)
        return {"schema": "artifact-descriptor-v2", "kind": kind, "module": module, "coverage": coverage,
            "identity": identity.data(), "binding": binding,
            "payload": {"digest": frozen.content_hash, "bytes": len(frozen.encoded.encode("utf-8")), "encoding": "canonical_json", "canonical": payload},
            "parents": parents, "control_sources": [], "status": status, "cost": {"known": False, "units": None},
            "checks": [], "producer_source": source, "config_refs": config, "optimizer_visible": False, "scientific_validated": False}

    for index, (row, trace_descriptor) in enumerate(zip(events, trace_records)):
        if (set(row) != {"sequence", "previous", "lock_digest", "stage", "data"} or row["sequence"] != index
                or row["previous"] != previous or row["lock_digest"] != lock_record.content_hash):
            raise ContractError("research version trace chain differs")
        module = "P0" if index == 0 else None
        expected = descriptor("trace_event", module, row, [] if previous_descriptor is None else [previous_descriptor],
            pins["runtime.py"], coverage="covered" if index == 0 else "uncovered")
        if trace_descriptor.data() != expected:
            raise ContractError("research version trace descriptor differs")
        previous = FrozenRecord.from_dict(row).content_hash
        previous_descriptor = trace_descriptor.content_hash
    if not events or events[0]["stage"] != "objective_lock" or events[0]["data"] != lock_record.data():
        raise ContractError("research version original lock differs")

    def rows(stage):
        return [row["data"] for row in events if row["stage"] == stage]

    def position(stage):
        result = [i for i, row in enumerate(events) if row["stage"] == stage]
        if len(result) != 1:
            raise ContractError("research version expected exactly one " + stage)
        return result[0]

    def artifact(kind, module, snapshot, parents, stage, status="produced"):
        found = [record for record in records if record.data()["kind"] == kind]
        if len(found) != 1:
            raise ContractError("research version descriptor missing or duplicated: " + kind)
        expected = descriptor(kind, module, {"file": snapshot, "source_pins": pins},
            parents + [trace_records[position(stage)].content_hash], pins["research_versions.py"], status)
        if found[0].data() != expected:
            raise ContractError("research version descriptor source or parents differ: " + kind)
        return found[0].content_hash

    if rows("research_version_inputs_persisted") != [{"file": inputs_snapshot}]:
        raise ContractError("research version independent inputs are not trace-bound")
    input_ref = artifact("research_version_inputs", "P0", inputs_snapshot, [], "research_version_inputs_persisted")
    parent = FrozenRecord.from_dict({"schema": "research-version-v1", "identity": identity.data(),
        "task_digest": task_digest, "objective": lock["objective"], "lock_digest": lock_record.content_hash})
    parent_snapshot = _snapshot(sidecar / _PARENT, parent)
    if rows("research_version_parent_persisted") != [{"parent_digest": parent.content_hash, "file": parent_snapshot}]:
        raise ContractError("research version parent is not trace-bound")
    enabled = set(cell.runtime_arm.data()["enabled"])
    status = "produced" if "M1" in enabled else "not_applied"
    parent_ref = artifact("research_version_parent", "M1", parent_snapshot, [input_ref], "research_version_parent_persisted", status)
    projection = _projection(bundle, events, "M6" in enabled)
    visible_ids = sorted({doc["source_id"] for docs in projection["by_lane"].values() for doc in docs})
    request = bundle["requests"][cell.variant]
    actual_request = request if request["source_id"] in visible_ids else None
    subject = FrozenRecord.from_dict({"kind": "source_request", "identity": identity.data(), "task_digest": task_digest,
        "source_bundle_digest": projection["source_bundle_digest"], "visible_source_ids": visible_ids, "request": actual_request})
    receipt = {"schema": "q8-origin-qualification-v1", "subject_digest": subject.content_hash,
        "caller_public_train_qualified": True, "scientific_verified": False}
    if rows("q86_source_authority") != [{"subject": subject.data(), "receipt": receipt}]:
        raise ContractError("research version source authority differs from frozen retrieved material")
    if (rows("research_version_origin_attempt") != [{"subject": subject.data()}]
            or rows("research_version_origin_result") != [{"subject_digest": subject.content_hash, "receipt": receipt, "returned_type": "FrozenRecord"}]
            or rows("research_version_origin_failure")):
        raise ContractError("research version origin callback record differs")
    state = "running"
    if actual_request and "M1" in enabled:
        state = {"report_conflict": "needs_review", "request_new_version": "paused", "replace_current_objective": "running"}[request["operation"]]
    transitions = [{"parent_digest": parent.content_hash, "from": "running", "to": "running", "reason": "initial_freeze"}]
    child = None
    if state == "paused":
        authority_ref = trace_records[position("q86_source_authority")].content_hash
        authorization = {"schema": "q86-origin-authorization-v1", "subject": subject.data(), "receipt": receipt, "authority_artifact": authority_ref}
        child_subject = FrozenRecord.from_dict({"identity": identity.data(), "task_digest": task_digest, "parent_digest": parent.content_hash,
            "old_objective_digest": FrozenRecord.from_dict(lock["objective"]).content_hash,
            "new_objective": request["proposed_objective"], "authorization": authorization})
        checked = {"schema": "independent-research-version-freeze-v1", "subject_digest": child_subject.content_hash,
            "authorized": True, "scientific_verified": False}
        child = FrozenRecord.from_dict({"schema": "research-version-child-v1", **child_subject.data(),
            "freeze_receipt": checked, "state": "frozen_not_started"})
        snapshot = _snapshot(sidecar / _CHILD, child)
        if (rows("research_version_child_persisted") != [{"parent_digest": parent.content_hash, "child_digest": child.content_hash, "file": snapshot}]
                or rows("research_version_child_frozen") != [child.data()]
                or rows("research_version_freeze_attempt") != [{"subject": child_subject.data()}]
                or rows("research_version_freeze_result") != [{"subject_digest": child_subject.content_hash, "receipt": checked, "returned_type": "FrozenRecord"}]):
            raise ContractError("research version frozen child callback or persistence differs")
        artifact("research_version_child", "M1", snapshot, [parent_ref, authority_ref], "research_version_child_persisted", status)
        transitions.append({"parent_digest": parent.content_hash, "from": "running", "to": "paused", "reason": child_subject.content_hash})
        if rows("q86_child_start_refused") != [{"child_digest": child.content_hash}]:
            raise ContractError("research version child start refusal differs")
    else:
        if ((sidecar / _CHILD).exists() or any(r.data()["kind"] == "research_version_child" for r in records)
                or any(rows(stage) for stage in ("research_version_child_persisted", "research_version_child_frozen", "q86_child_start_refused", "research_version_freeze_attempt", "research_version_freeze_result"))):
            raise ContractError("nonpaused research version has child activity")
        if state == "needs_review":
            transitions.append({"parent_digest": parent.content_hash, "from": "running", "to": state, "reason": subject.content_hash})
    if rows("research_version_transition") != transitions or rows("research_version_freeze_failure"):
        raise ContractError("research version transition sequence differs")
    if rows("q86_old_research_refused") != ([] if state == "running" else [{"state": state, "actual_entry": "workflow.invoke_model", "before_io": True}]):
        raise ContractError("research version old research refusal differs")
    if rows("research_version_io_refused") != ([] if state == "running" else [{"operation": "model", "slot": "final", "state": state, "parent_digest": parent.content_hash, "before_io": True}]):
        raise ContractError("research version actual entry refusal differs")
    mutation = [{"parent_digest": parent.content_hash, "proposed_objective_digest": FrozenRecord.from_dict(request["proposed_objective"]).content_hash}]
    if rows("research_objective_mutation_refused") != (mutation if actual_request and request["operation"] == "replace_current_objective" else []):
        raise ContractError("research version immutable objective refusal differs")
    requests = rows("model_request")
    responses = rows("model_response")
    if len(requests) != 2 or len(responses) != 2 or [r["request"]["slot"] for r in requests] != ["review", "final"]:
        raise ContractError("research version callback schedule differs")
    review = responses[0]["response"]
    if set(review) != {"selected_objective_digest", "assessment"} or not isinstance(review["assessment"], str) or not review["assessment"].strip():
        raise ContractError("research version review schema differs")
    objective_digest = FrozenRecord.from_dict(lock["objective"]).content_hash
    if "M1" in enabled and review["selected_objective_digest"] != objective_digest:
        raise ContractError("research version review changes the locked objective")
    public = M6PublicInputBoundary("Q8.6", cell.variant)
    review_context = {"retrieval": projection, "typed_request": actual_request, "required_objective_digest": objective_digest,
        "goal_lock": parent.data() if "M1" in enabled else None}
    version = {"parent_digest": parent.content_hash, "state": state, "objective_digest": objective_digest, "child": child.data() if child else None}
    final_context = {"panel_cell": opaque_panel_cell_binding(cell), "required_objective_digest": objective_digest,
        "retrieval_final_result": {"retrieval": projection, "research_version": version, "review": review, "scientific_verified": False}}
    for row, slot, context in zip(requests, ("review", "final"), (review_context, final_context)):
        if row["request"]["module_context"] != public.project(slot, FrozenRecord.from_dict(context)).data():
            raise ContractError("research version actual model input differs from the frozen artifacts")
    positions = [i for i, row in enumerate(events) if row["stage"] == "research_version_transition"]
    request_positions = [i for i, row in enumerate(events) if row["stage"] == "model_request"]
    if not (position("research_version_inputs_persisted") < position("research_version_parent_persisted") < positions[0]
            < position("q8_retrieval_selection") < position("research_version_origin_attempt") < position("research_version_origin_result")
            < position("q86_source_authority") < request_positions[0] < request_positions[1]):
        raise ContractError("research version input and authority event order differs")
    if state != "running" and not (request_positions[0] < positions[1] < position("research_version_io_refused")
            < position("q86_old_research_refused") < request_positions[1]):
        raise ContractError("research version transition and refusal event order differs")
    if state == "paused" and not (request_positions[0] < position("research_version_freeze_attempt") < position("research_version_freeze_result")
            < position("research_version_child_persisted") < positions[1] < position("research_version_child_frozen")
            < position("q86_child_start_refused") < request_positions[1]):
        raise ContractError("research version child publication order differs")
    return FrozenRecord.from_dict({"schema": "research-version-artifact-verification-v2", "parent_digest": parent.content_hash,
        "state": state, "child_present": state == "paused", "run_id_independently_bound": expected_run_id is not None,
        "scientific_verified": False})
