"""Metadata-only primary process qualification; no payload/lease authority.

An observed-family allocation is scoped to pinned historical metadata, never
an independent_clean attestation. Original training membership is irreversible
within this protocol. The caller owns the exact input paths and their pins.
"""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.modular.canonical_lineage import SCHEMA as REF_SCHEMA, record_token, validate_graph
from evaluation.modular.custody import InventoryItem, SCHEMA as CUSTODY_SCHEMA
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.lineage_custodian import _git_pin, validate_receipt
from evaluation.modular.process_source_qualification import controller_metadata
from evaluation.modular.train_io import _safe_under
from research_loop.ontology import digest

SOURCES = ("discoverybench", "blade")
SEED = "research-loop-primary-observed-family-split-20260913-v1"
AUDIT_SCHEMA = "bounded-primary-process-access-audit-v1"
SPLIT_SCHEMA = "prospective-primary-observed-family-split-v1"
GROUP_SCHEMA = "primary-observed-family-v1"
GAPS = ["os_access_not_audited", "unlogged_historical_access_not_established",
        "model_pretraining_not_assessed", "cross_source_independence_not_proven",
        "metadata_relationship_coverage_incomplete", "upstream_data_terms_not_qualified",
        "selection_does_not_prove_model_call", "nonprimary_snapshot_bytes_not_reaudited",
        "complete_canonical_read_manifest_may_be_unavailable"]


class PinnedReads:
    """Pins precede interpretation; outputs contain locator hashes, not paths."""
    def __init__(self, inputs):
        self.inputs, self.observed = inputs, {}

    def raw(self, key):
        entry = self.inputs[key]
        path = Path(entry["path"]).resolve(strict=True)
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        _check(sha, "sha")
        if sha != entry["sha256"] or (path in self.observed and self.observed[path] != sha):
            raise CustodyError()
        self.observed[path] = sha
        return raw

    def json(self, key):
        return json.loads(self.raw(key))

    def opaque_file(self, path, expected):
        path = Path(path).resolve(strict=True)
        if path.is_symlink() or path.is_junction():
            raise CustodyError()
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        sha = hasher.hexdigest()
        if sha not in expected or (path in self.observed and self.observed[path] != sha):
            raise CustodyError()
        self.observed[path] = sha
        return sha

    def finish(self):
        for path, sha in list(self.observed.items()):
            self.opaque_file(path, {sha})
        return [{"locator_sha256": digest(str(path)), "sha256": sha}
                for path, sha in sorted(self.observed.items(), key=lambda row: str(row[0]))]


def literal_selection(raw, name):
    """Only a unique top-level literal list; never import upstream runners."""
    tree = ast.parse(raw)
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    if len(values) != 1:
        raise CustodyError()
    selected = ast.literal_eval(values[0])
    if (type(selected) is not list or not selected or any(type(v) not in (str, int) for v in selected)
            or len(selected) != len(set(selected))):
        raise CustodyError()
    return selected


def _inventory(config, reads):
    state = reads.json("custody")
    if state.get("schema") != CUSTODY_SCHEMA or digest(state.get("inventory")) != state.get("inventory_digest"):
        raise CustodyError()
    items = [InventoryItem.parse(row) for row in state["inventory"]]
    if ({source: sum(row.benchmark == source for row in items) for source in SOURCES} != config["expected_counts"]
            or any(row.benchmark not in SOURCES for row in items)):
        raise CustodyError()
    split = dict(state["split"])
    recorded = split.pop("digest")
    if digest(split) != recorded or split["inventory_digest"] != state["inventory_digest"]:
        raise CustodyError()
    domains = {row["item"]: row["domain"] for row in split["rows"]}
    if (len(domains) != len(items) or set(domains) != {f"{row.benchmark}:{row.task_id}" for row in items}
            or any(domain not in {"train", "validation", "quarantine"} for domain in domains.values())):
        raise CustodyError()
    return state, items, domains


