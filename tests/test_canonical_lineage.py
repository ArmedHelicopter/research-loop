import hashlib
import json

import pytest

from evaluation.modular.canonical_lineage import (
    Record, empty_references, match_records, normalize_reference, record_token, validate_graph,
)
from evaluation.modular.fresh_airs_custodian import CustodyError

SECRET = "PRIVATE_DYNAMIC_TASK_GOLD_CODE_KEY"


def record(source, identity, entries=(), legacy=None):
    refs = empty_references()
    unresolved = 0
    for value, hint in entries:
        result = normalize_reference(value, hint)
        if result is None:
            unresolved += 1
        else:
            kind, token = result
            refs[kind].add(token)
    return Record(source, record_token(source, "fixed-pin", identity),
                  {kind: frozenset(values) for kind, values in refs.items()}, legacy, unresolved)


def test_same_doi_normalizes_across_sources_and_http_forms():
    a = record("discoverybench", SECRET, [("10.1234/ABC.1", "doi")])
    b = record("airsbench", SECRET + "other", [("https://doi.org/10.1234%2Fabc.1", "source_url")])
    graph = match_records([a, b])
    assert graph["group_count"] == 1
    assert graph["groups"][0]["source_counts"]["airsbench"] == 1
    assert graph["groups"][0]["supported_relation_counts"]["doi"] == 1
    assert graph["independent_family_count_established"] == 0
    assert SECRET not in json.dumps(graph)
    assert "10.1234" not in json.dumps(graph)


def test_typed_artifact_hash_equality_and_derived_bytes_are_distinct():
    original = hashlib.sha256(b"synthetic observations").hexdigest()
    transformed = hashlib.sha256(b"transformed synthetic observations").hexdigest()
    a = record("blade", "a", [(original, "data_artifact_sha256")])
    b = record("airsbench", "b", [(original, "data_artifact_sha256")])
    c = record("scicode", "c", [(transformed, "data_artifact_sha256")])
    graph = match_records([a, b, c])
    assert sorted(group["member_count"] for group in graph["groups"]) == [1, 2]
    assert graph["absence_of_match_proves_independence"] is False


def test_plain_dataset_names_and_source_bound_hashes_are_not_comparable_identifiers():
    raw = "opaque-source-family-v1-" + "a" * 64
    a = record("blade", "a", [(SECRET, "source_url"), (raw, "source_url")])
    b = record("airsbench", "b", [(SECRET, "source_url")])
    graph = match_records([a, b])
    assert graph["group_count"] == 2
    assert graph["sources"]["blade"]["records_without_canonical_reference"] == 1
    assert graph["sources"]["blade"]["unresolved_reference_value_count"] == 2


def test_repository_aliases_and_transitive_shared_reference_closure():
    a = record("blade", "a", [("https://github.com/Owner/Repo/blob/main/data.csv", "source_url")])
    b = record("scienceagentbench", "b", [("git@github.com:owner/repo.git", "github_repository"), ("10.5555/test", "doi")])
    c = record("airsbench", "c", [("doi:10.5555/TEST", "doi")])
    graph = match_records([a, b, c])
    assert graph["group_count"] == 1
    assert graph["groups"][0]["member_count"] == 3
    assert graph["groups"][0]["supported_relation_counts"]["github_repository"] == 1
    assert graph["groups"][0]["supported_relation_counts"]["doi"] == 1


def test_hf_dataset_identity_is_typed_and_case_conservative():
    a = normalize_reference("https://huggingface.co/datasets/owner/Corpus/resolve/main/data.csv")
    b = normalize_reference("https://huggingface.co/datasets/owner/Corpus")
    c = normalize_reference("https://huggingface.co/datasets/owner/corpus")
    assert a == b
    assert a != c
    assert a[0] == "hf_dataset"
    assert normalize_reference("legacy", "hf_dataset") == normalize_reference("https://huggingface.co/datasets/legacy")
    assert normalize_reference("https://huggingface.co/datasets/legacy/resolve/main/data.csv") is None


def test_generic_url_keeps_semantic_query_and_path_differences():
    assert normalize_reference("https://EXAMPLE.com:443/a?version=1#section") == normalize_reference("https://example.com/a?version=1")
    assert normalize_reference("https://example.com/a?version=1") != normalize_reference("https://example.com/a?version=2")
    assert normalize_reference("https://example.com/a") != normalize_reference("https://example.com/A")
    assert normalize_reference("https://secret:password@example.com/data") is None
    assert normalize_reference("https://example.com/\udc96") is None


def test_legacy_constraint_kept_separate_from_scientific_reference_support():
    group = "f" * 64
    a = record("discoverybench", "a", legacy=group)
    b = record("discoverybench", "b", legacy=group)
    graph = match_records([a, b])
    assert graph["group_count"] == 1
    assert graph["groups"][0]["supported_relation_counts"]["legacy_group_constraint"] == 1
    assert graph["groups"][0]["members_without_canonical_reference"] == 2


def test_same_local_declaration_only_constrains_same_source():
    from dataclasses import replace
    local = frozenset(["a" * 64])
    a = replace(record("airsbench", "a"), local_dataset_declarations=local)
    b = replace(record("airsbench", "b"), local_dataset_declarations=local)
    c = replace(record("blade", "c"), local_dataset_declarations=local)
    graph = match_records([a, b, c])
    assert sorted(group["member_count"] for group in graph["groups"]) == [1, 2]
    assert graph["sources"]["airsbench"]["records_with_any_canonical_reference"] == 0
    assert graph["sources"]["airsbench"]["local_dataset_declaration_record_count"] == 2


@pytest.mark.parametrize("mutation", ["top", "nested", "scalar"])
def test_public_graph_rejects_dynamic_schema_keys_and_string_channels(mutation):
    graph = match_records([record("airsbench", SECRET)])
    if mutation == "top":
        graph[SECRET] = SECRET
    elif mutation == "nested":
        graph["groups"][0][SECRET] = SECRET
    else:
        graph["groups"][0]["independent_family_qualification"] = SECRET
    with pytest.raises(CustodyError) as error:
        validate_graph(graph)
    assert SECRET not in str(error.value)
