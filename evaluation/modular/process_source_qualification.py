"""Named, bounded process audit and prospective split; not independent_clean.

Reads fixed receipt metadata only. No existing custody state is changed and no
validation export/lease API exists here. Unknown pretraining is a declared gap.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.modular.canonical_lineage import normalize_reference, record_token, validate_graph
from evaluation.modular.extended_ingestion import _inside, _receipt
from evaluation.modular.fresh_airs_custodian import CustodyError, _write_new
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import digest

SOURCES = ("scicode", "scienceagentbench")
CONTROLLERS = ("train-panel-controller-attempt-v1", "q31-train-controller-attempt-v1", "m4-m5-train-controller-attempt-v1")
GAPS = ("os_access_not_audited", "unlogged_historical_access_not_established",
        "model_pretraining_not_assessed", "cross_source_independence_not_proven",
        "upstream_scientific_data_terms_require_artifact_binding")


class BoundReads:
    def __init__(self):
        self.reads = {}

    def read(self, path):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        value = hashlib.sha256(raw).hexdigest()
        if path in self.reads and self.reads[path] != value:
            raise CustodyError()
        self.reads[path] = value
        return json.loads(raw), value

    def finish(self):
        for path, value in self.reads.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != value:
                raise CustodyError()
        return [{"locator_sha256": digest(str(path)), "sha256": value}
                for path, value in sorted(self.reads.items(), key=lambda entry: str(entry[0]))]


def controller_metadata(attempt, ledger):
    if (attempt.get("schema") not in CONTROLLERS
            or ledger.get("config", {}).get("schema") != "codex-model-port-v1"):
        raise CustodyError()
    receipts = attempt.get("packet_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise CustodyError()
    benchmarks, identities = set(), []
    for receipt in receipts:
        identity = receipt.get("identity") if isinstance(receipt, dict) else None
        if (not isinstance(identity, dict) or identity.get("benchmark") not in
                {"discoverybench", "blade", "scicode", "scienceagentbench", "airsbench"}):
            raise CustodyError()
        benchmarks.add(identity["benchmark"])
        identities.append(digest(identity))
    calls = ledger.get("calls")
    if not isinstance(calls, list) or type(ledger.get("usage_incomplete")) is not bool:
        raise CustodyError()
    states = {key: 0 for key in ("reserved", "succeeded", "failed", "unknown", "over_budget")}
    for call in calls:
        state = call.get("status") if isinstance(call, dict) else None
        if state not in states:
            raise CustodyError()
        states[state] += 1
    tokens = ledger.get("tokens")
    if type(tokens) is not int or tokens < 0:
        raise CustodyError()
    return {"benchmark_counts": {key: sum(row["identity"]["benchmark"] == key for row in receipts)
                                  for key in ("discoverybench", "blade", "scicode", "scienceagentbench", "airsbench")},
            "identity_sha256": sorted(set(identities)), "call_count": len(calls), "call_status_counts": states,
            "known_tokens": tokens, "usage_incomplete": ledger["usage_incomplete"],
            "target_projection_observed": bool(benchmarks.intersection(SOURCES))}


def process_audit(config):
    """Verify an explicitly declared access scope; no claim about unlisted I/O.

    scope_review_sha256 binds the parent's scientific-safety scope decision.
    It is a review commitment, not a cryptographic identity authentication.
    """
    reads = BoundReads()
    state, state_sha = reads.read(config["extended_inventory"])
    imported, imported_sha = reads.read(config["import_metadata"])
    if (state_sha != imported.get("custody_state_sha256") or state.get("split") is not None
            or state.get("leases") or state.get("attestations")
            or state.get("inventory_digest") != imported.get("inventory_digest")
            or digest(state.get("inventory")) != state.get("inventory_digest")):
        raise CustodyError()
    metadata, metadata_sha = reads.read(config["metadata_receipt"])
    if (metadata.get("schema") != "extended-custodian-metadata-receipt-v1"
            or metadata.get("optimizer_access") != "none"):
        raise CustodyError()
    acquisitions = {}
    for source in SOURCES:
        receipt, sha = reads.read(config["acquisition_receipts"][source])
        if (receipt.get("schema") != "pinned-source-snapshot-receipt-v1"
                or receipt.get("source") != source
                or receipt.get("revision") != SOURCE_SNAPSHOTS[source].revision
                or receipt.get("payload_returned") is not False
                or receipt.get("task_projection_created") is not False):
            raise CustodyError()
        acquisitions[source] = sha
    runs = []
    for entry in config["runs"]:
        attempt, attempt_sha = reads.read(entry["attempt"])
        ledger, ledger_sha = reads.read(entry["ledger"])
        # Controller ownership of the ledger is verified without reading any
        # prompt, model response, request text, argv, or startup context.
        if attempt.get("schema") == "m4-m5-train-controller-attempt-v1":
            expected = {"model_calls": len(ledger.get("calls", [])), "known_model_tokens": ledger.get("tokens"),
                        "model_usage_incomplete": ledger.get("usage_incomplete")}
            policy_sha = ledger.get("config", {}).get("context_policy", {}).get("sha256")
            if (attempt.get("actual_model_usage") != expected or not isinstance(policy_sha, str)
                    or attempt.get("model_policy_sha256") != policy_sha):
                raise CustodyError()
            binding_kind = "scope_review_pair_and_usage_policy_equality"
        else:
            if Path(attempt.get("model_root", "")).resolve() != Path(entry["ledger"]).resolve().parent:
                raise CustodyError()
            binding_kind = "controller_declared_model_root"
        runs.append({"attempt_sha256": attempt_sha, "ledger_sha256": ledger_sha,
                     "controller_ledger_binding": binding_kind,
                     **controller_metadata(attempt, ledger)})
    if not runs or any(row["target_projection_observed"] for row in runs):
        raise CustodyError()
    review, review_sha = reads.read(config["scope_review"])
    if (review.get("schema") != "process-access-scope-review-v1"
            or review.get("decision") != "observed_process_scope_and_conservative_grouping"
            or review.get("run_locator_sha256") != sorted(digest(str(Path(row["attempt"]).resolve())) for row in config["runs"])
            or review.get("ledger_locator_sha256") != sorted(digest(str(Path(row["ledger"]).resolve())) for row in config["runs"])
            or review.get("gaps") != list(GAPS)):
        raise CustodyError()
    canonical, canonical_sha = reads.read(config["canonical_receipt"])
    validate_graph(canonical["graph"])
    return {"schema": "bounded-process-access-audit-v1", "scope_sha256": review_sha,
            "start_boundary_acquisition_receipts": acquisitions,
            "end_boundary_utc": datetime.now(timezone.utc).isoformat(),
            "included_ledger_observations": runs, "input_bindings": reads.finish(),
            "unchanged_extended_inventory_sha256": state_sha, "import_metadata_sha256": imported_sha,
            "metadata_receipt_sha256": metadata_sha,
            "canonical_receipt_sha256": canonical_sha,
            "observation": "no_target_projection_observed_in_declared_receipt_scope",
            "gaps": list(GAPS), "legacy_independent_clean_attestation": False,
            "os_access_isolation_verified": False, "existing_split_mutated": False,
            "validation_lease_issued": False}


def metadata_groups(private_root):
    """Exact metadata closures, with all unmapped records joined per source.

    SciCode has no canonical external references: all 80 atomic main-problem
    records form one fallback group. SAB preserves dataset-tree/source-path
    equality plus canonical repo equality; its unmapped records join together.
    """
    parent, by_token, input_hashes = {}, {}, {}

    def find(token):
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    factors = {}
    for source in SOURCES:
        spec = SOURCE_SNAPSHOTS[source]
        snapshot = Path(private_root) / "snapshots" / source / spec.revision
        receipt = _receipt(snapshot, source)
        input_hashes[source] = digest(receipt)
        rows = []
        if source == "scicode":
            for name in ("problems_dev.jsonl", "problems_test.jsonl"):
                rows.extend(json.loads(line) for line in _inside(snapshot, name).read_bytes().splitlines() if line.strip())
        else:
            with _inside(snapshot, "ScienceAgentBench.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        if len(rows) != {"scicode": 80, "scienceagentbench": 102}[source]:
            raise CustodyError()
        for index, row in enumerate(rows):
            token = record_token(source, spec.revision, index)
            parent[token], by_token[token] = token, source
            found = []
            if source == "scienceagentbench":
                value = row.get("github_name")
                repo = (normalize_reference(value, "github_repository") if isinstance(value, str)
                        and value.strip().lower() not in {"", "n/a", "na", "none", "null", "-"} else None)
                if repo:
                    found.append(digest({"kind": repo[0], "value": repo[1]}))
                for field in ("dataset_folder_tree", "src_file_or_path"):
                    value = row.get(field)
                    if isinstance(value, str) and value.strip().lower() not in {"", "n/a", "na", "none", "null", "-"}:
                        found.append(digest({"source": source, "field": field, "value": value.strip()}))
                if not repo:
                    found.append(digest({"source": source, "unmapped_fallback": True}))
            else:
                found.append(digest({"source": source, "unmapped_fallback": True}))
            for factor in found:
                previous = factors.setdefault(factor, token)
                left, right = find(token), find(previous)
                parent[max(left, right)] = min(left, right)
        if digest(_receipt(snapshot, source)) != input_hashes[source]:
            raise CustodyError()
    groups = {}
    for token in sorted(parent):
        groups.setdefault(find(token), []).append(token)
    return [{"group_sha256": digest({"schema": "observed-source-family-v1", "members": members}),
             "member_tokens": members, "member_count": len(members), "source": by_token[members[0]],
             "independence_proven": False, "known_core_relation": False} for members in groups.values()], input_hashes


def apply_canonical_closure(groups, graph):
    """Union shared observed factors across supplemental and old source groups.

    A received CSV/JSONL *container* hash is not a scientific data factor.
    Any observed link to an old primary source makes the whole closure train.
    """
    validate_graph(graph)
    by_token = {token: index for index, group in enumerate(groups) for token in group["member_tokens"]}
    parent = list(range(len(groups)))

    def find(index):
        while index != parent[index]:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    core_linked = set()
    seen = set()
    for group in graph["groups"]:
        selected = [token for token in group["member_tokens"] if token in by_token]
        seen.update(selected)
        for token in selected[1:]:
            left, right = find(by_token[selected[0]]), find(by_token[token])
            parent[max(left, right)] = min(left, right)
        if group["source_counts"]["discoverybench"] or group["source_counts"]["blade"]:
            core_linked.update(selected)
    if seen != set(by_token):
        raise CustodyError()
    merged = {}
    for index, group in enumerate(groups):
        merged.setdefault(find(index), []).append(group)
    result = []
    for selected in merged.values():
        members = sorted(token for group in selected for token in group["member_tokens"])
        sources = {group["source"] for group in selected}
        result.append({"group_sha256": digest({"schema": "observed-source-family-v1", "members": members}),
                       "member_tokens": members, "member_count": len(members),
                       "source": next(iter(sources)) if len(sources) == 1 else "mixed_extended",
                       "independence_proven": False, "known_core_relation": bool(set(members).intersection(core_linked))})
    return result


def prospective_split(audit, groups, *, seed, validation_percent=30):
    if (audit.get("schema") != "bounded-process-access-audit-v1"
            or audit.get("observation") != "no_target_projection_observed_in_declared_receipt_scope"
            or audit.get("legacy_independent_clean_attestation") is not False
            or audit.get("gaps") != list(GAPS)
            or type(validation_percent) is not int or not 1 <= validation_percent <= 99
            or not isinstance(seed, str) or not seed):
        raise CustodyError()
    tokens, allocation = set(), []
    for group in sorted(groups, key=lambda row: row["group_sha256"]):
        members = group["member_tokens"]
        if not members or len(members) != len(set(members)) or tokens.intersection(members):
            raise CustodyError()
        tokens.update(members)
        if group["member_count"] != len(members) or group["group_sha256"] != digest({"schema": "observed-source-family-v1", "members": members}):
            raise CustodyError()
        selected = int(digest({"seed": seed, "group_sha256": group["group_sha256"]}), 16) % 100 < validation_percent
        if group["known_core_relation"]:
            selected = False
        allocation.append({**group, "split": "validation" if selected else "train"})
    return {"schema": "prospective-observed-family-split-v1", "audit_sha256": digest(audit),
            "seed": seed, "validation_percent": validation_percent, "groups": allocation,
            "counts": {split: sum(row["member_count"] for row in allocation if row["split"] == split)
                       for split in ("train", "validation")},
            "qualification_scope": "bounded_process_access_and_observed_relationships",
            "independence_proven": False, "old_split_mutated": False, "validation_lease_issued": False}


def seal_new_split(destination, config, *, seed):
    # Caller supplies exact source locations, never a caller-asserted clean
    # audit or caller-invented family membership. Re-read all evidence here.
    audit = process_audit(config)
    groups, source_receipts = metadata_groups(config["extended_private_root"])
    for source in SOURCES:
        raw = Path(config["acquisition_receipts"][source]).read_bytes()
        if (hashlib.sha256(raw).hexdigest() != audit["start_boundary_acquisition_receipts"][source]
                or digest(json.loads(raw)) != source_receipts[source]):
            raise CustodyError()
    canonical_raw = Path(config["canonical_receipt"]).read_bytes()
    if hashlib.sha256(canonical_raw).hexdigest() != audit["canonical_receipt_sha256"]:
        raise CustodyError()
    groups = apply_canonical_closure(groups, json.loads(canonical_raw)["graph"])
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    result = prospective_split(audit, groups, seed=seed)
    result["source_receipt_digests"] = source_receipts
    _write_new(destination / "process-audit.json", audit)
    _write_new(destination / "prospective-split.json", result)
    # Tokens only; no payload reader/resolver is granted by this sealed result.
    return {"schema": "prospective-split-seal-receipt-v1", "split_sha256": digest(result),
            "audit_sha256": digest(audit), "counts": result["counts"],
            "sealed_root_locator_sha256": digest(str(destination.resolve())),
            "validation_lease_issued": False, "old_split_mutated": False}