def _source_index(config, reads, state, items, receipt, manifest):
    """Rebind archived graph tokens and hash exact inventory files, no decoding.

    The canonical read manifest distinguishes scientific data from containers.
    Hashing inventory bytes is not public task or reference interpretation.
    """
    if receipt["inventory_digest"] != state["inventory_digest"]:
        raise CustodyError()
    if manifest is not None and (digest(manifest) != receipt["read_manifest_sha256"] or len(manifest) != receipt["read_file_count"]):
        raise CustodyError()
    bindings = {row["locator_sha256"]: row for row in manifest} if manifest is not None else {}
    if manifest is not None and len(bindings) != len(manifest):
        raise CustodyError()
    root = Path(config["snapshot_root"]).resolve(strict=True)
    roots = {"discoverybench": root / "discovery/upstream/discoverybench",
             "blade": root / "scienceagent/work/BLADE/blade_bench/datasets"}
    pins = {"discoverybench": _git_pin(roots["discoverybench"]),
            "blade": _git_pin(roots["blade"].parent.parent)}
    for source in SOURCES:
        bound = receipt["source_bindings"][source]
        if (bound["source_pin_established"] != (pins[source] is not None)
                or bound["source_pin_hashes"] != ([digest(pins[source])] if pins[source] else [])):
            raise CustodyError()
    index, source_counts = {}, {s: 0 for s in SOURCES}
    aggregates = {s: {"metadata_container": [], "data_artifact": []} for s in SOURCES}
    for item in items:
        directory = _safe_under(roots[item.benchmark], item.relative_path)
        hashes = []
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or path.is_junction():
                raise CustodyError()
            if not path.is_file():
                continue
            sha = reads.opaque_file(path, set(item.content_hashes))
            hashes.append(sha)
            locator = digest(str(path.resolve()))
            kind = ("metadata_container" if ((item.benchmark == "blade" and path.name == "info.json") or
                    (item.benchmark == "discoverybench" and path.match("metadata_*.json"))) else
                    "data_artifact" if path.suffix.lower() == ".csv" and path.name != "annotations.csv" else None)
            if kind:
                aggregates[item.benchmark][kind].append(sha)
                source_counts[item.benchmark] += 1
            if locator in bindings:
                bound = bindings[locator]
                if bound["content_sha256"] != sha or bound["kind"] not in {"metadata_container", "data_artifact"}:
                    raise CustodyError()
        if sorted(hashes) != sorted(item.content_hashes):
            raise CustodyError()
        pin = pins[item.benchmark] or {"unresolved_pin_inventory_binding": state["inventory_digest"]}
        token = record_token(item.benchmark, pin, item.task_id)
        if token in index:
            raise CustodyError()
        index[token] = item
    for source in SOURCES:
        bound = receipt["source_bindings"][source]
        if source_counts[source] != bound["metadata_file_count"] + bound["data_artifact_file_count"]:
            raise CustodyError()
        for kind, key in (("metadata_container", "metadata_container_hashes"), ("data_artifact", "data_artifact_hashes")):
            if sorted(set(aggregates[source][kind])) != bound[key]:
                raise CustodyError()
    return index, source_counts


