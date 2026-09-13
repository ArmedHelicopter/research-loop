"""Bounded AIRS preparation-slot supplement to the sealed metadata audit."""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import sys
from pathlib import Path

from evaluation.modular import lineage_custodian as custody
from evaluation.modular.canonical_lineage import KINDS, SOURCES, match_records, validate_graph
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.fresh_airs_hf_custodian import metadata_contract, safe_error
from evaluation.modular.lineage_static_loaders import COUNTERS, SLOTS, APIS, extract_fixed_slots, validate_factors
from research_loop.ontology import digest

SCHEMA = "airs-static-lineage-supplement-v1"


def validate_receipt(value):
    copy = dict(value)
    validate_graph(copy.pop("airs_graph"))
    records = copy.pop("records")
    for record in records:
        _check({key: val for key, val in record.items() if key != "factors"}, {"record_token": "sha"})
        validate_factors(record["factors"])
    _check(copy, {"schema": SCHEMA, "base_receipt_sha256": "sha", "input_config_sha256": "sha",
                  "implementation_sha256": ["sha"], "fixed_rules_sha256": "sha", "read_manifest_sha256": "sha",
                  "read_file_count": "count", "read_files_unchanged": True, "source_revision_sha256": "sha",
                  "payload_artifact_sha256": ["sha"], "counts": {name: "count" for name in COUNTERS},
                  "cross_source_equalities": {source: {kind: ["sha"] for kind in KINDS} for source in SOURCES if source != "airsbench"},
                  "static_reference_status": "syntax_declared_api_literals_not_runtime_verified",
                  "upstream_code_executed": False, "evaluator_slot_inspected": False, "new_artifact_downloaded": False,
                  "raw_code_exported": False, "old_split_mutated": False, "validation_lease_issued": False,
                  "independence_established": False, "historical_exposure_status": "unknown_not_changed"})
    if len(records) != value["airs_graph"]["total_records"]:
        raise CustodyError()
    return value


def run(*, config_path, baseline_path, baseline_sha256, private_audit, output):
    config_path, baseline_path = Path(config_path), Path(baseline_path)
    private_audit, output = Path(private_audit).resolve(), Path(output).resolve()
    if private_audit.exists() or output.exists() or output.is_relative_to(private_audit):
        raise CustodyError()
    if custody._sha(baseline_path) != baseline_sha256:
        raise CustodyError()
    base = custody.validate_receipt(json.loads(baseline_path.read_bytes()))
    config = json.loads(config_path.read_bytes())
    if set(config) != custody.CONFIG_KEYS or custody._sha(config_path) != base["config_sha256"]:
        raise CustodyError()
    for key in ("snapshot_root", "extended_private_root", "airs_private_root"):
        if output.is_relative_to(Path(config[key]).resolve()) or private_audit.is_relative_to(Path(config[key]).resolve()):
            raise CustodyError()
    private_audit.mkdir(parents=True)
    sources = [Path(__file__), Path(__file__).with_name("lineage_static_loaders.py"),
               Path(custody.__file__), Path(__file__).with_name("canonical_lineage.py"),
               Path(__file__).with_name("lineage_metadata_fields.py")]
    implementation = [custody._sha(path) for path in sources]
    _write_new(private_audit / "intent.json", {"schema": SCHEMA, "base_receipt_sha256": baseline_sha256,
               "config_sha256": custody._sha(config_path), "implementation_sha256": implementation,
               "fixed_rules_sha256": digest({"slots": SLOTS, "apis": APIS}), "python_executable": sys.executable})
    stage = "binding"
    try:
        audit = custody.Audit()
        audit.bind_read(baseline_path, "public_receipt")
        records = custody.airs_records(config, audit)
        expected = {token for group in base["graph"]["groups"] if group["source_counts"]["airsbench"] for token in group["member_tokens"]}
        if set(record.token for record in records) != expected or base["graph"]["sources"]["airsbench"]["records_with_any_canonical_reference"] != 0:
            raise CustodyError()
        root = Path(config["airs_private_root"])
        revision, _license, _recognized, artifacts = metadata_contract(root / "metadata.bin")
        # Exact already bound release slots only; no tree scan or evaluator text.
        rows = [row for index in range(len(artifacts)) for row in custody._csv(root / f"payload-{index:04d}.bin")]
        if len(rows) != len(records):
            raise CustodyError()
        stage = "static_parse"
        public_records, enriched = [], []
        counts = {name: 0 for name in COUNTERS}
        for row, record in zip(rows, records, strict=True):
            factors = extract_fixed_slots(row)
            public_records.append({"record_token": record.token, "factors": factors})
            for name in COUNTERS:
                counts[name] += factors["counts"][name]
            refs = {kind: record.references[kind] | frozenset(factors["canonical_fingerprints"][kind]) for kind in KINDS}
            enriched.append(dataclasses.replace(record, references=refs))
        stage = "match"
        graph = match_records(enriched)
        equalities = {source: {kind: sorted(set(graph["sources"]["airsbench"]["canonical_fingerprints"][kind]) & set(base["graph"]["sources"][source]["canonical_fingerprints"][kind])) for kind in KINDS} for source in SOURCES if source != "airsbench"}
        manifest = audit.finish()
        receipt = {"schema": SCHEMA, "base_receipt_sha256": baseline_sha256,
                   "input_config_sha256": custody._sha(config_path), "implementation_sha256": implementation,
                   "fixed_rules_sha256": digest({"slots": SLOTS, "apis": APIS}), "read_manifest_sha256": digest(manifest),
                   "read_file_count": len(manifest), "read_files_unchanged": True,
                   "source_revision_sha256": digest(revision), "payload_artifact_sha256": audit.bindings["airsbench"]["metadata_container_hashes"],
                   "records": public_records, "counts": counts, "airs_graph": graph, "cross_source_equalities": equalities,
                   "static_reference_status": "syntax_declared_api_literals_not_runtime_verified",
                   "upstream_code_executed": False, "evaluator_slot_inspected": False, "new_artifact_downloaded": False,
                   "raw_code_exported": False, "old_split_mutated": False, "validation_lease_issued": False,
                   "independence_established": False, "historical_exposure_status": "unknown_not_changed"}
        stage = "output"
        validate_receipt(receipt)
        _write_new(private_audit / "read-manifest.json", manifest)
        _write_new(private_audit / "receipt.json", receipt)
        _write_new(output, receipt)
        return receipt
    except BaseException as error:
        failure = {"schema": SCHEMA, "status": "failed", "stage": stage, **safe_error(error)}
        _write_new(private_audit / "failure.json", failure)
        _write_new(output.with_suffix(".failure.json"), failure)
        raise CustodyError() from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed-slot static AIRS metadata supplement")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--private-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run(config_path=args.config, baseline_path=args.baseline, baseline_sha256=args.baseline_sha256,
                private_audit=args.private_audit, output=args.output)
        print(json.dumps({"schema": SCHEMA, "status": "completed", "receipt_sha256": custody._sha(args.output)}, sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({"schema": SCHEMA, "status": "failed_details_suppressed"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
