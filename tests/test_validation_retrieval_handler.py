import hashlib
import hmac

import pytest

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.retrieval_panel_drivers import _SCOPE, _material
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.validation_retrieval_handler import (
    HANDLER_ID, _SOURCE_SCHEMA, _SCOPE_NAME, dependency_binding, execute, export_dependencies, replay,
    ValidationRetrievalDependencies, verify_material_source,
)
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical


SPLIT = "9" * 64
KEY = b"v" * 32


class Provider:
    def search(self, *, lane, query, source_bundle, call_limit, source_limit):
        return tuple(row for row in source_bundle.documents if row.lane == lane)[:source_limit]


def _dependencies():
    return ValidationRetrievalDependencies(Provider(), {"fixture-source": KEY})


def _task(name="discoverybench"):
    return PublicTask.create(DataIdentity(name, "val-q8", "val-group", "synthetic-v1", SPLIT, "validation"), {"question": "public validation fixture"})


def _docs(prefix):
    return [
        {"source_id": prefix + "-s", "root_source_id": prefix + "-rs", "lane": "support", "text": "public support"},
        {"source_id": prefix + "-c", "root_source_id": prefix + "-rc", "lane": "counter", "text": "public counter"},
        {"source_id": prefix + "-m", "root_source_id": prefix + "-rm", "lane": "method", "text": "public method"},
    ]


def _signals():
    return {"new_mechanism": False, "key_conflict": False, "innovation_claim": False,
            "dependency_unknown": False, "stagnation": False, "cheap_distinguishing_diagnostic_locked": False}


def _bundle(task):
    materials = {"Q8.2": {variant: {"sources": _docs("q82-" + variant), "signals": _signals()} for variant in _SCOPE["Q8.2"]},
                 "Q8.3": {variant: {"sources": _docs("q83"), "signals": _signals()} for variant in _SCOPE["Q8.3"]}}
    normalized = {experiment: {variant: _material(task, experiment, variant, item) for variant, item in rows.items()}
                  for experiment, rows in materials.items()}
    pool_digest = FrozenRecord.from_dict({"materials": normalized}).content_hash
    body = {"schema": _SOURCE_SCHEMA, "authority": "fixture-source", "identity": task.identity.data(), "task_digest": task.content_hash,
            "source_bundle_digest": pool_digest, "scope": _SCOPE_NAME, "scientific_admission": False,
            "provenance_receipt_digest": "a" * 64}
    mac = hmac.new(KEY, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()
    return FrozenRecord.from_dict({"schema": "typed-validation-retrieval-panel-bundle-v1", "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "query": {"task_digest": task.content_hash, "question": "frozen public query"},
        "budget": {"provider_calls": 3, "source_cap": 3, "context_bytes": 4096}, "materials": normalized,
        "source_receipt": {"body": body, "mac": mac}})


def _cell(task, material, experiment="Q8.2", variant="correct", enabled=True):
    train = DataIdentity("discoverybench", "train-q8", "train-group", "synthetic-v1", "8" * 64, "train")
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([train]), changes={"prompt": {"instructions": "fixture"}}, search_cost=0)
    arm = default_compatibility("b" * 64).arm(("M6",) if enabled else ())
    scenario = FrozenRecord.from_dict({"scenario": "fixed-validation-q8"})
    return PanelCell(experiment, task.identity, "r1", variant, "on" if enabled else "off", arm, task.content_hash,
        scenario.content_hash, package.digest, "c" * 64), scenario, package


def _run(tmp_path, *, experiment="Q8.2", variant="correct", enabled=True):
    task = _task(); material = _bundle(task); cell, scenario, package = _cell(task, material, experiment, variant, enabled)
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm,
        objective=FrozenRecord.from_dict({"objective": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=tmp_path / "runtime", verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    def model(request):
        return FrozenRecord.from_dict({"answer": "synthetic public response", "request_digest": request.content_hash})
    output = execute(cell=cell, task=task, scenario=scenario, package=package, material=material, session=session,
        workflow=ModularWorkflow(session), model=model, root=tmp_path / "handler", dependencies=_dependencies())
    return task, material, cell, scenario, package, session, output


def test_full_q82_q83_grid_replays_signed_originals_on_both_benchmarks(tmp_path):
    for benchmark in ("discoverybench", "blade"):
        for experiment, variants in _SCOPE.items():
            for variant in variants:
                for enabled in (False, True):
                    root = tmp_path / benchmark / experiment / variant / ("on" if enabled else "off")
                    task, material, cell, scenario, package, session, output = _run(root, experiment=experiment, variant=variant, enabled=enabled)
                    replayed = replay(cell=cell, task=task, scenario=scenario, package=package, material=material,
                        root=root / "handler", events=[x.data() for x in session._events],
                        dependency_manifest=export_dependencies(_dependencies()), source_keys={"fixture-source": KEY})
                    assert replayed == output
                    assert output.data()["handler_id"] == HANDLER_ID
                    assert output.data()["public_context"]["scientific_admission"] is False


def test_q82_off_preserves_unused_provider_budget(tmp_path):
    task, material, cell, scenario, package, session, output = _run(tmp_path, enabled=False)
    usage = FrozenRecord.from_dict(output.data()["public_context"]["retrieval"]).data()
    events = [x.data() for x in session._events]
    budget = [x["data"] for x in events if x["stage"] == "q8_retrieval_budget"]
    assert usage["scientific_admission"] is False
    assert budget[0]["provider_calls"] == 0 and budget[0]["unused_provider_calls"] == 3


def test_replay_rejects_bad_source_signature_and_final_context_drift(tmp_path):
    task, material, cell, scenario, package, session, _ = _run(tmp_path)
    with pytest.raises(ContractError, match="signature"):
        replay(cell=cell, task=task, scenario=scenario, package=package, material=material, root=tmp_path / "handler",
            events=[x.data() for x in session._events], dependency_manifest=export_dependencies(_dependencies()), source_keys={"fixture-source": b"x" * 32})
    request = tmp_path / "handler" / "final-request-context.json"
    request.write_text(FrozenRecord.from_dict({"drift": True}).encoded + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ContractError, match="final request context"):
        replay(cell=cell, task=task, scenario=scenario, package=package, material=material, root=tmp_path / "handler",
            events=[x.data() for x in session._events], dependency_manifest=export_dependencies(_dependencies()), source_keys={"fixture-source": KEY})


def test_dependency_export_binds_exact_verifier_without_exporting_keys():
    binding = dependency_binding(_dependencies())
    manifest = export_dependencies(_dependencies())
    assert FrozenRecord.from_dict(manifest.data()["binding"]) == binding
    assert KEY.hex() not in manifest.encoded


def test_source_gate_rejects_bad_signature_before_provider_or_model_call():
    task = _task(); material = _bundle(task)
    with pytest.raises(ContractError, match="signature"):
        verify_material_source(material=material, task=task,
            dependencies=ValidationRetrievalDependencies(Provider(), {"fixture-source": b"x" * 32}))
