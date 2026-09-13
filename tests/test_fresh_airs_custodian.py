from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from evaluation.modular import fresh_airs_custodian as c


MARKER = "DYNAMIC_PRIVATE_KEY_AND_GOLD_DO_NOT_EXPORT"


class Transport:
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []

    def iter_bytes(self, url):
        self.calls.append(url)
        data = self.payloads[url]
        yield data[:8]
        yield data[8:]


def fixture_transport():
    contents = {"LICENSE": b"synthetic repository license"}
    for task in ("alpha", "beta"):
        root = f"airsbench/tasks/rad/{task}/"
        contents[root + "metadata.yaml"] = f"dataset: synthetic-shared\n{MARKER}:\n  {MARKER}: {MARKER}\n".encode()
        for name in ("project_description.md", "prepare.py", "evaluate.py", "evaluate_prepare.py"):
            contents[root + name] = MARKER.encode()
    entries = [{"path": name, "type": "blob", "size": len(data),
                "sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}
               for name, data in contents.items()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in contents.items():
            archive.writestr(f"airs-bench-{c.REVISION}/{name}", data)
    tree = {"sha": c.REVISION, "truncated": False, "tree": entries}
    return Transport({c.TREE_URL: json.dumps(tree).encode(), c.ARCHIVE_URL: buffer.getvalue()})


def baseline(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schema": "opaque-overlap-baseline-v1", "family_fingerprints": [],
                                "artifact_fingerprints": [], "publication_fingerprints": []}))
    return path


def run(tmp_path, transport=None):
    return c.acquire(private_store=tmp_path / "private", output=tmp_path / "public" / "receipt.json",
                     overlap_baseline=baseline(tmp_path), transport=transport or fixture_transport())


def test_synthetic_dynamic_keys_gold_code_and_text_never_leave_custody(tmp_path):
    receipt = run(tmp_path)
    c.validate_public(receipt)
    assert receipt["task_count"] == 2
    assert receipt["task_bundle_complete_count"] == 2
    assert receipt["metadata_components"][0]["member_count"] == 2
    assert receipt["validation_eligible_count"] == 0
    assert receipt["historical_exposure_status"] == "unknown"
    assert MARKER not in json.dumps(receipt)
    for path in (tmp_path / "public").iterdir():
        assert MARKER not in path.read_text()
    assert MARKER.encode() in (tmp_path / "private" / "archive.bin").read_bytes()


@pytest.mark.parametrize("mutation", ["top", "nested", "value", "type", "token"])
def test_recursive_allowlist_refuses_dynamic_output_channels(tmp_path, mutation):
    receipt = run(tmp_path)
    if mutation == "top":
        receipt[MARKER] = "secret"
    elif mutation == "nested":
        receipt["metadata_components"][0][MARKER] = "secret"
    elif mutation == "value":
        receipt["lineage_status"] = MARKER
    elif mutation == "type":
        receipt["task_count"] = True
    else:
        receipt["opaque_family_fingerprints"].append(MARKER)
    with pytest.raises(c.CustodyError) as caught:
        c.validate_public(receipt)
    assert MARKER not in str(caught.value)


def test_tampered_archive_retains_first_fetch_events_and_cannot_export(tmp_path):
    transport = fixture_transport()
    tree = json.loads(transport.payloads[c.TREE_URL])
    tree["tree"][0]["sha"] = "0" * 40
    transport.payloads[c.TREE_URL] = json.dumps(tree).encode()
    with pytest.raises(c.CustodyError):
        run(tmp_path, transport)
    assert (tmp_path / "private" / "archive.bin").exists()
    assert not (tmp_path / "public" / "receipt.json").exists()
    events = sorted((tmp_path / "private").glob("event-*.json"))
    assert json.loads(events[0].read_text())["event"] == "acquisition_intent"
    assert json.loads(events[-1].read_text())["event"] == "acquisition_failed_details_suppressed"
    with pytest.raises(c.CustodyError):
        c.acquire(private_store=tmp_path / "private", output=tmp_path / "another.json",
                  overlap_baseline=tmp_path / "baseline.json", transport=transport)


def test_cli_suppresses_library_stdout_stderr_and_exception_content(tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        import sys
        print(MARKER)
        print(MARKER, file=sys.stderr)
        raise RuntimeError(MARKER)
    monkeypatch.setattr(c, "acquire", fail)
    assert c.main(["--private-store", str(tmp_path / "private"), "--output", str(tmp_path / "out"),
                   "--overlap-baseline", str(tmp_path / "baseline")]) == 1
    captured = capsys.readouterr()
    assert MARKER not in captured.out + captured.err
    assert json.loads(captured.out)["status"] == "failed_details_suppressed"
    assert captured.err == ""


def test_real_entrypoint_with_synthetic_transport_exports_only_validated_receipt(tmp_path, monkeypatch, capsys):
    transport = fixture_transport()
    monkeypatch.setattr(c, "OfficialTransport", lambda: transport)
    base = baseline(tmp_path)
    out = tmp_path / "public" / "receipt.json"
    assert c.main(["--private-store", str(tmp_path / "private"), "--output", str(out),
                   "--overlap-baseline", str(base)]) == 0
    captured = capsys.readouterr()
    assert MARKER not in captured.out + captured.err
    assert transport.calls == [c.TREE_URL, c.ARCHIVE_URL]
    assert json.loads(captured.out)["receipt_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    c.validate_public(json.loads(out.read_text()))


def test_equivalent_factor_and_artifact_fingerprints_detect_overlap(tmp_path):
    one = run(tmp_path / "one")
    second = tmp_path / "second"
    second.mkdir()
    base = second / "baseline.json"
    base.write_text(json.dumps({"schema": "opaque-overlap-baseline-v1",
                               "family_fingerprints": one["opaque_family_fingerprints"],
                               "artifact_fingerprints": one["opaque_artifact_fingerprints"],
                               "publication_fingerprints": []}))
    two = c.acquire(private_store=second / "private", output=second / "public" / "receipt.json",
                    overlap_baseline=base, transport=fixture_transport())
    assert two["family_overlap_count"] > 0
    assert two["artifact_overlap_count"] > 0


def test_source_bound_group_tokens_are_not_cross_source_lineage_evidence(tmp_path):
    base = baseline(tmp_path)
    value = json.loads(base.read_text())
    value["family_fingerprints"] = ["opaque-source-family-v1-" + "a" * 64]
    base.write_text(json.dumps(value))
    receipt = c.acquire(private_store=tmp_path / "private", output=tmp_path / "public" / "receipt.json",
                        overlap_baseline=base, transport=fixture_transport())
    assert receipt["baseline_family_count"] == 1
    assert receipt["baseline_comparable_family_count"] == 0
    assert receipt["family_comparison_status"] == "exact_equalities_only_schema_domain_coverage_incomplete"
    assert receipt["validation_eligible_count"] == 0
