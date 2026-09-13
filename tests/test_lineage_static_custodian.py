import csv
import hashlib
import io
import json

import pytest

from evaluation.modular import fresh_airs_hf_custodian as hf, lineage_custodian as c, lineage_static_custodian as s
from research_loop.ontology import digest

SECRET = "PRIVATE_EVALUATOR_DYNAMIC_KEY"


@pytest.fixture
def static_fixture(tmp_path):
    row = {"metadata.yaml": "dataset: local-label\n", "prepare.py": "from datasets import load_dataset\nload_dataset('owner/corpus', revision='v1')",
           "evaluate_prepare.py": "", "evaluate.py": SECRET + " !!!", SECRET: SECRET}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    data = stream.getvalue().encode()
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    class Transport:
        def iter_bytes(self, url):
            if url == hf.API_URL:
                yield json.dumps({"id": hf.REPO, "sha": "c" * 40, "cardData": {"license": "cc-by-nc-4.0"},
                                  "siblings": [{"rfilename": "data.csv", "size": len(data), "blobId": blob}]}).encode()
            else:
                yield data
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema": "opaque-overlap-baseline-v1", "family_fingerprints": [], "artifact_fingerprints": [], "publication_fingerprints": []}))
    private, public = tmp_path / "airs-private", tmp_path / "public" / "receipt.json"
    hf.acquire(private_store=private, output=public, overlap_baseline=empty, transport=Transport())
    config = {key: str(tmp_path / key) for key in c.CONFIG_KEYS}
    config.update(schema="canonical-lineage-input-locations-v1", airs_private_root=str(private), airs_public_receipt=str(public))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    audit = c.Audit()
    records = c.airs_records(config, audit)
    manifest = audit.finish()
    base = {"schema": c.SCHEMA, "inventory_digest": "a" * 64, "config_sha256": c._sha(config_path),
            "field_rules_sha256": "a" * 64, "implementation_sha256": [], "runtime_metadata_sha256": "a" * 64,
            "read_manifest_sha256": digest(manifest), "read_file_count": len(manifest), "read_files_unchanged": True,
            "source_bindings": audit.bindings, "graph": c.match_records(records),
            "raw_private_payload_returned": False, "current_process_payload_exported": False,
            "historical_exposure_status": "unknown_not_changed", "os_access_isolation_verified": False,
            "old_split_mutated": False, "validation_lease_issued": False}
    c.validate_receipt(base)
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base))
    return config_path, base_path, private


def args(tmp_path, fixture):
    config, baseline, private = fixture
    return ["--config", str(config), "--baseline", str(baseline), "--baseline-sha256", c._sha(baseline),
            "--private-audit", str(tmp_path / "audit"), "--output", str(tmp_path / "out" / "receipt.json")]


def test_fixed_file_entrypoint_supplements_bound_receipt_without_evaluator_parse(tmp_path, static_fixture, capsys):
    config, baseline, private = static_fixture
    before = (private / "payload-0000.bin").read_bytes()
    assert s.main(args(tmp_path, static_fixture)) == 0
    receipt = s.validate_receipt(json.loads((tmp_path / "out" / "receipt.json").read_bytes()))
    assert receipt["counts"]["resolved_call_count"] == 1
    assert receipt["counts"]["slot_present_count"] == 1
    assert receipt["counts"]["syntax_error_count"] == 0
    assert receipt["airs_graph"]["sources"]["airsbench"]["records_with_any_canonical_reference"] == 1
    assert receipt["base_receipt_sha256"] == c._sha(baseline)
    assert SECRET not in json.dumps(receipt) + capsys.readouterr().out
    assert before == (private / "payload-0000.bin").read_bytes()


def test_tampered_bound_payload_and_raw_parser_exception_are_suppressed(tmp_path, static_fixture, monkeypatch, capsys):
    def fail(_row):
        raise ValueError(SECRET)
    monkeypatch.setattr(s, "extract_fixed_slots", fail)
    assert s.main(args(tmp_path, static_fixture)) == 1
    failure = json.loads((tmp_path / "out" / "receipt.failure.json").read_bytes())
    assert failure["stage"] == "static_parse"
    assert SECRET not in json.dumps(failure) + capsys.readouterr().out


def test_payload_must_still_match_first_acquisition_hash(tmp_path, static_fixture, capsys):
    config, baseline, private = static_fixture
    (private / "payload-0000.bin").write_text(SECRET)
    assert s.main(args(tmp_path, static_fixture)) == 1
    failure = json.loads((tmp_path / "out" / "receipt.failure.json").read_bytes())
    assert failure["stage"] == "binding"
    assert SECRET not in json.dumps(failure) + capsys.readouterr().out
