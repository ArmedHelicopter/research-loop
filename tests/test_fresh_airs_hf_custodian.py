import hashlib
import json
import ssl
import urllib.error

import pytest

from evaluation.modular import fresh_airs_hf_custodian as h
from evaluation.modular.fresh_airs_custodian import CustodyError

SECRET = "PRIVATE_DYNAMIC_KEY_TASK_GOLD_CODE"


class Transport:
    def __init__(self):
        self.pin = "a" * 40
        self.name = f"data/{SECRET}.jsonl"
        self.payload = b"\n".join(json.dumps({SECRET: {SECRET: SECRET}, "files": {"metadata.yaml": f"dataset: shared\n{SECRET}: {SECRET}"}}).encode() for _ in range(2))
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.calls = []

    def iter_bytes(self, url):
        self.calls.append(url)
        if url == h.API_URL:
            value = {"id": h.REPO, "sha": self.pin,
                     "cardData": {"license": "cc-by-nc-4.0", SECRET: SECRET},
                     "siblings": [{"rfilename": self.name, "size": len(self.payload),
                                   "lfs": {"sha256": self.sha}}]}
            yield json.dumps(value).encode()
        else:
            assert f"/resolve/{self.pin}/" in url
            yield self.payload


def baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schema": "opaque-overlap-baseline-v1", "family_fingerprints": ["opaque-source-family-v1-" + "b" * 64],
                                "artifact_fingerprints": [], "publication_fingerprints": []}))
    return path


def test_hf_cli_seals_pin_and_never_exports_dynamic_keys_or_task_content(tmp_path, monkeypatch, capsys):
    transport = Transport()
    monkeypatch.setattr(h, "OfficialTransport", lambda: transport)
    out = tmp_path / "public" / "receipt.json"
    private = tmp_path / "private"
    base = baseline(tmp_path)
    probe = h.metadata_probe(private_store=tmp_path / "probe-private", output=tmp_path / "probe-public" / "probe.json", transport=transport)
    assert h.main(["--private-store", str(private), "--output", str(out), "--overlap-baseline", str(base),
                   "--expected-revision", transport.pin, "--expected-contract", probe["payload_contract_sha256"]]) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + out.read_text()
    receipt = h.validate_public(json.loads(out.read_text()))
    assert receipt["task_count"] == 2
    assert receipt["metadata_components"][0]["member_count"] == 2
    assert receipt["baseline_comparable_family_count"] == 0
    assert receipt["validation_eligible_count"] == 0
    events = [json.loads(p.read_text()) for p in sorted(private.glob("event-*.json"))]
    pin_index = next(i for i,e in enumerate(events) if e["event"] == "fixed_revision_bound_before_payload_fetch")
    fetch_index = next(i for i,e in enumerate(events) if e.get("artifact_kind") == "payload-0000")
    assert pin_index < fetch_index
    assert events[pin_index]["revision"] == transport.pin


@pytest.mark.parametrize("error,category", [
    (urllib.error.HTTPError("https://example.com/" + SECRET, 403, SECRET, {}, None), "http"),
    (urllib.error.URLError(ssl.SSLCertVerificationError(SECRET)), "tls"),
    (urllib.error.URLError(TimeoutError(SECRET)), "timeout"),
    (urllib.error.URLError(SECRET), "network"),
    (RuntimeError(SECRET), "other"),
])
def test_fixed_error_categories_do_not_export_exception_text(error, category):
    result = h.safe_error(error)
    assert result["category"] == category
    assert SECRET not in json.dumps(result)


def test_fetch_failure_keeps_events_and_exports_only_fixed_failure_fields(tmp_path):
    class Failed:
        def iter_bytes(self, url):
            raise urllib.error.HTTPError(url, 503, SECRET, {}, None)
            yield b""
    out = tmp_path / "public" / "receipt.json"
    with pytest.raises(CustodyError):
        h.acquire(private_store=tmp_path / "private", output=out,
                  overlap_baseline=baseline(tmp_path), transport=Failed())
    assert not out.exists()
    failure = json.loads(out.with_suffix(".failure.json").read_text())
    assert failure["http_status"] == 503
    assert failure["stage"] == "metadata"
    assert SECRET not in json.dumps(failure)


def test_hf_hash_mismatch_does_not_parse_or_publish(tmp_path, monkeypatch):
    transport = Transport()
    transport.sha = "0" * 64
    called = []
    monkeypatch.setattr(h, "read_rows", lambda *args: called.append(True))
    out = tmp_path / "public" / "receipt.json"
    with pytest.raises(CustodyError):
        h.acquire(private_store=tmp_path / "private", output=out,
                  overlap_baseline=baseline(tmp_path), transport=transport)
    assert not called
    assert not out.exists()
    assert json.loads(out.with_suffix(".failure.json").read_text())["category"] == "contract"


def test_hf_public_schema_rejects_extra_nested_mapping_key(tmp_path):
    receipt = h.acquire(private_store=tmp_path / "private", output=tmp_path / "public" / "receipt.json",
                        overlap_baseline=baseline(tmp_path), transport=Transport())
    receipt["metadata_components"][0][SECRET] = SECRET
    with pytest.raises(CustodyError):
        h.validate_public(receipt)


def test_metadata_only_emits_no_dynamic_names_and_fetches_no_payload(tmp_path):
    transport = Transport()
    receipt = h.metadata_probe(private_store=tmp_path / "private", output=tmp_path / "public" / "receipt.json", transport=transport)
    assert SECRET not in json.dumps(receipt)
    assert receipt["json_artifacts"] == 1
    assert receipt["task_payload_fetched"] is False
    assert transport.calls == [h.API_URL]


def test_changed_predeclared_pin_refused_before_payload_download(tmp_path):
    transport = Transport()
    with pytest.raises(CustodyError):
        h.acquire(private_store=tmp_path / "private", output=tmp_path / "public" / "receipt.json",
                  overlap_baseline=baseline(tmp_path), transport=transport, expected_revision="f" * 40)
    assert transport.calls == [h.API_URL]
