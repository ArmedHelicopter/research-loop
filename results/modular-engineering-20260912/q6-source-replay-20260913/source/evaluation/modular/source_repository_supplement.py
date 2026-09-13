"""Bounded custody-only repository metadata supplement; no payload projection.

Only the fixed SAB github_name field selects official repository endpoints.
Current repository licenses are metadata evidence, never upstream data licenses.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from evaluation.modular.canonical_lineage import normalize_reference, record_token
from evaluation.modular.extended_ingestion import _inside, _receipt
from evaluation.modular.fresh_airs_custodian import CustodyError, _check, _write_new
from evaluation.modular.fresh_airs_hf_custodian import safe_error
from research_loop.modular.source_ingestion import SOURCE_SNAPSHOTS
from research_loop.ontology import digest

SCHEMA = "source-repository-supplement-v1"
MAX_BYTES = 2 * 1024 * 1024
PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
PIN = re.compile(r"[0-9a-f]{40}\Z")
ZERO = "0" * 64


def repository_identity(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    value = value.strip()
    if value.lower() in {"", "n/a", "na", "none", "null", "-"}:
        return None
    # This acquisition channel must not silently broaden the frozen canonical
    # schema (for example by accepting a bare owner/repo/ trailing slash).
    if normalize_reference(value, "github_repository") is None:
        return None
    if "://" not in value:
        value = "https://github.com/" + value
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.query or parsed.fragment):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or not all(PART.fullmatch(x) for x in parts):
        return None
    parts[1] = parts[1].removesuffix(".git")
    if not parts[1] or any(x in {".", ".."} for x in parts):
        return None
    return "/".join(parts).lower()


def inventory(private_root):
    spec = SOURCE_SNAPSHOTS["scienceagentbench"]
    snapshot = Path(private_root) / "snapshots/scienceagentbench" / spec.revision
    receipt = _receipt(snapshot, "scienceagentbench")
    path = _inside(snapshot, "ScienceAgentBench.csv")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 102:
        raise CustodyError()
    grouped, missing = {}, []
    for index, row in enumerate(rows):
        token = record_token("scienceagentbench", spec.revision, index)
        identity = repository_identity(row.get("github_name"))
        if identity is None:
            missing.append(token)
        else:
            grouped.setdefault(identity, []).append(token)
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise CustodyError()
    if len(grouped) > 40:
        raise CustodyError()
    return grouped, missing, digest(receipt), before


class Transport:
    def __init__(self, identities):
        self.identities = frozenset(identities)

    def iter_bytes(self, identity, phase, pin):
        if identity not in self.identities:
            raise CustodyError()
        if phase == "revision" and pin is None:
            suffix = "/commits?per_page=1"
        elif phase == "license" and isinstance(pin, str) and PIN.fullmatch(pin):
            suffix = "/license?ref=" + pin
        else:
            raise CustodyError()
        request = urllib.request.Request("https://api.github.com/repos/" + identity + suffix,
                                         headers={"User-Agent": "research-loop-custodian"})
        with urllib.request.urlopen(request, timeout=15) as response:
            while block := response.read(65536):
                yield block


class Archive:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.count, self.previous = 0, ZERO

    def event(self, kind, **fields):
        self.count += 1
        path = self.root / f"event-{self.count:04d}.json"
        _write_new(path, {"kind": kind, "previous_sha256": self.previous, **fields})
        self.previous = hashlib.sha256(path.read_bytes()).hexdigest()

    def fetch(self, identity, phase, pin, transport):
        token = normalize_reference(identity, "github_repository")[1]
        self.event("fetch_started", repository_sha256=token, phase=phase,
                   pin_sha256=digest(pin) if pin else None)
        path = self.root / f"response-{self.count:04d}.bin"
        sha, size = hashlib.sha256(), 0
        try:
            with path.open("xb") as stream:
                for block in transport.iter_bytes(identity, phase, pin):
                    if type(block) is not bytes or not block or size + len(block) > MAX_BYTES:
                        raise CustodyError()
                    stream.write(block)
                    sha.update(block)
                    size += len(block)
                stream.flush()
                os.fsync(stream.fileno())
            raw = json.loads(path.read_bytes())
            self.event("fetch_received", repository_sha256=token, phase=phase,
                       response_sha256=sha.hexdigest(), bytes=size)
            return raw, sha.hexdigest(), None
        except Exception as error:
            failure = safe_error(error)
            self.event("fetch_failed", repository_sha256=token, phase=phase,
                       response_sha256=sha.hexdigest(), bytes=size, failure=failure)
            return None, sha.hexdigest(), failure


def validate_public(value):
    entry = {"repository_sha256": "sha", "member_tokens": ["sha"], "member_count": "count",
             "revision_response_sha256": "sha", "license_response_sha256": "sha",
             "current_revision_sha256": "sha", "license_declaration_sha256": "sha",
             "revision_received": False, "license_received": False,
             "snapshot_revision_relation": "unknown", "upstream_data_terms": "unqualified"}
    copy = json.loads(json.dumps(value))
    for row in copy.get("repositories", []):
        for key in ("revision_received", "license_received"):
            if type(row.get(key)) is not bool:
                raise CustodyError()
            row[key] = False
    _check(copy, {"schema": SCHEMA, "source": "scienceagentbench", "input_receipt_sha256": "sha",
                  "input_csv_sha256": "sha", "record_count": "count", "repositories": [entry],
                  "unmapped_tokens": ["sha"], "fetch_count": "count", "failed_fetch_count": "count",
                  "event_chain_sha256": "sha", "payload_exported": False,
                  "split_created": False, "validation_lease_issued": False,
                  "pretraining_exposure": "not_assessed_not_a_process_cleanliness_requirement"})
    tokens = [x for row in value["repositories"] for x in row["member_tokens"]] + value["unmapped_tokens"]
    if len(tokens) != value["record_count"] or len(tokens) != len(set(tokens)):
        raise CustodyError()
    if any(row["member_count"] != len(row["member_tokens"]) for row in value["repositories"]):
        raise CustodyError()
    return value


def supplement(grouped, missing, receipt_sha, csv_sha, archive, transport):
    entries, failures, fetches = [], 0, 0
    for identity, members in sorted(grouped.items()):
        raw, response_sha, error = archive.fetch(identity, "revision", None, transport)
        fetches += 1
        pin = raw[0].get("sha") if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict) else None
        valid = isinstance(pin, str) and PIN.fullmatch(pin) is not None
        license_sha, declaration_sha, received = ZERO, ZERO, False
        if not valid:
            failures += 1
            archive.event("revision_unresolved", repository_sha256=normalize_reference(identity, "github_repository")[1])
        else:
            raw, license_sha, error = archive.fetch(identity, "license", pin, transport)
            fetches += 1
            metadata = raw.get("license") if isinstance(raw, dict) else None
            spdx = metadata.get("spdx_id") if isinstance(metadata, dict) else None
            received = isinstance(spdx, str) and spdx not in {"", "NOASSERTION"}
            if received:
                declaration_sha = digest(spdx)
            else:
                failures += 1
        entries.append({"repository_sha256": normalize_reference(identity, "github_repository")[1],
                        "member_tokens": sorted(members), "member_count": len(members),
                        "revision_response_sha256": response_sha, "license_response_sha256": license_sha,
                        "current_revision_sha256": digest(pin) if valid else ZERO,
                        "license_declaration_sha256": declaration_sha,
                        "revision_received": valid, "license_received": received,
                        "snapshot_revision_relation": "unknown", "upstream_data_terms": "unqualified"})
    result = {"schema": SCHEMA, "source": "scienceagentbench", "input_receipt_sha256": receipt_sha,
              "input_csv_sha256": csv_sha, "record_count": sum(map(len, grouped.values())) + len(missing),
              "repositories": entries, "unmapped_tokens": sorted(missing), "fetch_count": fetches,
              "failed_fetch_count": failures, "event_chain_sha256": archive.previous,
              "payload_exported": False, "split_created": False, "validation_lease_issued": False,
              "pretraining_exposure": "not_assessed_not_a_process_cleanliness_requirement"}
    return validate_public(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--public-receipt", required=True)
    args = parser.parse_args()
    # No untrusted parser, transport, or exception output crosses the boundary.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            grouped, missing, receipt_sha, csv_sha = inventory(args.private_root)
            archive = Archive(args.archive)
            result = supplement(grouped, missing, receipt_sha, csv_sha, archive, Transport(grouped))
            _write_new(Path(args.public_receipt), result)
        print(json.dumps({"status": "recorded", "records": result["record_count"],
                          "repositories": len(result["repositories"]), "fetches": result["fetch_count"],
                          "failed_fetches": result["failed_fetch_count"]}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": safe_error(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
