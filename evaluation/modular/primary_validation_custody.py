"""Auditor-owned primary validation bridge; no optimizer or TRAIN export port.

Qualification and TRAIN freeze are independently supplied signed evidence. This
module never creates either proof, calibrates a scorer, or changes the original
prospective split's intentionally unproven independence flags. Private source
buffers reach only a configured evaluator, after a durable one-use consumption.
Process/mount separation and key custody remain deployment responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping

from evaluation.modular import primary_process_qualification as primary
from evaluation.modular.custody import CustodyStore, InventoryItem
from evaluation.modular.train_io import _safe_path, prepare_primary_public_task
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.panel_receipts import (
    FrozenPanel, PanelReceiptVerifier, RuntimeReceipt, ScientificScorerReceipt,
    ValidationAcceptance, verify_signed,
)
from research_loop.ontology import ContractError, canonical, digest


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digests(values) -> None:
    if (not isinstance(values, list) or not values or len(values) != len(set(values))
            or any(not isinstance(value, str) or len(value) != 64
                   or any(c not in "0123456789abcdef" for c in value) for value in values)):
        raise ContractError("primary validation requires nonempty digest evidence")


def _write(path: Path, raw: bytes) -> None:
    _safe_path(path).parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


@dataclass(frozen=True)
class PrimaryValidationMaterial:
    """Public input buffers for a private fixed evaluation, never optimizer output."""
    task: PublicTask
    csv: bytes
    source_receipt: FrozenRecord


@dataclass(frozen=True)
class PrimaryValidationResult:
    runtime: tuple[RuntimeReceipt, ...]
    scores: tuple[ScientificScorerReceipt, ...]
    acceptance: FrozenRecord


class PrimaryValidationCustodian:
    """Bridge a qualified sealed primary split to the existing acceptance API.

    ``source_provider`` is an auditor-owned local reader, not a model callback.
    It is called only for the exact leased tokens after lease consumption. The
    signed qualification pins its metadata/CSV bytes independently of this
    adapter. ``evaluate`` must use the configured isolated evaluator service.
    """

    def __init__(self, *, private_root: Path, sealed_split: FrozenRecord,
                 sealed_audit: FrozenRecord, qualification: FrozenRecord,
                 qualification_keys: Mapping[str, bytes], freeze: FrozenRecord,
                 freeze_keys: Mapping[str, bytes], candidate: FrozenRecord,
                 config: FrozenRecord, rubric: FrozenRecord,
                 custody_keys: Mapping[str, bytes], custody_authority: str,
                 calibration_keys: Mapping[str, bytes]):
        self.root = _safe_path(private_root)
        self.split, self.audit, self.qualification = sealed_split, sealed_audit, qualification
        self.freeze, self.candidate, self.config, self.rubric = freeze, candidate, config, rubric
        self._qualification_keys, self._freeze_keys = dict(qualification_keys), dict(freeze_keys)
        self._calibration_keys = dict(calibration_keys)
        if custody_authority not in custody_keys:
            raise ContractError("primary validation requires a configured custody authority")
        self._custody_authority, self._custody_key = custody_authority, custody_keys[custody_authority]
        self._rows, self._sources, self._freeze_body = self._inputs()
        inventory = [InventoryItem(row["source"], row["token"], row["group"], "primary-sealed",
                                   row["token"], (row["token"],)).data() for row in self._rows]
        inventory.sort(key=lambda row: (row["benchmark"], row["task_id"]))
        allocation = {"schema": "qualified-primary-custody-split-v1", "inventory_digest": digest(inventory),
            "primary_split_digest": sealed_split.content_hash, "primary_audit_digest": sealed_audit.content_hash,
            "qualification_digest": qualification.content_hash,
            "rows": [{"item": f"{r['source']}:{r['token']}", "group": r["group"], "domain": r["domain"],
                      "official_split": "primary-sealed", "exposure": "unknown",
                      "custodian_qualified": r["token"] in self._sources} for r in self._rows]}
        self._allocation = {**allocation, "digest": digest(allocation)}
        self._inventory = inventory
        if not self.root.exists():
            self.root.mkdir(parents=True)
        self.store = self._store()
        if self.store.state["split"] is None:
            if self.store.state["inventory"] or self.store.state["leases"]:
                raise ContractError("primary validation requires a fresh or exact existing custody state")
            # This is a projection of authenticated qualification, not a new
            # independence attestation or a random re-split of held-out data.
            self.store.state.update(inventory=inventory, inventory_digest=digest(inventory), split=self._allocation)
            self.store._save()
            _write(self.root / "input-evidence.json", canonical(self._input_evidence()).encode())
        self._check_state()

    def _store(self):
        return CustodyStore(self.root / "custody.json", calibration_keys=self._calibration_keys,
                           signing_authority_id=self._custody_authority, signing_key=self._custody_key)

    def _input_evidence(self):
        return {name: getattr(self, name).data() for name in
                ("split", "audit", "qualification", "freeze", "candidate", "config", "rubric")}

    def _inputs(self):
        split, audit = self.split.data(), self.audit.data()
        if (split.get("schema") != primary.SPLIT_SCHEMA or audit.get("schema") != primary.AUDIT_SCHEMA
                or split.get("audit_sha256") != self.audit.content_hash):
            raise ContractError("primary validation sealed source binding mismatch")
        groups = [{k: v for k, v in group.items() if k != "split"} for group in split["groups"]]
        if primary.partition_primary(audit, groups) != split:
            raise ContractError("primary validation allocation does not replay")
        by_token = {row["token"]: row for row in audit["rows"]}
        rows = [{"token": token, "group": group["group_sha256"], "domain": group["split"],
                 "source": by_token[token]["source"]} for group in split["groups"] for token in group["member_tokens"]]
        if (len(by_token) != len(audit["rows"]) or len(rows) != len(by_token)
                or {row["token"] for row in rows} != set(by_token)
                or any(row["source"] not in primary.SOURCES for row in rows)):
            raise ContractError("primary validation membership mismatch")
        qualified = verify_signed(self.qualification, self._qualification_keys,
                                  schema="primary-validation-qualification-v1")
        fields = {"schema", "authority", "decision", "scope", "split_digest", "audit_digest", "input_bindings_digest",
                  "source_evidence_digests", "exposure_evidence_digests", "relationship_evidence_digests", "sources"}
        if (set(qualified) != fields or qualified["decision"] != "qualified_for_acceptance"
                or qualified["scope"] != "recorded_primary_split_provenance_exposure_v1"
                or qualified["split_digest"] != self.split.content_hash or qualified["audit_digest"] != self.audit.content_hash
                or qualified["input_bindings_digest"] != digest(audit["input_bindings"])):
            raise ContractError("independent primary qualification is absent or bound to another split")
        for field in ("source_evidence_digests", "exposure_evidence_digests", "relationship_evidence_digests"):
            _digests(qualified[field])
        sources = {}
        for source in qualified["sources"]:
            if set(source) != {"token", "benchmark", "metadata_sha256", "csv_sha256", "official_split"}:
                raise ContractError("primary validation source receipt shape mismatch")
            _digests([source["metadata_sha256"], source["csv_sha256"]])
            if source["token"] in sources or not isinstance(source["official_split"], str):
                raise ContractError("primary validation duplicate or malformed source")
            sources[source["token"]] = source
        held = {row["token"]: row for row in rows if row["domain"] == "validation"}
        if (set(sources) != set(held) or {r["benchmark"] for r in sources.values()} != set(primary.SOURCES)
                or any(sources[token]["benchmark"] != row["source"] for token, row in held.items())
                or any(by_token[token].get("forced_train") is not False for token in held)):
            raise ContractError("qualification must cover only the exact held-out primary family")
        freeze = verify_signed(self.freeze, self._freeze_keys, schema="primary-validation-train-freeze-v1")
        fields = {"schema", "authority", "status", "domain", "candidate_digest", "config_digest", "rubric_digest",
                  "selection_rule_digest", "training_receipts_digest", "scorer_digest", "protocol_digest",
                  "acceptance_criteria_digest", "panel_design_digest", "package_digests"}
        if (set(freeze) != fields or freeze["status"] != "frozen" or freeze["domain"] != "train"
                or freeze["candidate_digest"] != self.candidate.content_hash
                or freeze["config_digest"] != self.config.content_hash or freeze["rubric_digest"] != self.rubric.content_hash):
            raise ContractError("validation requires the unchanged independently frozen TRAIN candidate/config/rubric")
        for field in ("selection_rule_digest", "training_receipts_digest", "scorer_digest", "protocol_digest", "acceptance_criteria_digest", "panel_design_digest"):
            _digests([freeze[field]])
        _digests(freeze["package_digests"])
        return sorted(rows, key=lambda row: (row["source"], row["token"])), sources, freeze

    def _check_state(self):
        self._inputs()
        self.store = self._store()
        if (self.store.state["inventory"] != self._inventory or self.store.state["split"] != self._allocation
                or self.store.state["attestations"]
                or (self.root / "input-evidence.json").read_bytes() != canonical(self._input_evidence()).encode()):
            raise ContractError("primary validation retained input/custody drift")

    def identities(self) -> tuple[DataIdentity, ...]:
        """Private panel construction only; tokens never leave in the aggregate."""
        self._check_state()
        return tuple(DataIdentity(row["source"], row["token"], row["group"], digest(self._inventory),
                                  self._allocation["digest"], "validation")
                     for row in self._rows if row["domain"] == "validation")

    def _panel(self, panel):
        self._check_state()
        freeze = self._freeze_body
        if (not isinstance(panel, FrozenPanel) or panel.domain != "validation" or panel.stage != "V_final"
                or panel.candidate_digest != self.candidate.content_hash
                or primary_validation_design_digest(panel) != freeze["panel_design_digest"]
                or panel.acceptance_criteria.content_hash != freeze["acceptance_criteria_digest"]
                or {cell.scorer_digest for cell in panel.cells} != {freeze["scorer_digest"]}
                or sorted({cell.package_digest for cell in panel.cells}) != sorted(freeze["package_digests"])
                or set(panel.required_benchmarks) != set(primary.SOURCES)
                or not {cell.identity for cell in panel.cells} <= set(self.identities())):
            raise ContractError("primary validation panel differs from the frozen candidate or custody")

    def lease(self, panel: FrozenPanel, calibration: FrozenRecord) -> str:
        self._panel(panel)
        return self.store.lease_panel(panel, calibration_receipt=calibration,
                                      protocol_digest=self._freeze_body["protocol_digest"])["id"]

    def run(self, *, panel: FrozenPanel, lease_id: str, calibration: FrozenRecord,
            source_provider: Callable[[str], tuple[bytes, bytes]],
            evaluate: Callable[[FrozenPanel, tuple[PrimaryValidationMaterial, ...], FrozenRecord], PrimaryValidationResult],
            verifier: PanelReceiptVerifier) -> FrozenRecord:
        self._panel(panel)
        lease = self.store.state["leases"].get(lease_id)
        if lease is None or lease["calibration_receipt_digest"] != calibration.content_hash:
            raise ContractError("primary validation calibration/lease mismatch")
        self.store.consume_validation(lease_id, panel_digest=panel.digest, arm_schedule=list(panel.arm_schedule))
        issued = self.store.issued_validation_receipt(lease_id)
        destination = self.root / "runs" / lease_id
        destination.mkdir(parents=True, exist_ok=False)
        _write(destination / "consumed-lease.json", canonical(issued.data()).encode())
        try:
            materials = []
            for identity in sorted({cell.identity for cell in panel.cells}, key=lambda row: (row.benchmark, row.task_id)):
                source = self._sources[identity.task_id]
                metadata, csv = source_provider(identity.task_id)
                if _sha(metadata) != source["metadata_sha256"] or _sha(csv) != source["csv_sha256"]:
                    raise ContractError("primary validation source byte pin mismatch")
                task = prepare_primary_public_task(identity, source, json.loads(metadata), csv)
                if {cell.task_digest for cell in panel.cells if cell.identity == identity} != {task.content_hash}:
                    raise ContractError("primary validation public task subject mismatch")
                _write(destination / "sources" / identity.task_id / "metadata.json", metadata)
                _write(destination / "sources" / identity.task_id / "data.csv", csv)
                materials.append(PrimaryValidationMaterial(task, csv, FrozenRecord.from_dict(source)))
            result = evaluate(panel, tuple(materials), issued)
            if not isinstance(result, PrimaryValidationResult):
                raise ContractError("primary validation evaluator must return typed retained receipts")
            evidence = {"schema": "primary-validation-evidence-v1", "panel_digest": panel.digest,
                        "input_evidence_digest": digest(self._input_evidence()), "lease": issued.data(),
                        "calibration": calibration.data(), "acceptance": result.acceptance.data(),
                        "runtime": [{**PanelReceiptVerifier._runtime_data(row), "trace_path": str(_safe_path(row.trace_path)),
                                     "trace_sha256": _sha(_safe_path(row.trace_path).read_bytes())} for row in result.runtime],
                        "scores": [{"cell_key": list(row.cell_key), "receipt": row.receipt.data()} for row in result.scores]}
            _write(destination / "evidence.json", canonical(evidence).encode())
            return self.replay(panel=panel, lease_id=lease_id, verifier=verifier)
        except BaseException as exc:
            _write(destination / "failure.json", canonical({"schema": "primary-validation-failure-v1",
                "status": "failed_after_consumption", "error_type": type(exc).__name__,
                "panel_digest": panel.digest, "lease_id": lease_id, "retry_permitted": False}).encode())
            raise

    def replay(self, *, panel: FrozenPanel, lease_id: str, verifier: PanelReceiptVerifier) -> FrozenRecord:
        """Recompute acceptance without reopening an execution or source provider."""
        self._panel(panel)
        destination = self.root / "runs" / lease_id
        evidence = json.loads(_safe_path(destination / "evidence.json").read_bytes())
        issued = self.store.issued_validation_receipt(lease_id)
        if (evidence["panel_digest"] != panel.digest or evidence["input_evidence_digest"] != digest(self._input_evidence())
                or evidence["lease"] != issued.data()
                or json.loads((destination / "consumed-lease.json").read_bytes()) != issued.data()):
            raise ContractError("primary validation retained subject/lease mismatch")
        for identity in {cell.identity for cell in panel.cells}:
            source = self._sources[identity.task_id]
            for filename, field in (("metadata.json", "metadata_sha256"), ("data.csv", "csv_sha256")):
                if _sha(_safe_path(destination / "sources" / identity.task_id / filename).read_bytes()) != source[field]:
                    raise ContractError("primary validation retained source drift")
        runtime = []
        for row in evidence["runtime"]:
            path = _safe_path(Path(row["trace_path"]))
            if _sha(path.read_bytes()) != row["trace_sha256"]:
                raise ContractError("primary validation retained runtime drift")
            runtime.append(RuntimeReceipt(tuple(row["cell_key"]), row["status"], path,
                                          row["trace_digest"], row["output_digest"], row["failure_reason"]))
        scores = tuple(ScientificScorerReceipt(tuple(row["cell_key"]), FrozenRecord.from_dict(row["receipt"])) for row in evidence["scores"])
        validation = ValidationAcceptance(issued, FrozenRecord.from_dict(evidence["acceptance"]),
            FrozenRecord.from_dict(evidence["calibration"]), self._freeze_body["protocol_digest"])
        verdict = verifier.verify(panel, tuple(runtime), scorer_receipts=scores, validation=validation)
        if verdict.decision not in {"accepted", "rejected", "inconclusive"} or not verdict.scientific_verified:
            raise ContractError("primary validation requires independently verified acceptance")
        aggregate = FrozenRecord.from_dict({"schema": "primary-validation-aggregate-v1", "domain": "validation",
            "role": "acceptance_only", "candidate_digest": panel.candidate_digest, "panel_digest": panel.digest,
            "decision": verdict.decision, "observed_cells": verdict.observed_cells, "failures": verdict.failures,
            "unscored": verdict.unscored, "blocked": verdict.blocked, "private_evidence_digest": digest(evidence),
            "optimization_feedback_permitted": False})
        output = destination / "aggregate.json"
        if output.exists():
            if output.read_bytes() != canonical(aggregate.data()).encode():
                raise ContractError("primary validation retained aggregate drift")
        else:
            _write(output, canonical(aggregate.data()).encode())
        return aggregate


def primary_validation_design_digest(panel) -> str:
    """Freeze the design before private task extraction; no scores enter it."""
    return digest({"stage": panel.stage, "scope_ids": list(panel.scope_ids),
                   "legal_arm_grids": {key: value.data() for key, value in panel.legal_arm_grids.items()},
                   "combinations": panel.combinations.data(), "required_benchmarks": list(panel.required_benchmarks)})
