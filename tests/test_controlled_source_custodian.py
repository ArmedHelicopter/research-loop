from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import evaluation.modular.controlled_source_custodian as controlled
from evaluation.modular.controlled_source_custodian import _Artifact, acquire_corebench
from research_loop.ontology import ContractError, canonical


def _blob(value: bytes) -> str:
    return hashlib.sha1(f"blob {len(value)}\0".encode("ascii") + value).hexdigest()


class _Transport:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values, self.urls = values, []

    def iter_bytes(self, url: str):
        self.urls.append(url)
        value = self.values[url]
        yield value[:5]
        yield value[5:]


@pytest.fixture
def corebench_contract(monkeypatch):
    license_bytes = b"fixture license\n"
    task_bytes = canonical({"tasks": [
        {"paper_id": "shared-paper", "prompt": "PRIVATE_TASK_MARKER", "solution": "PRIVATE_SOLUTION_MARKER"},
        {"paper_id": "shared-paper", "prompt": "PRIVATE_TASK_MARKER"},
        {"paper_id": "other-paper", "gold": "PRIVATE_GOLD_MARKER"},
    ]}).encode()
    contract = {"source": "corebench", "repository": "fixture/corebench", "revision": "a" * 40,
                "license": _Artifact("LICENSE", len(license_bytes), _blob(license_bytes)),
                "task": _Artifact("benchmark/dataset/core_train.json", len(task_bytes), _blob(task_bytes))}
    monkeypatch.setattr(controlled, "_COREBENCH", contract)
    values = {controlled._url(contract["license"]): license_bytes, controlled._url(contract["task"]): task_bytes}
    return contract, _Transport(values)


def test_first_controlled_acquisition_keeps_raw_payload_private_and_emits_opaque_groups(tmp_path: Path, corebench_contract) -> None:
    _contract, transport = corebench_contract
    baseline = tmp_path / "baseline.json"
    baseline.write_text(canonical({"schema": "opaque-overlap-baseline-v1", "family_fingerprints": [],
                                   "artifact_fingerprints": [], "publication_fingerprints": []}), encoding="utf-8")
    output = tmp_path / "receipt.json"
    receipt = acquire_corebench(private_store=tmp_path / "private", output=output, transport=transport,
                                overlap_baseline=baseline)
    encoded = canonical(receipt)
    assert receipt["raw_private_payload_returned"] is False
    assert receipt["optimizer_access"] == "none"
    assert receipt["controlled_new_optimizer_process_payload_exported"] is False
    assert receipt["family_metadata"]["record_count"] == 3
    assert receipt["family_metadata"]["family_component_sizes"] == [1, 2]
    assert all(url.startswith("https://raw.githubusercontent.com/") for url in transport.urls)
    assert "PRIVATE_TASK_MARKER" not in encoded and "PRIVATE_SOLUTION_MARKER" not in encoded and "PRIVATE_GOLD_MARKER" not in encoded
    assert output.exists()
    assert (tmp_path / "private" / "snapshots" / "corebench").is_dir()
    with pytest.raises(ContractError, match="already exists"):
        acquire_corebench(private_store=tmp_path / "private", output=tmp_path / "other.json", transport=transport)


def test_acquisition_refuses_wrong_fixed_blob_without_leaving_final_snapshot(tmp_path: Path, corebench_contract) -> None:
    contract, transport = corebench_contract
    task_url = controlled._url(contract["task"])
    transport.values[task_url] = b"x" * len(transport.values[task_url])
    with pytest.raises(ContractError, match="fixed Git blob"):
        acquire_corebench(private_store=tmp_path / "private", output=tmp_path / "receipt.json", transport=transport)
    assert not (tmp_path / "private" / "snapshots" / "corebench" / contract["revision"]).exists()


def test_actual_controlled_source_metadata_preserves_the_exposure_failure_boundary() -> None:
    metadata = json.loads(Path("docs/data-source-metadata/corebench-controlled-acquisition.json").read_text(encoding="utf-8"))
    assert metadata["revision"] == controlled._COREBENCH["revision"]
    assert metadata["official_license"]["declared_license"] == "MIT"
    assert metadata["current_context_qualification"] == "ineligible_for_unseen_claim_due_to_recorded_schema_diagnostic_exposure_failure"
    assert metadata["validation_status"] == "not_eligible"
