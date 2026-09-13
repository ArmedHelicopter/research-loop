import json

from evaluation.modular.lineage_metadata_fields import extract_metadata_references


def test_reference_only_fields_ignore_task_code_gold_and_dynamic_keys():
    row = {
        "source_url": "https://doi.org/10.1234/real",
        "task_inst": "PRIVATE_TASK https://doi.org/10.1234/not-source",
        "ground_truth_code": "PRIVATE_GOLD https://github.com/secret/code",
        "PRIVATE_DYNAMIC_KEY": {"doi": "10.1234/not-source-either"},
    }
    refs, unresolved, declared = extract_metadata_references(row)
    assert len(refs["doi"]) == 1
    assert not refs["github_repository"]
    assert unresolved == 0
    assert declared is False
    assert "PRIVATE" not in json.dumps({key: sorted(value) for key, value in refs.items()})


def test_explicit_provider_reference_and_nested_metadata_yaml_are_comparable():
    a, _, _ = extract_metadata_references({"huggingface_repo": "owner/dataset"})
    b, _, _ = extract_metadata_references({"metadata.yaml": "dataset:\n  url: https://huggingface.co/datasets/owner/dataset\n"})
    assert a["hf_dataset"] == b["hf_dataset"]
    assert len(a["hf_dataset"]) == 1


def test_unknown_names_remain_unmapped_and_license_declaration_is_only_a_count():
    refs, unresolved, declared = extract_metadata_references({"dataset_name": "PRIVATE DATASET NAME", "license": "PRIVATE CUSTOM TERMS"})
    assert unresolved == 1
    assert not any(refs.values())
    assert declared is True


def test_atomic_substeps_share_refs_but_arbitrary_background_is_not_scanned():
    refs, _, _ = extract_metadata_references({"sub_steps": [{"metadata": {"doi": "10.1234/shared"}, "background": "https://doi.org/10.1234/no"}]})
    assert len(refs["doi"]) == 1


def test_serialized_dataset_reference_visits_only_declared_provider_fields():
    a, unresolved, _ = extract_metadata_references({"dataset": "{'hf_name': 'owner/corpus', 'PRIVATE_DYNAMIC': {'doi': '10.1234/not-allowed'}}"})
    b, _, _ = extract_metadata_references({"dataset_url": "https://huggingface.co/datasets/owner/corpus"})
    assert a["hf_dataset"] == b["hf_dataset"]
    assert not a["doi"]
    assert unresolved == 0


def test_generic_repository_name_does_not_invent_a_github_provider():
    refs, unresolved, _ = extract_metadata_references({"repository": "owner/corpus"})
    assert not any(refs.values())
    assert unresolved == 1


def test_unmapped_serialized_object_remains_in_coverage_gap():
    refs, unresolved, _ = extract_metadata_references({"dataset": "{'PRIVATE_DYNAMIC': 'PRIVATE_VALUE'}"})
    assert not any(refs.values())
    assert unresolved == 1
