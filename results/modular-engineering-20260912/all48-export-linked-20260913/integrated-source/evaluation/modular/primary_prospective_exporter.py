"""Train-only primary partition broker with an explicit controller packet port."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluation.modular import primary_process_qualification as qualification
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.prospective_train_exporter import ProspectiveTrainExporter, _concrete
from evaluation.modular.train_io import PublicTrainPacket, _safe_under, prepare_primary_public_task
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import digest


@dataclass(frozen=True)
class PrimaryTrainExportItem:
    source: str
    token: str
    group_sha256: str
    input_bindings_digest: str

    def __post_init__(self):
        if self.source not in qualification.SOURCES:
            raise CustodyError()
        _check({key: value for key, value in self.data().items() if key != "source"},
               {"token": "sha", "group_sha256": "sha", "input_bindings_digest": "sha"})

    def data(self):
        return asdict(self)


class ConcreteReads(qualification.PinnedReads):
    """Check lexical paths and all ancestors before and after each byte read."""
    def raw(self, key):
        path = Path(self.inputs[key]["path"])
        before = _concrete(path)
        result = super().raw(key)
        if _concrete(path) != before:
            raise CustodyError()
        return result

    def opaque_file(self, path, expected):
        before = _concrete(path)
        result = super().opaque_file(path, expected)
        if _concrete(path) != before:
            raise CustodyError()
        return result


class PrimaryProspectiveTrainExporter(ProspectiveTrainExporter):
    sources = qualification.SOURCES
    item_type = PrimaryTrainExportItem
    max_items = 308

    def __init__(self, config, sealed_root, *, expected_split_digest, expected_audit_digest,
                 expected_split_sha256, expected_audit_sha256,
                 eligibility_path, eligibility_sha256, output_root, audit_root):
        super().__init__(config, sealed_root, expected_split_digest=expected_split_digest,
                         expected_audit_digest=expected_audit_digest, output_root=output_root, audit_root=audit_root)
        self.eligibility_path = _concrete(eligibility_path)
        _check(eligibility_sha256, "sha")
        self.eligibility_sha256 = eligibility_sha256
        _check({"split": expected_split_sha256, "audit": expected_audit_sha256}, {"split": "sha", "audit": "sha"})
        self.seal_file_sha256 = {"split": expected_split_sha256, "audit": expected_audit_sha256}
        self._index = {}

    def _private_root(self):
        return self.config["snapshot_root"]

    def _sealed_metadata(self):
        values = {}
        for key, name in (("split", "prospective-split.json"), ("audit", "process-audit.json")):
            path = self.sealed_root / name
            raw = _concrete(path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != self.seal_file_sha256[key]:
                raise CustodyError()
            _concrete(path)
            values[key] = json.loads(raw)
        return values["split"], values["audit"]

    def _eligibility(self, items):
        raw = _concrete(self.eligibility_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.eligibility_sha256:
            raise CustodyError()
        value = json.loads(raw)
        _check(value, {"schema": "primary-train-export-eligibility-v1", "split_sha256": "sha", "audit_sha256": "sha",
                       "train_export_enabled": True, "held_group_sha256": ["sha"], "held_member_tokens": ["sha"],
                       "review_evidence_sha256": ["sha"], "validation_access_enabled": False})
        if (value["split_sha256"] != self.expected_split_digest or value["audit_sha256"] != self.expected_audit_digest
                or any(item.token in value["held_member_tokens"] or item.group_sha256 in value["held_group_sha256"] for item in items)):
            raise CustodyError()

    def _allocation(self, items):
        # Only sealed metadata and the explicit eligibility record are read
        # before refusing validation, foreign groups, and stale caller inputs.
        split, audit = self._sealed_metadata()
        if (self.config.get("schema") != "primary-process-qualification-inputs-v1"
                or split.get("schema") != qualification.SPLIT_SCHEMA or audit.get("schema") != qualification.AUDIT_SCHEMA
                or digest(split) != self.expected_split_digest or digest(audit) != self.expected_audit_digest
                or audit.get("config_sha256") != digest(self.config)):
            raise CustodyError()
        groups = [{key: value for key, value in group.items() if key != "split"} for group in split["groups"]]
        if qualification.partition_primary(audit, groups) != split:
            raise CustodyError()
        sources = {row["token"]: row["source"] for row in audit["rows"]}
        allocation = {token: (group["group_sha256"], group["split"]) for group in split["groups"] for token in group["member_tokens"]}
        if set(allocation) != set(sources) or len(sources) != len(audit["rows"]):
            raise CustodyError()
        for item in items:
            if (sources.get(item.token) != item.source or allocation.get(item.token) != (item.group_sha256, "train")
                    or item.input_bindings_digest != digest(audit["input_bindings"])):
                raise CustodyError()
        self._eligibility(items)
        self._requested = tuple(items)
        self._active_audit = audit
        self._source_hashes = {row["locator_sha256"]: row["sha256"] for row in audit["input_bindings"]}
        return split, audit, allocation

    def _source_bindings(self):
        reads = ConcreteReads(self.config["inputs"])
        state, items, _ = qualification._inventory(self.config, reads)
        receipt = reads.json("canonical_receipt")
        manifest = reads.json("canonical_manifest") if "canonical_manifest" in self.config["inputs"] else None
        index, _ = qualification._source_index(self.config, reads, state, items, receipt, manifest)
        reads.finish()
        return state, index, receipt

    def _verify_audit_inputs(self, audit):
        self._sealed_metadata()
        self._eligibility(self._requested)
        self._source_bindings()  # Independent ancestor/reparse checks at entry.
        for entry in self.config["inputs"].values():
            _concrete(entry["path"])
        checked, _ = qualification.audit_primary_process(self.config)
        checked["end_boundary_utc"] = audit["end_boundary_utc"]
        if checked != audit:
            raise CustodyError()
        for entry in self.config["inputs"].values():
            _concrete(entry["path"])
        self._source_bindings()  # Also closes persistent substitutions at finish.

    def _verify_source_receipts(self, split, audit):
        state, self._index, receipt = self._source_bindings()
        self._inventory_digest = state["inventory_digest"]
        return {source: {"source": source, "inventory_digest": state["inventory_digest"],
                         "canonical_receipt_sha256": self.config["inputs"]["canonical_receipt"]["sha256"],
                         "source_binding": receipt["source_bindings"][source]} for source in self.sources}

    def _bound_public_bytes(self, path, expected):
        path = Path(path)
        if any(token in path.name.lower() for token in ("answer", "annotation", "reference", "label", "scorer", "gold")):
            raise CustodyError()
        before = _concrete(path)
        raw = before.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if (_concrete(path) != before or sha not in expected
                or self._source_hashes.get(digest(str(before))) != sha):
            raise CustodyError()
        return raw

    def _read_selected(self, items, indexes, receipts):
        result = {}
        for selected in items:
            item = self._index[selected.token]
            root = Path(self.config["snapshot_root"]) / ("discovery/upstream/discoverybench" if item.benchmark == "discoverybench" else "scienceagent/work/BLADE/blade_bench/datasets")
            source = _safe_under(root, item.relative_path)
            expected = set(item.content_hashes)
            if item.benchmark == "discoverybench":
                metadata = next(iter(sorted(source.glob("metadata_*.json"))))
                raw_bytes = self._bound_public_bytes(metadata, expected)
                raw = json.loads(raw_bytes)
                name = raw["datasets"][0]["name"]
                if (not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name
                        or ":" in name or name in {".", ".."}):
                    raise CustodyError()
                data = self._bound_public_bytes(source / name, expected)
                selector = {"metadata_file": metadata.name, "metadata_sha256": hashlib.sha256(raw_bytes).hexdigest(), "query_index": 0}
            else:
                raw = json.loads(self._bound_public_bytes(source / "info.json", expected))
                data = self._bound_public_bytes(source / "data.csv", expected)
                selector = None
            identity = DataIdentity(item.benchmark, item.task_id, selected.group_sha256, self._inventory_digest,
                                    self.expected_split_digest, "train")
            task = prepare_primary_public_task(identity, item.data(), raw, data)
            result[selected.token] = {"task": task, "csv_bytes": data, "selector": selector, "official_split": item.official_split}
        return result

    def _prepare_task(self, item, material):
        return material["task"]

    def _write_public_packet(self, target, item, task, material):
        self._eligibility(self._requested)
        metadata = {"identity": task.identity.data(), "source_group": task.identity.group_id,
                    "official_split": material["official_split"], "split_digest": self.expected_split_digest,
                    "csv_sha256": hashlib.sha256(material["csv_bytes"]).hexdigest(), "csv_byte_count": len(material["csv_bytes"]),
                    "packet_hash": task.content_hash, "export_token": item.token,
                    "input_bindings_digest": item.input_bindings_digest, "eligibility_sha256": self.eligibility_sha256}
        if material["selector"] is not None:
            metadata["source_selector"] = material["selector"]
        _write_new(target / "public.json", {"task": task.data(), "receipt": metadata})
        with (target / "data.csv").open("xb") as stream:
            stream.write(material["csv_bytes"])
            stream.flush()
            os.fsync(stream.fileno())
        return metadata

    def _before_exposure(self):
        self._eligibility(self._requested)

    def _before_publish(self):
        self._verify_audit_inputs(self._active_audit)

    def export_packets(self, items):
        items = tuple(items)
        result = self.export(items)
        by_token = {packet["export_token"]: packet for packet in result.receipt.data()["packets"]}
        return tuple(PublicTrainPacket(task, self.output_root / item.token / "public.json", self.output_root / item.token / "data.csv",
                                      FrozenRecord.from_dict(by_token[item.token])) for item, task in zip(items, result.tasks, strict=True))

    def export_controller_packets(self, token_allowlist):
        if not isinstance(token_allowlist, list) or not token_allowlist or len(token_allowlist) != len(set(token_allowlist)):
            raise CustodyError()
        # Construct typed requests from sealed metadata; a controller cannot
        # supply a replacement family/input binding or ask for another domain.
        split, audit = self._sealed_metadata()
        sources = {row["token"]: row["source"] for row in audit["rows"]}
        groups = {token: group["group_sha256"] for group in split["groups"] for token in group["member_tokens"]}
        try:
            items = [PrimaryTrainExportItem(sources[token], token, groups[token], digest(audit["input_bindings"])) for token in token_allowlist]
        except Exception:
            raise CustodyError() from None
        return self.export_packets(items)
