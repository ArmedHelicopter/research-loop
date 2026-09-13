import json
import ssl
import urllib.error

import pytest

from evaluation.modular.canonical_lineage import normalize_reference
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.source_repository_supplement import Archive, repository_identity, supplement, validate_public
from research_loop.ontology import digest


class Fake:
    def iter_bytes(self, identity, phase, pin):
        if phase == "revision":
            value = [{"sha": "a" * 40, "PRIVATE_DYNAMIC_TASK": "PRIVATE_GOLD"}]
        else:
            value = {"license": {"spdx_id": "MIT"}, "content": "PRIVATE_CODE", "PRIVATE_DYNAMIC_TASK": "PRIVATE_GOLD"}
        yield json.dumps(value).encode()


def test_private_dynamic_fields_never_leave_archive(tmp_path):
    groups = {"fixture/repo": [digest(1), digest(2)]}
    archive = Archive(tmp_path / "private")
    result = supplement(groups, [digest(3)], digest(4), digest(5), archive, Fake())
    assert result["record_count"] == 3
    assert result["repositories"][0]["repository_sha256"] == normalize_reference("fixture/repo", "github_repository")[1]
    assert result["repositories"][0]["license_received"] is True
    assert "PRIVATE" not in json.dumps(result)
    assert result["repositories"][0]["snapshot_revision_relation"] == "unknown"
    assert result["repositories"][0]["upstream_data_terms"] == "unqualified"
    assert len(list(archive.root.glob("response-*.bin"))) == 2


def test_transport_failure_sealed_without_exception_text(tmp_path):
    class Broken:
        def iter_bytes(self, *args):
            yield b'{"PRIVATE_DYNAMIC_TASK":'
            raise urllib.error.URLError(ssl.SSLError("PRIVATE_GOLD"))
    archive = Archive(tmp_path / "private")
    result = supplement({"fixture/repo": [digest(1)]}, [], digest(2), digest(3), archive, Broken())
    assert result["failed_fetch_count"] == 1
    assert result["fetch_count"] == 1
    events = "".join(path.read_text() for path in archive.root.glob("event-*.json"))
    assert "PRIVATE" not in events
    assert '"tls":true' in events
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("identity", ["https://evil.invalid/a/b", "a/b?secret=yes", "../repo", "a/..", "a/b/c", "https://github.com/a/b#task"])
def test_repository_selection_cannot_expand_endpoints(identity):
    assert repository_identity(identity) is None


@pytest.mark.parametrize("identity", ["n/a", " N/A ", "na", "none", "null", "-"])
def test_missing_value_does_not_become_official_repository(identity):
    assert repository_identity(identity) is None


def test_exact_public_schema_and_duplicate_denominator_rejected(tmp_path):
    result = supplement({"fixture/repo": [digest(1)]}, [], digest(2), digest(3), Archive(tmp_path / "private"), Fake())
    malformed = dict(result, PRIVATE_DYNAMIC_TASK="PRIVATE_GOLD")
    with pytest.raises(CustodyError):
        validate_public(malformed)
    result["unmapped_tokens"] = [digest(1)]
    result["record_count"] = 2
    with pytest.raises(CustodyError):
        validate_public(result)


def test_no_pin_means_no_unpinned_license_fetch(tmp_path):
    class InvalidPin:
        def iter_bytes(self, identity, phase, pin):
            assert phase == "revision"
            yield b'[{"sha":"PRIVATE_GOLD"}]'
    result = supplement({"fixture/repo": [digest(1)]}, [], digest(2), digest(3), Archive(tmp_path / "private"), InvalidPin())
    assert result["fetch_count"] == result["failed_fetch_count"] == 1
    assert result["repositories"][0]["revision_received"] is False


def test_existing_archive_not_overwritten(tmp_path):
    Archive(tmp_path / "private")
    with pytest.raises(FileExistsError):
        Archive(tmp_path / "private")
