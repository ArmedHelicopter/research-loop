from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from research_loop.modular.benchmarks.scicode import SciCodeAdapter
from research_loop.modular.benchmarks.scienceagentbench import ScienceAgentBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError


_KEYS = {"audit-a": b"a" * 32, "audit-b": b"b" * 32}


def identity(benchmark: str, *, domain: str = "train") -> DataIdentity:
    return DataIdentity(benchmark, "fixture-task", "fixture-group", "source-pin", "fixture-split", domain)


def scicode_public() -> dict[str, object]:
    return {"problem_id": "fixture-task", "required_dependencies": "numpy", "sub_steps": [{
        "step_description_prompt": "Construct the public calculation.",
        "function_header": "def calculate(values):",
        "return_line": "return result",
        "step_background": "Synthetic public context.",
    }]}


def scienceagent_public() -> dict[str, object]:
    return {"task_id": "fixture-task", "task_inst": "Analyze the supplied public fixture.",
            "dataset_folder_tree": "datasets/\n  public.csv", "dataset_preview": "x,y\n1,2",
            "output_fname": "result.csv", "domain_knowledge": "Synthetic public context."}


@pytest.mark.parametrize("adapter,benchmark,metadata", [
    (SciCodeAdapter(), "scicode", scicode_public()),
    (ScienceAgentBenchAdapter(), "scienceagentbench", scienceagent_public()),
])
def test_projected_extended_task_reaches_real_train_run_journal(tmp_path: Path, adapter, benchmark, metadata) -> None:
    task = adapter.prepare(identity(benchmark), metadata)
    session = RunSession(task, package_digest="fixture-package", arm=default_compatibility("base").arm(["M1", "M2", "M3"]),
        objective=FrozenRecord.from_dict({"question": "fixture objective", "primary_endpoint": "fixture"}),
        slots=("only",), execution_limit=0, sidecar=tmp_path / benchmark,
        verifier=AuditVerifier(_KEYS), required_audit=("measurement",))
    seen = []
    response = session.invoke("only", lambda request: seen.append(request) or FrozenRecord.from_dict({"response": "fixture"}),
                              instruction="Use only public task content.")
    assert response.data()["response"] == "fixture"
    request = seen[0].data()
    assert request["task"]["identity"]["domain"] == "train"
    assert "gold" not in json.dumps(request).lower()
    assert "test_cases" not in json.dumps(request).lower()
    journal = (session.sidecar / "trace.jsonl").read_text(encoding="utf-8")
    assert '"stage":"model_request"' in journal
    assert task.content_hash in journal


@pytest.mark.parametrize("adapter,benchmark,metadata", [
    (SciCodeAdapter(), "scicode", scicode_public()),
    (ScienceAgentBenchAdapter(), "scienceagentbench", scienceagent_public()),
])
def test_projection_preserves_validation_domain_and_never_coerces_train(adapter, benchmark, metadata) -> None:
    task = adapter.prepare(identity(benchmark, domain="validation"), metadata)
    assert task.identity.domain == "validation"
    with pytest.raises(ContractError):
        task.identity.require_train()


@pytest.mark.parametrize("adapter,benchmark,metadata", [
    (SciCodeAdapter(), "scicode", scicode_public()),
    (ScienceAgentBenchAdapter(), "scienceagentbench", scienceagent_public()),
])
@pytest.mark.parametrize("field", ["gold_program_name", "test_cases", "ground_truth_code", "reference_code", "dataset_path"])
def test_extended_adapters_reject_private_or_unprojected_fields(adapter, benchmark, metadata, field) -> None:
    metadata = deepcopy(metadata)
    metadata[field] = "hidden"
    with pytest.raises(ContractError):
        adapter.prepare(identity(benchmark), metadata)


@pytest.mark.parametrize("name", ["../private/result.csv", "/absolute.csv", "C:\\private.csv", "result.csv/", "bad\u0000.csv",
                                   "results/../private.csv", "results//out.csv", "./out.csv", "results/./out.csv"])
def test_scienceagent_adapter_rejects_escape_output_name(name) -> None:
    metadata = scienceagent_public()
    metadata["output_fname"] = name
    with pytest.raises(ContractError):
        ScienceAgentBenchAdapter().prepare(identity("scienceagentbench"), metadata)


def test_scicode_adapter_rejects_nested_private_step_field() -> None:
    metadata = scicode_public()
    metadata["sub_steps"][0]["gold_code"] = "hidden"
    with pytest.raises(ContractError):
        SciCodeAdapter().prepare(identity("scicode"), metadata)


@pytest.mark.parametrize("variant", ["blank_background", "nested_output"])
def test_adapter_supports_optional_blank_or_nested_path(variant):
    if variant == "blank_background":
        metadata = scicode_public()
        metadata["sub_steps"][0]["step_background"] = " \n\t"
        task = SciCodeAdapter().prepare(identity("scicode"), metadata)
        assert task.payload.data()["steps"][0]["background"] is None
    else:
        metadata = scienceagent_public()
        metadata["output_fname"] = "results/predictions.csv"
        task = ScienceAgentBenchAdapter().prepare(identity("scienceagentbench"), metadata)
        assert task.payload.data()["output_filename"] == "results/predictions.csv"
