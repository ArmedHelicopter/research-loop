"""Typed, conservative source-reference matching without public source strings.

This module consumes custodian-selected metadata only. Content-bearing names,
URLs, titles and dynamic keys never belong in its public graph. An observed
shared reference supports a grouping constraint, never independent-family or
scientific validity certification.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass, field

from evaluation.modular.fresh_airs_custodian import CustodyError, _check
from research_loop.ontology import canonical, digest

SCHEMA = "canonical-source-reference-v1"
SOURCES = ("discoverybench", "blade", "scicode", "scienceagentbench", "airsbench")
KINDS = ("doi", "github_repository", "hf_dataset", "source_url", "data_artifact_sha256")
RELATIONS = KINDS + ("source_scoped_dataset_declaration", "legacy_group_constraint")
HEX = re.compile(r"[0-9a-f]{64}\Z")
DOI = re.compile(r"10\.[0-9]{4,9}/[-._;()/:a-z0-9]+\Z", re.I)
GITHUB_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")


def _reference(kind, namespace, value):
    return digest({"schema": SCHEMA, "kind": kind, "namespace": namespace, "value": value})


def normalize_reference(raw, hint="source_url"):
    """Return a typed hash, or None; never infer provider IDs from plain names.

    GitHub repository identities ignore descendant code paths conservatively.
    HF dataset case is preserved. Unknown URLs retain path and query exactly;
    different versions or encodings are not guessed equivalent. Bare names,
    prose, filenames, and source-bound hashes are not cross-source identifiers.
    """
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 4096 or not raw.isascii():
        return None
    value = raw.strip()
    if any(character.isspace() for character in value):
        return None
    if hint == "data_artifact_sha256":
        value = value.lower()
        return (hint, _reference(hint, "raw_bytes_sha256", value)) if HEX.fullmatch(value) else None
    candidate = value.removeprefix("doi:").removeprefix("DOI:").strip()
    if DOI.fullmatch(candidate):
        return "doi", _reference("doi", "doi", candidate.lower())
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    if "://" not in value:
        if hint == "github_repository" and len(value.split("/")) == 2:
            value = "https://github.com/" + value
        elif hint == "hf_dataset" and len(value.split("/")) in (1, 2) and all(GITHUB_PART.fullmatch(part) for part in value.split("/")):
            value = "https://huggingface.co/datasets/" + value
        else:
            return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname.lower()
        if host in {"doi.org", "dx.doi.org", "www.doi.org"}:
            candidate = urllib.parse.unquote(parsed.path.lstrip("/"))
            return ("doi", _reference("doi", "doi", candidate.lower())) if DOI.fullmatch(candidate) else None
        parts = parsed.path.strip("/").split("/")
        if host in {"github.com", "www.github.com"} and len(parts) >= 2:
            owner, repo = parts[0], parts[1].removesuffix(".git")
            if not GITHUB_PART.fullmatch(owner) or not GITHUB_PART.fullmatch(repo):
                return None
            return "github_repository", _reference("github_repository", "github", f"{owner}/{repo}".lower())
        if host == "huggingface.co" and len(parts) >= 2 and parts[0] == "datasets":
            if len(parts) > 3 and parts[2] in {"resolve", "tree", "blob"}:
                # A legacy single-name dataset plus route cannot safely be
                # distinguished from a namespace/repository with that name.
                return None
            identity = parts[1:3]
            if not all(GITHUB_PART.fullmatch(part) for part in identity):
                return None
            return "hf_dataset", _reference("hf_dataset", "huggingface", "/".join(identity))
        port = parsed.port
        netloc = host if port is None or (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)} else f"{host}:{port}"
        # Fragments do not change the retrieved resource; retain query semantics.
        normalized = urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
        return "source_url", _reference("source_url", "url", normalized)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Record:
    source: str
    token: str
    references: dict[str, frozenset[str]] = field(repr=False)
    legacy_group: str | None = field(default=None, repr=False)
    unresolved_reference_values: int = 0
    record_license_declared: bool = False
    local_dataset_declarations: frozenset[str] = field(default_factory=frozenset, repr=False)

    def __post_init__(self):
        if self.source not in SOURCES or not HEX.fullmatch(self.token):
            raise CustodyError()
        if set(self.references) != set(KINDS):
            raise CustodyError()
        if any(not HEX.fullmatch(value) for values in self.references.values() for value in values):
            raise CustodyError()
        if self.legacy_group is not None and not HEX.fullmatch(self.legacy_group):
            raise CustodyError()
        if any(not HEX.fullmatch(value) for value in self.local_dataset_declarations):
            raise CustodyError()


def record_token(source, pin, private_identity):
    return digest({"schema": SCHEMA, "source": source, "pin": pin, "private_identity": private_identity})


def empty_references():
    return {kind: set() for kind in KINDS}


def match_records(records):
    if not records or len({record.token for record in records}) != len(records):
        raise CustodyError()
    parents = {record.token: record.token for record in records}
    def find(token):
        while parents[token] != token:
            parents[token] = parents[parents[token]]
            token = parents[token]
        return token
    def join(left, right):
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)
    by_ref = {kind: {} for kind in RELATIONS}
    by_token = {record.token: record for record in records}
    for record in records:
        for kind in KINDS:
            for reference in record.references[kind]:
                by_ref[kind].setdefault(reference, []).append(record.token)
        if record.legacy_group is not None:
            by_ref["legacy_group_constraint"].setdefault(record.legacy_group, []).append(record.token)
        for reference in record.local_dataset_declarations:
            scoped = digest({"source": record.source, "declaration_sha256": reference})
            by_ref["source_scoped_dataset_declaration"].setdefault(scoped, []).append(record.token)
    shared = {kind: [] for kind in RELATIONS}
    for kind, refs in by_ref.items():
        for reference, members in sorted(refs.items()):
            members = sorted(members)
            for member in members[1:]:
                join(members[0], member)
            if len(members) >= 2:
                shared[kind].append({"reference_sha256": reference, "member_tokens": members,
                                     "source_counts": {source: sum(by_token[token].source == source for token in members) for source in SOURCES}})
    components = {}
    for record in records:
        components.setdefault(find(record.token), []).append(record.token)
    groups = []
    for members in sorted(components.values(), key=lambda values: sorted(values)):
        members = sorted(members)
        member_set = set(members)
        groups.append({"group_sha256": digest({"schema": SCHEMA, "members": members}),
                       "member_tokens": members, "member_count": len(members),
                       "source_counts": {source: sum(by_token[token].source == source for token in members) for source in SOURCES},
                       "supported_relation_counts": {kind: sum(bool(member_set.intersection(entry["member_tokens"])) for entry in shared[kind]) for kind in RELATIONS},
                       "members_without_canonical_reference": sum(not any(by_token[token].references.values()) for token in members),
                       "members_with_local_dataset_declaration": sum(bool(by_token[token].local_dataset_declarations) for token in members),
                       "independent_family_qualification": "unknown"})
    summary = {}
    for source in SOURCES:
        chosen = [record for record in records if record.source == source]
        summary[source] = {
            "record_count": len(chosen),
            "records_with_any_canonical_reference": sum(any(record.references.values()) for record in chosen),
            "records_without_canonical_reference": sum(not any(record.references.values()) for record in chosen),
            "unresolved_reference_value_count": sum(record.unresolved_reference_values for record in chosen),
            "record_license_declaration_count": sum(record.record_license_declared for record in chosen),
            "local_dataset_declaration_record_count": sum(bool(record.local_dataset_declarations) for record in chosen),
            "local_dataset_declaration_unique_count": len(set().union(*(record.local_dataset_declarations for record in chosen))),
            "local_dataset_declaration_fingerprints": sorted(set().union(*(record.local_dataset_declarations for record in chosen))),
            "canonical_reference_record_counts": {kind: sum(bool(record.references[kind]) for record in chosen) for kind in KINDS},
            "canonical_reference_unique_counts": {kind: len(set().union(*(record.references[kind] for record in chosen))) for kind in KINDS},
            "canonical_fingerprints": {kind: sorted(set().union(*(record.references[kind] for record in chosen))) for kind in KINDS},
            "per_record_license_qualification": "not_established",
        }
    result = {"schema": "canonical-lineage-graph-v1", "reference_schema": SCHEMA,
              "sources": summary, "groups": groups, "shared_references": shared,
              "total_records": len(records), "group_count": len(groups),
              "independent_family_count_established": 0, "validation_eligible_records": 0,
              "absence_of_match_proves_independence": False,
              "split_created": False, "existing_custody_mutated": False, "validation_lease_issued": False}
    validate_graph(result)
    return result


def validate_graph(value):
    counts = {source: "count" for source in SOURCES}
    kind_counts = {kind: "count" for kind in KINDS}
    source_spec = {"record_count": "count", "records_with_any_canonical_reference": "count",
                   "records_without_canonical_reference": "count", "unresolved_reference_value_count": "count",
                   "record_license_declaration_count": "count", "canonical_reference_record_counts": kind_counts,
                   "local_dataset_declaration_record_count": "count", "local_dataset_declaration_unique_count": "count",
                   "local_dataset_declaration_fingerprints": ["sha"],
                   "canonical_reference_unique_counts": kind_counts,
                   "canonical_fingerprints": {kind: ["sha"] for kind in KINDS},
                   "per_record_license_qualification": "not_established"}
    group_spec = {"group_sha256": "sha", "member_tokens": ["sha"], "member_count": "count", "source_counts": counts,
                  "supported_relation_counts": {kind: "count" for kind in RELATIONS},
                  "members_without_canonical_reference": "count", "independent_family_qualification": "unknown"}
    group_spec["members_with_local_dataset_declaration"] = "count"
    spec = {"schema": "canonical-lineage-graph-v1", "reference_schema": SCHEMA,
            "sources": {source: source_spec for source in SOURCES}, "groups": [group_spec],
            "shared_references": {kind: [{"reference_sha256": "sha", "member_tokens": ["sha"], "source_counts": counts}] for kind in RELATIONS},
            "total_records": "count", "group_count": "count", "independent_family_count_established": 0,
            "validation_eligible_records": 0, "absence_of_match_proves_independence": False,
            "split_created": False, "existing_custody_mutated": False, "validation_lease_issued": False}
    _check(value, spec)
    if value["total_records"] != sum(group["member_count"] for group in value["groups"]):
        raise CustodyError()
    return value
