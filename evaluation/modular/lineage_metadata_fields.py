"""Predeclared source/dataset/publication reference paths, without diagnostics."""
from __future__ import annotations

import re

from evaluation.modular.canonical_lineage import empty_references, normalize_reference

# These are parser constants, never a schema inferred from task-bearing keys.
# Arbitrary task/gold/code/background strings are not visited or regex-scanned.
REFERENCE_FIELDS = {
    "doi": "doi", "paper_doi": "doi", "publication_doi": "doi", "doi_url": "doi",
    "repository": "github_repository", "repo": "github_repository", "github": "github_repository",
    "github_name": "github_repository", "repository_url": "github_repository", "github_url": "github_repository",
    "huggingface_repo": "hf_dataset", "hf_repo": "hf_dataset", "hf_dataset": "hf_dataset",
    "huggingface_dataset": "hf_dataset", "dataset_hf_id": "hf_dataset",
    "source": "source_url", "source_url": "source_url", "source_urls": "source_url",
    "data_source": "source_url", "data_url": "source_url", "data_urls": "source_url",
    "dataset_source": "source_url", "dataset_url": "source_url", "dataset_urls": "source_url",
    "dataset": "source_url", "dataset_id": "source_url", "dataset_name": "source_url",
    "paper": "source_url", "paper_url": "source_url", "publication": "source_url",
    "publication_url": "source_url", "citation": "source_url", "citations": "source_url",
    "reference": "source_url", "references": "source_url", "url": "source_url", "urls": "source_url",
}
CONTAINERS = ("metadata", "task_metadata", "provenance", "source_metadata", "dataset_metadata", "publication_metadata", "data_desc", "datasets")
LICENSE_FIELDS = ("license", "licence", "license_id", "license_url")
_URL = re.compile(r"https?://[^\s<>\"{}]+")
_DOI = re.compile(r"(?<![A-Za-z0-9])10\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+")


def extract_metadata_references(row):
    """Return only normalized hashes and coverage counters to the custodian.

    Nested metadata.yaml is parsed only under known metadata containers or the
    exact metadata.yaml field. Unknown mapping keys never become public schema,
    never select file paths, and never authorize reading arbitrary nested text.
    """
    references = empty_references()
    unresolved = 0
    declared = False
    visited = {}

    def add(value, hint):
        nonlocal unresolved
        if isinstance(value, dict):
            visit(value)
        elif isinstance(value, list):
            for child in value:
                add(child, hint)
        elif isinstance(value, str) and value.strip():
            direct = normalize_reference(value, hint)
            extracted = [direct] if direct is not None else []
            if not extracted:
                # Reference fields may contain formatted bibliographic entries;
                # patterns are never applied to prompts, solutions, or code.
                for match in (*_URL.findall(value), *_DOI.findall(value)):
                    result = normalize_reference(match, hint)
                    if result is not None:
                        extracted.append(result)
            if not extracted:
                unresolved += 1
            for kind, token in extracted:
                references[kind].add(token)

    def visit(value):
        nonlocal declared
        if not isinstance(value, dict) or id(value) in visited:
            return
        visited[id(value)] = value
        for name, hint in REFERENCE_FIELDS.items():
            if name in value:
                add(value[name], hint)
        declared = declared or any(isinstance(value.get(name), str) and bool(value[name].strip()) for name in LICENSE_FIELDS)
        for name in (*CONTAINERS, "metadata.yaml"):
            child = value.get(name)
            if isinstance(child, str):
                import yaml
                parsed = yaml.safe_load(child)
                visit(parsed)
            elif isinstance(child, dict):
                visit(child)
            elif isinstance(child, list):
                for entry in child:
                    visit(entry)
        # Dependent substeps stay within the atomic record. Only the same
        # declared metadata fields are inspected, not their problem/code text.
        children = value.get("sub_steps")
        if isinstance(children, list):
            for child in children:
                visit(child)

    visit(row)
    return {kind: frozenset(values) for kind, values in references.items()}, unresolved, declared
