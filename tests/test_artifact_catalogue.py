import json
import pytest
from pathlib import Path

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError


def identity(domain="train", task_id="task"):
    return DataIdentity("synthetic", task_id, "group", "dataset-v1", "split-v1", domain)


def make_catalogue(path, *, identity_value):
    return ArtifactCatalogue.external(path, identity=identity_value, producer_source=source_snapshot(Path(__file__)))


def test_append_only_catalogue_rejects_missing_parent_cross_subject_and_validation_optimizer(tmp_path):
    catalogue = make_catalogue(tmp_path / "artifacts.jsonl", identity_value=identity())
    root = catalogue.append(kind="root", module="M1", payload={"x": 1})
    with pytest.raises(ContractError, match="parent"):
        catalogue.append(kind="orphan", module="M2", payload={"x": 2}, parents=("f" * 64,))
    foreign = make_catalogue(tmp_path / "foreign.jsonl", identity_value=identity(task_id="other"))
    foreign_root = foreign.append(kind="root", module="M1", payload={"x": 1})
    with catalogue.path.open("a", encoding="utf-8") as stream:
        stream.write(foreign_root.encoded + "\n")
    with pytest.raises(ContractError, match="tampered"):
        make_catalogue(catalogue.path, identity_value=identity())
    target = make_catalogue(tmp_path / "target.jsonl", identity_value=identity(task_id="target"))
    with pytest.raises(ContractError, match="unsupported"):
        target.append(kind="target_control", module="M9", payload={"selection": "frozen"}, control_sources=(foreign_root,))
    validation = make_catalogue(tmp_path / "validation.jsonl", identity_value=identity(domain="validation"))
    with pytest.raises(ContractError, match="validation"):
        validation.append(kind="leak", module="M9", payload={"x": 1}, optimizer_visible=True)
    assert root.data()["scientific_validated"] is False


def test_failure_stays_append_only_and_tamper_is_detected(tmp_path):
    path = tmp_path / "artifacts.jsonl"
    catalogue = make_catalogue(path, identity_value=identity())
    failed = catalogue.append(kind="docker_receipt", module="M8", payload={"status": "failed"}, status="failed")
    assert failed.data()["status"] == "failed"
    assert failed.data()["scientific_validated"] is False
    body = failed.data(); body["identity"]["task_id"] = "tampered"
    path.write_text(FrozenRecord.from_dict(body).encoded + "\n", encoding="utf-8")
    with pytest.raises(ContractError, match="tampered"):
        make_catalogue(path, identity_value=identity())
    with pytest.raises(ContractError, match="tampered"):
        catalogue.records()


def test_seal_survives_reopen_and_rejects_append_and_tail_deletion(tmp_path):
    path = tmp_path / 'artifacts.jsonl'
    catalogue = make_catalogue(path, identity_value=identity())
    first = catalogue.append(kind='input', module='M1', payload={'x': 1})
    catalogue.append(kind='failed_attempt', module='M7', payload={'error': 'execution_failed'},
                     parents=(first.content_hash,), status='failed')
    seal = catalogue.seal()
    reopened = make_catalogue(path, identity_value=identity())
    reopened.verify(seal)
    with pytest.raises(ContractError, match='sealed'):
        reopened.append(kind='late', module='M9', payload={'x': 2})
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(lines[0])
    with pytest.raises(ContractError, match='seal'):
        catalogue.verify(seal)
    with pytest.raises(ContractError, match='seal'):
        make_catalogue(path, identity_value=identity())


@pytest.mark.parametrize('change', [
    {'status': 'success_without_check'}, {'scientific_validated': True},
    {'cost': {'known': True, 'units': None}}, {'cost': {'known': True, 'units': -1}},
    {'kind': ''}, {'parents': {}}, {'module': 'M99'}, {'optimizer_visible': 'false'},
])
def test_reload_applies_same_semantic_contract_even_if_attacker_rehashes(change, tmp_path):
    path = tmp_path / 'artifacts.jsonl'
    catalogue = make_catalogue(path, identity_value=identity())
    catalogue.append(kind='result', module='M2', payload={'x': 1})
    row = json.loads(path.read_text(encoding='utf-8'))
    row['descriptor'].update(change)
    row['descriptor_digest'] = FrozenRecord.from_dict(row['descriptor']).content_hash
    path.write_text(FrozenRecord.from_dict(row).encoded+'\n', encoding='utf-8')
    with pytest.raises(ContractError):
        catalogue.records()
    with pytest.raises(ContractError):
        make_catalogue(path, identity_value=identity())


def test_validation_domain_cannot_be_opened_as_train_or_rehashed_into_optimizer_view(tmp_path):
    path = tmp_path / 'validation.jsonl'
    validation = make_catalogue(path, identity_value=identity(domain='validation'))
    validation.append(kind='acceptance', module='M5', payload={'fixture': 'sealed'})
    with pytest.raises(ContractError, match='identity, domain'):
        make_catalogue(path, identity_value=identity())
    row = json.loads(path.read_text(encoding='utf-8'))
    row['descriptor']['optimizer_visible'] = True
    row['descriptor_digest'] = FrozenRecord.from_dict(row['descriptor']).content_hash
    path.write_text(FrozenRecord.from_dict(row).encoded+'\n', encoding='utf-8')
    with pytest.raises(ContractError, match='validation'):
        validation.records()


def test_current_source_bytes_and_partial_write_are_checked_on_each_read(tmp_path):
    source = tmp_path / 'producer.py'
    source.write_bytes(b'# original producer\n')
    catalogue = ArtifactCatalogue.external(tmp_path/'artifacts.jsonl', identity=identity(),
                                           producer_source=source_snapshot(source))
    catalogue.append(kind='result', module='M3', payload={'context': 'frozen'})
    source.write_bytes(b'# changed producer\n')
    with pytest.raises(ContractError, match='source drift'):
        catalogue.records()
    source.write_bytes(b'# original producer\n')
    catalogue.path.write_bytes(catalogue.path.read_bytes().rstrip(b'\n'))
    with pytest.raises(ContractError, match='incomplete'):
        catalogue.records()
