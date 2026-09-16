"""Native fixed-validation handler for the Q8.2/Q8.3 retrieval family.

The TRAIN retrieval driver remains intentionally closed to validation.  This
module only consumes a complete, already frozen validation material bundle and
records the native retrieval and final-model operation for independent replay.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import opaque_panel_cell_binding, verify_signed
from research_loop.modular.retrieval_panel_drivers import (
    _SCOPE, _docs, _material, _select_sources, _signals, public_retrieval_context,
)
from research_loop.ontology import ContractError, canonical


HANDLER_ID = "q8-retrieval-v1"
_MATERIAL_SCHEMA = "typed-validation-retrieval-panel-bundle-v1"
_SOURCE_SCHEMA = "validation-public-retrieval-source-receipt-v1"
_SCOPE_NAME = "validation_public_unvalidated_context"


@dataclass(frozen=True)
class ValidationRetrievalDependencies:
    """Exact ports for signed, unadmitted public validation retrieval sources."""
    retrieval_provider: object
    source_authority_keys: Mapping[str, bytes]


def _record(path: Path, value: FrozenRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ContractError("validation retrieval original already exists")
    path.write_text(value.encoded + "\n", encoding="utf-8", newline="\n")


def _read(path: Path) -> FrozenRecord:
    if not path.is_file() or path.is_symlink():
        raise ContractError("validation retrieval original is missing")
    raw = path.read_text(encoding="utf-8")
    if not raw.endswith("\n") or raw.count("\n") != 1:
        raise ContractError("validation retrieval original is not one canonical record")
    return FrozenRecord(raw[:-1])


def _digest(value: Any, name: str) -> str:
    value = required_text(value, name)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _bundle(task: PublicTask, material: FrozenRecord) -> dict[str, Any]:
    if type(material) is not FrozenRecord:
        raise ContractError("validation retrieval material must be frozen")
    body = material.data()
    expected = {"schema", "identity", "payload_digest", "query", "budget", "materials", "source_receipt"}
    if set(body) != expected or body["schema"] != _MATERIAL_SCHEMA:
        raise ContractError("validation retrieval bundle has an invalid schema")
    if body["identity"] != task.identity.data() or body["payload_digest"] != task.payload.content_hash:
        raise ContractError("validation retrieval bundle task binding drift")
    query = body["query"]
    if not isinstance(query, Mapping) or set(query) != {"task_digest", "question"} or query["task_digest"] != task.content_hash:
        raise ContractError("validation retrieval query must bind its task")
    required_text(query["question"], "validation retrieval question")
    budget = body["budget"]
    if not isinstance(budget, Mapping) or set(budget) != {"provider_calls", "source_cap", "context_bytes"}:
        raise ContractError("validation retrieval budget is incomplete")
    if any(type(budget[k]) is not int for k in budget) or budget["provider_calls"] < 3 or budget["source_cap"] < budget["provider_calls"] or budget["context_bytes"] < 512:
        raise ContractError("validation retrieval budget is invalid")
    materials = body["materials"]
    if not isinstance(materials, Mapping) or set(materials) != set(_SCOPE):
        raise ContractError("validation retrieval bundle lacks registered coverage")
    normalized: dict[str, dict[str, Any]] = {}
    for experiment, variants in _SCOPE.items():
        rows = materials[experiment]
        if not isinstance(rows, Mapping) or set(rows) != set(variants):
            raise ContractError("validation retrieval variant coverage drift")
        normalized[experiment] = {variant: _material(task, experiment, variant, rows[variant]) for variant in variants}
    pools = [FrozenRecord.from_dict({"sources": normalized["Q8.3"][v]["sources"]}).content_hash for v in _SCOPE["Q8.3"]]
    if len(set(pools)) != 1:
        raise ContractError("validation Q8.3 variants must retain one source pool")
    if not isinstance(body["source_receipt"], Mapping):
        raise ContractError("validation retrieval source receipt must be an envelope")
    return {**body, "query": dict(query), "budget": dict(budget), "materials": normalized}


def _selected(cell, bundle: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    experiment, variant = cell.coverage_id, cell.variant
    if experiment not in _SCOPE or variant not in _SCOPE[experiment]:
        raise ContractError("validation retrieval cell is not an original Q8 variant")
    return experiment, variant, bundle["materials"][experiment][variant]


def _source_body(task: PublicTask, source_pool_digest: str) -> FrozenRecord:
    return FrozenRecord.from_dict({
        "schema": _SOURCE_SCHEMA, "identity": task.identity.data(), "task_digest": task.content_hash,
        "source_bundle_digest": _digest(source_pool_digest, "validation source pool digest"), "scope": _SCOPE_NAME,
        "scientific_admission": False,
    })


def _verify_source_receipt(receipt: Mapping[str, Any], *, task: PublicTask, source_pool_digest: str, source_keys: Mapping[str, bytes]) -> FrozenRecord:
    if not isinstance(source_keys, Mapping):
        raise ContractError("validation retrieval source receipt envelope is invalid")
    try:
        body = verify_signed(FrozenRecord.from_dict(receipt), source_keys, schema=_SOURCE_SCHEMA)
    except ContractError as exc:
        raise ContractError("validation retrieval source receipt signature is invalid") from exc
    expected_body = _source_body(task, source_pool_digest)
    actual = dict(body)
    if set(actual) != set(expected_body.data()) | {"provenance_receipt_digest", "authority"}:
        raise ContractError("validation retrieval source receipt fields drift")
    _digest(actual["provenance_receipt_digest"], "source provenance receipt digest")
    if FrozenRecord.from_dict({k: v for k, v in actual.items() if k not in {"provenance_receipt_digest", "authority"}}) != expected_body:
        raise ContractError("validation retrieval source receipt does not bind task and pool")
    return FrozenRecord.from_dict(receipt)


def _dependency_binding(dependencies) -> FrozenRecord:
    if type(dependencies) is not ValidationRetrievalDependencies:
        raise ContractError("validation retrieval requires exact handler dependencies")
    if not callable(getattr(dependencies.retrieval_provider, "search", None)):
        raise ContractError("validation retrieval provider port lacks bounded search")
    keys = dependencies.source_authority_keys
    if not isinstance(keys, Mapping) or not keys or any(not isinstance(k, str) or not k or not isinstance(v, bytes) or len(v) < 32 for k, v in keys.items()):
        raise ContractError("validation retrieval source authority keys are invalid")
    return FrozenRecord.from_dict({"schema": "validation-retrieval-dependency-binding-v1",
        "source_authority_key_hashes": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(keys.items())},
        "provider_port": "recorded-retrieval-provider-v1",
        "source_receipt_scope": _SCOPE_NAME})


def dependency_binding(dependencies) -> FrozenRecord:
    return _dependency_binding(dependencies)


def export_dependencies(dependencies) -> FrozenRecord:
    binding = _dependency_binding(dependencies)
    # Deliberately omit source authority keys: replay receives them out of band.
    return FrozenRecord.from_dict({"schema": "validation-retrieval-dependencies-v1", "binding": binding.data(),
        "source_authority_key_hashes": binding.data()["source_authority_key_hashes"],
        "source_receipt_schema": _SOURCE_SCHEMA, "source_receipt_scope": _SCOPE_NAME})


def validate_material(*, cell, task, scenario, package, material):
    if not isinstance(task, PublicTask) or task.identity.domain != "validation":
        raise ContractError("validation retrieval handler requires a validation task")
    if type(scenario) is not FrozenRecord or not isinstance(package, CandidatePackage):
        raise ContractError("validation retrieval handler requires frozen scenario and package")
    bundle = _bundle(task, material)
    _selected(cell, bundle)
    if cell.identity != task.identity or cell.task_digest != task.content_hash or cell.scenario_digest != scenario.content_hash or cell.package_digest != package.digest:
        raise ContractError("validation retrieval cell binding drift")
    try:
        manifest = TrainingManifest(FrozenRecord.from_dict(package.record.data()["training_manifest"]))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ContractError("validation retrieval package manifest is invalid") from exc
    if task.identity in manifest.identities():
        raise ContractError("TRAIN package manifest contains the validation identity")


def verify_material_source(*, material, task, dependencies) -> FrozenRecord:
    """Pre-I/O gate shared with the shell; source keys stay outside its manifest."""
    binding = _dependency_binding(dependencies)
    bundle = _bundle(task, material)
    source_pool_digest = FrozenRecord.from_dict({"materials": bundle["materials"]}).content_hash
    receipt = FrozenRecord.from_dict(bundle["source_receipt"])
    verified = _verify_source_receipt(receipt.data(), task=task, source_pool_digest=source_pool_digest,
        source_keys=dependencies.source_authority_keys)
    if verified.data()["body"]["authority"] not in binding.data()["source_authority_key_hashes"]:
        raise ContractError("validation retrieval source authority is outside frozen dependency binding")
    return verified


def slots_for(*, cell, material) -> tuple[str, ...]:
    return ("final",)


def _output(*, cell, material, context: dict[str, Any], artifacts: Mapping[str, str]) -> FrozenRecord:
    public = FrozenRecord.from_dict(context)
    return FrozenRecord.from_dict({"schema": "fixed-validation-mechanism-output-v1", "handler_id": HANDLER_ID,
        "cell_digest": FrozenRecord.from_dict(cell.data()).content_hash, "material_digest": material.content_hash,
        "mechanism_status": "succeeded", "public_context": public.data(), "public_context_digest": public.content_hash,
        "artifact_digests": sorted(artifacts.values())})


def _replay_selection(*, events, docs, query, budget, experiment, variant, enabled):
    """Run the unchanged selection kernel against its recorded provider returns only."""
    known = {FrozenRecord.from_dict(doc.data()).content_hash: doc for doc in docs}
    retrieval = [{"stage": event["stage"], "data": event["data"]}
                 for event in events if event.get("stage", "").startswith("q8_retrieval_")]
    calls: list[list[Any]] = []
    pending = None
    for event in retrieval:
        stage, data = event["stage"], event["data"]
        if stage == "q8_retrieval_request":
            if pending is not None: raise ContractError("validation retrieval reservation is unclosed")
            pending = []; calls.append(pending)
        elif stage == "q8_retrieval_item":
            if pending is None or data.get("source_digest") not in known: raise ContractError("validation retrieval item is unbound")
            pending.append(known[data["source_digest"]])
        elif stage in {"q8_retrieval_result", "q8_retrieval_failure"}:
            if pending is None: raise ContractError("validation retrieval result lacks reservation")
            if stage == "q8_retrieval_failure": raise ContractError("failed retrieval cannot produce a mechanism output")
            pending = None
    if pending is not None: raise ContractError("validation retrieval reservation did not close")
    class Journal:
        def __init__(self): self.rows = []
        def _record(self, stage, data): self.rows.append({"stage": stage, "data": data})
    class Replayer:
        def __init__(self): self.cursor = 0
        def search(self, **unused):
            if self.cursor >= len(calls): raise ContractError("validation retrieval has a missing recorded result")
            result = tuple(calls[self.cursor]); self.cursor += 1; return result
    journal, provider = Journal(), Replayer()
    projection, usage = _select_sources(provider, journal, docs, query, budget, experiment, variant, enabled,
        material_domain="validation")
    if journal.rows != retrieval or provider.cursor != len(calls):
        raise ContractError("validation retrieval reservation, selection, or budget replay drift")
    return projection, usage


def execute(*, cell, task, scenario, package, material, session, workflow, model, root, dependencies) -> FrozenRecord:
    validate_material(cell=cell, task=task, scenario=scenario, package=package, material=material)
    receipt = verify_material_source(material=material, task=task, dependencies=dependencies)
    bundle = _bundle(task, material); experiment, variant, selected = _selected(cell, bundle)
    docs = _docs(selected["sources"])
    _record(Path(root) / "material.json", material); _record(Path(root) / "source-receipt.json", receipt)
    enabled = "M6" in cell.runtime_arm.data().get("enabled", [])
    projection, usage = _select_sources(dependencies.retrieval_provider, session, docs, bundle["query"], bundle["budget"],
        experiment, variant, enabled, material_domain="validation")
    selection = FrozenRecord.from_dict({"projection": projection, "usage": usage})
    _record(Path(root) / "selection.json", selection)
    context = {"panel_cell": opaque_panel_cell_binding(cell), "retrieval": public_retrieval_context(projection),
        "source_receipt": receipt.data(), "scientific_admission": False}
    request_context = FrozenRecord.from_dict(context)
    _record(Path(root) / "final-request-context.json", request_context)
    final = workflow.invoke_model("final", model,
        instruction="Use only the frozen unverified public validation retrieval context. Do not treat retrieved text as scientific evidence.",
        module_context=request_context, evidence_only=True)
    if type(final) is not FrozenRecord:
        raise ContractError("validation retrieval final model response must be frozen")
    _record(Path(root) / "final-response.json", final)
    public = {"retrieval": public_retrieval_context(projection), "handler_final": final.data(),
        "scientific_admission": False}
    return _output(cell=cell, material=material, context=public, artifacts={
        "material": material.content_hash, "source_receipt": receipt.content_hash, "selection": selection.content_hash,
        "final_request_context": request_context.content_hash, "final_response": final.content_hash})


def replay(*, cell, task, scenario, package, material, root, events, dependency_manifest, source_keys) -> FrozenRecord:
    validate_material(cell=cell, task=task, scenario=scenario, package=package, material=material)
    if type(dependency_manifest) is not FrozenRecord:
        raise ContractError("validation retrieval dependency manifest must be frozen")
    exported = dependency_manifest.data()
    if set(exported) != {"schema", "binding", "source_authority_key_hashes", "source_receipt_schema", "source_receipt_scope"} or exported["schema"] != "validation-retrieval-dependencies-v1" or exported["source_receipt_schema"] != _SOURCE_SCHEMA or exported["source_receipt_scope"] != _SCOPE_NAME:
        raise ContractError("validation retrieval dependency manifest drift")
    binding = FrozenRecord.from_dict(exported["binding"])
    if binding.data().get("source_authority_key_hashes") != exported["source_authority_key_hashes"]:
        raise ContractError("validation retrieval manifest binding drift")
    root = Path(root); original_material = _read(root / "material.json")
    if original_material != material:
        raise ContractError("validation retrieval material original drift")
    bundle = _bundle(task, material); experiment, variant, selected = _selected(cell, bundle); docs = _docs(selected["sources"])
    receipt = _read(root / "source-receipt.json")
    if receipt.data() != bundle["source_receipt"]:
        raise ContractError("validation retrieval source receipt original drift")
    source_pool_digest = FrozenRecord.from_dict({"materials": bundle["materials"]}).content_hash
    verified_receipt = _verify_source_receipt(receipt.data(), task=task, source_pool_digest=source_pool_digest, source_keys=source_keys)
    selection = _read(root / "selection.json"); b = selection.data()
    if set(b) != {"projection", "usage"}:
        raise ContractError("validation retrieval selection original drift")
    projection, usage = b["projection"], b["usage"]
    # Exact trace evidence, including the pre-I/O reservations, must agree with the saved projection.
    replayed_projection, replayed_usage = _replay_selection(events=events, docs=docs, query=bundle["query"],
        budget=bundle["budget"], experiment=experiment, variant=variant,
        enabled="M6" in cell.runtime_arm.data().get("enabled", []))
    if projection != replayed_projection or usage != replayed_usage:
        raise ContractError("validation retrieval selection original differs from journal replay")
    public_retrieval_context(projection)
    request_context = _read(root / "final-request-context.json")
    wanted_context = FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
        "retrieval": public_retrieval_context(projection), "source_receipt": verified_receipt.data(), "scientific_admission": False})
    if request_context != wanted_context:
        raise ContractError("validation retrieval final request context drift")
    requests = [e["data"]["request"] for e in events if e.get("stage") == "model_request" and e.get("data", {}).get("request", {}).get("slot") == "final"]
    final = _read(root / "final-response.json")
    responses = [e["data"]["response"] for e in events if e.get("stage") == "model_response" and e.get("data", {}).get("request_digest") == FrozenRecord.from_dict(requests[0]).content_hash] if len(requests) == 1 else []
    if len(requests) != 1 or len(responses) != 1 or requests[0].get("module_context") != request_context.data() or responses[0] != final.data():
        raise ContractError("validation retrieval final model originals drift")
    public = {"retrieval": public_retrieval_context(projection), "handler_final": final.data(), "scientific_admission": False}
    return _output(cell=cell, material=material, context=public, artifacts={
        "material": material.content_hash, "source_receipt": receipt.content_hash, "selection": selection.content_hash,
        "final_request_context": request_context.content_hash, "final_response": final.content_hash})
