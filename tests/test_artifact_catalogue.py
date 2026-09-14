import pytest

from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError


def identity(domain="train", task_id="task"):
    return DataIdentity("synthetic", task_id, "group", "dataset-v1", "split-v1", domain)


def test_append_only_catalogue_rejects_missing_parent_cross_subject_and_validation_optimizer(tmp_path):
    catalogue = ArtifactCatalogue.external(tmp_path / "artifacts.jsonl", identity=identity())
    root = catalogue.append(kind="root", module="M1", payload={"x": 1})
    with pytest.raises(ContractError, match="parent"):
        catalogue.append(kind="orphan", module="M2", payload={"x": 2}, parents=("f" * 64,))
    foreign = ArtifactCatalogue.external(tmp_path / "foreign.jsonl", identity=identity(task_id="other"))
    foreign_root = foreign.append(kind="root", module="M1", payload={"x": 1})
    with catalogue.path.open("a", encoding="utf-8") as stream:
        stream.write(foreign_root.encoded + "\n")
    contaminated = ArtifactCatalogue.external(catalogue.path, identity=identity())
    with pytest.raises(ContractError, match="cross-subject"):
        contaminated.append(kind="cross_subject", module="M2", payload={"x": 2}, parents=(foreign_root.content_hash,))
    validation = ArtifactCatalogue.external(tmp_path / "validation.jsonl", identity=identity(domain="validation"))
    with pytest.raises(ContractError, match="validation"):
        validation.append(kind="leak", module="M9", payload={"x": 1}, optimizer_visible=True)
    assert root.data()["scientific_validated"] is False


def test_failure_stays_append_only_and_tamper_is_detected(tmp_path):
    path = tmp_path / "artifacts.jsonl"
    catalogue = ArtifactCatalogue.external(path, identity=identity())
    failed = catalogue.append(kind="docker_receipt", module="M8", payload={"status": "failed"}, status="failed")
    assert failed.data()["status"] == "failed"
    assert failed.data()["scientific_validated"] is False
    body = failed.data(); body["identity"]["task_id"] = "tampered"
    path.write_text(FrozenRecord.from_dict(body).encoded + "\n", encoding="utf-8")
    tampered = ArtifactCatalogue.external(path, identity=identity())
    with pytest.raises(ContractError, match="tampered"):
        tampered.verify()