def _selection(reads, index, config):
    by_key = {(item.benchmark, item.task_id): token for token, item in index.items()}
    selected, call_observed, observations = set(), set(), []
    discovery = reads.json("discovery_manifest")
    rows = discovery.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise CustodyError()
    for row in rows:
        # Match the exact metadata directory, then bind its source bytes.
        path = Path(row["metadata_path"]).resolve(strict=True)
        matches = [token for token, item in index.items() if item.benchmark == "discoverybench"
                   and path.parent == _safe_under(Path(config["snapshot_root"]) / "discovery/upstream/discoverybench", item.relative_path)]
        if len(matches) != 1:
            raise CustodyError()
        token = matches[0]
        for field, sha_field in (("metadata_path", "metadata_sha256"), ("data_path", "data_sha256")):
            file = Path(row[field]).resolve(strict=True)
            if file.parent != path.parent or file not in reads.observed or reads.observed[file] != row[sha_field]:
                raise CustodyError()
        selected.add(token)
    observations.append({"kind": "discovery_selected", "selected_count": len(rows), "tokens": sorted(selected)})
    v1 = literal_selection(reads.raw("blade_runner"), "TASKS")
    v2 = reads.json("blade_v2_manifest")
    if v2.get("benchmark") != "BLADE" or v2.get("tasks") != literal_selection(reads.raw("blade_v2_runner"), "TASKS"):
        raise CustodyError()
    for kind, values in (("blade_runner_selected", v1), ("blade_v2_selected", v2["tasks"]),
                         ("blade_development_excluded", v2.get("development_exclusions", [])),
                         ("blade_unscorable_selected", v2.get("unscorable_without_reference", []))):
        if not isinstance(values, list) or any(type(v) is not str for v in values):
            raise CustodyError()
        tokens = [by_key[("blade", value)] for value in values]
        selected.update(tokens)
        observations.append({"kind": kind, "selected_count": len(tokens), "tokens": sorted(tokens)})
    # Presence of a fixed legacy receipt proves a call attempt, irrespective of
    # success/scientific score. No answer, prompt, or dynamic task key is read.
    receipt_stats = {"call_count": 0, "success_count": 0, "failure_count": 0, "known_tokens": 0,
                     "unknown_usage_count": 0}
    for entry in config.get("blade_call_receipts", []):
        token = by_key[("blade", entry["task_id"])]
        value = reads.json(entry["input"])
        if type(value.get("exit")) is not int or not isinstance(value.get("usage"), list):
            raise CustodyError()
        call_observed.add(token)
        receipt_stats["call_count"] += 1
        receipt_stats["success_count" if value["exit"] == 0 else "failure_count"] += 1
        usage = value["usage"]
        if len(usage) == 1 and all(type(usage[0].get(k)) is int and usage[0][k] >= 0 for k in ("input_tokens", "output_tokens")):
            receipt_stats["known_tokens"] += usage[0]["input_tokens"] + usage[0]["output_tokens"]
        else:
            receipt_stats["unknown_usage_count"] += 1
    for key in ("discovery_runner", "blade_manifest", "prepare_runner", "final_verification"):
        reads.raw(key)  # Frozen context evidence only; no outcome interpretation.
    budgets = []
    for entry in config.get("initial_budgets", []):
        budget = reads.json(entry["input"])
        if (entry["source"] not in SOURCES or any(type(budget.get(k)) is not int or budget[k] < 0 for k in ("calls", "tokens"))
                or type(budget.get("usage_incomplete")) is not bool):
            raise CustodyError()
        budgets.append({"source": entry["source"], "call_count": budget["calls"], "known_tokens": budget["tokens"],
                        "usage_incomplete": budget["usage_incomplete"], "call_status_breakdown_available": False})
    return selected, call_observed, observations, receipt_stats, budgets


def _later_runs(config, reads, index, domains):
    by_key = {(item.benchmark, item.task_id): token for token, item in index.items()}
    selected, output = set(), []
    for entry in config["runs"]:
        attempt, ledger = reads.json(entry["attempt"]), reads.json(entry["ledger"])
        metadata = controller_metadata(attempt, ledger)
        if attempt["schema"] == "m4-m5-train-controller-attempt-v1":
            expected = {"model_calls": len(ledger["calls"]), "known_model_tokens": ledger["tokens"],
                        "model_usage_incomplete": ledger["usage_incomplete"]}
            if (attempt.get("actual_model_usage") != expected
                    or attempt.get("model_policy_sha256") != ledger["config"].get("context_policy", {}).get("sha256")):
                raise CustodyError()
        elif Path(attempt["model_root"]).resolve() != Path(reads.inputs[entry["ledger"]]["path"]).resolve().parent:
            raise CustodyError()
        for packet in attempt["packet_receipts"]:
            identity = packet["identity"]
            token = by_key[(identity["benchmark"], identity["task_id"])]
            if identity["domain"] != "train" or domains[f"{identity['benchmark']}:{identity['task_id']}"] != "train":
                raise CustodyError()
            selected.add(token)
        output.append(metadata)
    return selected, output


def observed_groups(graph, index, known):
    """Reuse complete canonical closures, including paths through other sources.

    Preserve legacy scientific families. Entirely unmapped components share a
    source fallback; this is deliberately not per-question random splitting.
    """
    validate_graph(graph)
    parent = {token: token for token in index}
    def find(token):
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token
    def join(values):
        values = list(values)
        for token in values[1:]:
            left, right = find(values[0]), find(token)
            parent[max(left, right)] = min(left, right)
    seen, fallback, factors = set(), set(), {}
    for group in graph["groups"]:
        members = group["member_tokens"]
        if (members != sorted(set(members)) or group["member_count"] != len(members)
                or group["group_sha256"] != digest({"schema": REF_SCHEMA, "members": members})
                or seen.intersection(members)):
            raise CustodyError()
        seen.update(members)
        values = [token for token in members if token in index]
        for source in SOURCES:
            if sum(index[token].benchmark == source for token in values) != group["source_counts"][source]:
                raise CustodyError()
        join(values)
        if (group["members_without_canonical_reference"] == len(members)
                and group["members_with_local_dataset_declaration"] == 0):
            for token in values:
                fallback.add(token)
                factors.setdefault(("fallback", index[token].benchmark), []).append(token)
    if set(index) - seen:
        raise CustodyError()
    for token, item in index.items():
        factors.setdefault(("legacy", item.benchmark, item.source_group), []).append(token)
    for values in factors.values():
        join(values)
    groups = {}
    for token in sorted(index):
        groups.setdefault(find(token), []).append(token)
    return [{"group_sha256": digest({"schema": GROUP_SCHEMA, "members": members}),
             "member_tokens": members, "member_count": len(members),
             "source_counts": {source: sum(index[token].benchmark == source for token in members) for source in SOURCES},
             "known_train_member_count": len(set(members) & known),
             "fallback_member_count": len(set(members) & fallback), "independence_proven": False}
            for members in groups.values()]


def partition_primary(audit, groups):
    if (audit.get("schema") != AUDIT_SCHEMA or audit.get("gaps") != GAPS
            or audit.get("old_split_mutated") is not False):
        raise CustodyError()
    strata, allocated, seen = {}, [], set()
    for group in groups:
        members = group["member_tokens"]
        if (members != sorted(set(members)) or not members or seen.intersection(members)
                or group["group_sha256"] != digest({"schema": GROUP_SCHEMA, "members": members})
                or group["member_count"] != len(members) or sum(group["source_counts"].values()) != len(members)):
            raise CustodyError()
        seen.update(members)
        sources = tuple(s for s in SOURCES if group["source_counts"][s])
        if group["known_train_member_count"]:
            allocated.append({**group, "split": "train"})
        else:
            strata.setdefault(sources, []).append(group)
    strata_counts = []
    for sources, values in sorted(strata.items()):
        ranked = sorted(values, key=lambda row: hashlib.sha256(f"{SEED}:{row['group_sha256']}".encode()).hexdigest())
        count = (3 * len(ranked) + 9) // 10
        strata_counts.append({"source_counts": {s: int(s in sources) for s in SOURCES},
                              "candidate_groups": len(ranked), "validation_groups": count})
        allocated.extend({**group, "split": "validation" if i < count else "train"} for i, group in enumerate(ranked))
    allocated.sort(key=lambda row: row["group_sha256"])
    return {"schema": SPLIT_SCHEMA, "audit_sha256": digest(audit), "seed": SEED,
            "rule": "benchmark_set_stratified_sha256_rank_first_ceil_30_percent_groups",
            "groups": allocated, "strata": strata_counts,
            "counts": {split: sum(row["member_count"] for row in allocated if row["split"] == split) for split in ("train", "validation")},
            "source_counts": {source: {split: sum(row["source_counts"][source] for row in allocated if row["split"] == split)
                                       for split in ("train", "validation")} for source in SOURCES},
            "qualification_scope": "bounded_process_access_and_observed_relationships",
            "independence_proven": False, "old_split_mutated": False, "validation_lease_issued": False,
            "payload_export_count": 0}


def _audit_primary_process(config):
    reads = PinnedReads(config["inputs"])
    state, items, domains = _inventory(config, reads)
    receipt = reads.json("canonical_receipt")
    manifest = reads.json("canonical_manifest") if "canonical_manifest" in config["inputs"] else None
    validate_receipt(receipt)
    index, source_files = _source_index(config, reads, state, items, receipt, manifest)
    selected, called, observations, initial_cost, initial_budgets = _selection(reads, index, config)
    later_selected, later_runs = _later_runs(config, reads, index, domains)
    original_train = {token for token, item in index.items() if domains[f"{item.benchmark}:{item.task_id}"] == "train"}
    exposed = {token for token, item in index.items() if item.exposure == "exposed"}
    known = original_train | exposed | selected | called | later_selected
    groups = observed_groups(receipt["graph"], index, known)
    audit = {"schema": AUDIT_SCHEMA, "config_sha256": digest(config), "end_boundary_utc": datetime.now(timezone.utc).isoformat(),
             "start_boundary": "declared_initial_20260912_manifest_and_runner_bytes",
             "inventory_digest": state["inventory_digest"], "original_split_digest": state["split"]["digest"],
             "canonical_read_manifest_available": manifest is not None,
             "canonical_read_manifest_sha256": receipt["read_manifest_sha256"],
             "primary_aggregate_source_hashes_reverified": True,
             "source_verified_file_counts": source_files, "initial_selection_observations": observations,
             "initial_call_observations": initial_cost, "later_run_observations": later_runs,
             "initial_budget_observations": initial_budgets,
             "rows": [{"token": token, "source": item.benchmark, "original_train": token in original_train,
                       "known_exposure": token in exposed, "historically_selected": token in selected,
                       "legacy_call_receipt_observed": token in called, "later_projection_observed": token in later_selected,
                       "forced_train": token in known} for token, item in sorted(index.items())],
             "gaps": list(GAPS), "input_bindings": reads.finish(),
             "scope_observation": "unselected_rows_have_no_projection_observed_in_declared_metadata_scope",
             "old_split_mutated": False, "legacy_independent_clean_attestation": False,
             "validation_lease_issued": False, "payload_export_count": 0,
             "new_model_calls": 0, "new_network_calls": 0}
    return audit, groups


def audit_primary_process(config):
    try:
        return _audit_primary_process(config)
    except BaseException:
        raise CustodyError() from None


def seal_primary_process(destination, config):
    """Actual entrypoint retains fixed safe failure evidence, never payloads."""
    destination = Path(destination)
    if (destination.resolve().is_relative_to(Path(config["snapshot_root"]).resolve())
            or any(Path(entry["path"]).resolve().is_relative_to(destination.resolve()) for entry in config["inputs"].values())):
        raise CustodyError()
    destination.mkdir(parents=True, exist_ok=False)
    _write_new(destination / "intent.json", {"schema": SPLIT_SCHEMA, "config_sha256": digest(config), "seed": SEED})
    try:
        audit, groups = audit_primary_process(config)
        split = partition_primary(audit, groups)
        # The full byte check above closes before publication; repeat all declared
        # pins here as the final boundary without interpreting any source text.
        confirmed = PinnedReads(config["inputs"])
        for key in config["inputs"]:
            confirmed.raw(key)
        state, items, _ = _inventory(config, confirmed)
        _source_index(config, confirmed, state, items, confirmed.json("canonical_receipt"),
                      confirmed.json("canonical_manifest") if "canonical_manifest" in config["inputs"] else None)
        confirmed.finish()
        _write_new(destination / "process-audit.json", audit)
        _write_new(destination / "prospective-split.json", split)
        result = {"schema": "primary-process-seal-receipt-v1", "audit_sha256": digest(audit),
                  "split_sha256": digest(split), "counts": split["counts"], "source_counts": split["source_counts"],
                  "validation_lease_issued": False, "old_split_mutated": False, "payload_export_count": 0,
                  "model_calls": 0, "network_calls": 0}
        _write_new(destination / "seal-receipt.json", result)
        return result
    except BaseException:
        _write_new(destination / "failure.json", {"schema": "primary-process-seal-failure-v1", "status": "failed",
                                                  "safe_error": "metadata_binding_or_contract_failure",
                                                  "old_split_mutated": False, "payload_export_count": 0,
                                                  "model_calls": 0, "network_calls": 0})
        raise CustodyError() from None
