import hashlib
import json
from pathlib import Path
import sys

import pytest

import research_loop.modular.grok_headless_transport as transport
from research_loop.modular.grok_acp_transport import ProcessTree, diagnostic_config
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

PEER = Path(__file__).parent / "fixtures" / "grok_headless_peer.py"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean", "enum": [True]}},
          "required": ["ok"], "additionalProperties": False}


def account(time="2026-09-14T00:00:00+00:00"):
    return {"issuer": "https://auth.x.ai", "client_id": "official-native-client", "endpoint": "/user?include=subscription",
            "redirected": False, "api_key_auth": False, "account_id": "synthetic-account", "code_access": True,
            "unified_pool": True, "remaining_percentage": 99, "onDemandCap": 0, "onDemandUsed": 0,
            "prepaidBalance": 0, "auto_topup": False, "observed_at": time}


def prepared(tmp_path, monkeypatch):
    root = tmp_path / "slot"; home = root / "home"; profile = root / "profile"; native = root / "native"
    for path in (home, profile, native): path.mkdir(parents=True)
    (home / "auth.json").write_text('{"opaque":true}')
    (home / "config.toml").write_bytes(diagnostic_config(8192).encode())
    (native / "account-preflight.private.json").write_text(json.dumps(account()))
    (native / "account-postflight.private.json").write_text(json.dumps(account("2026-09-14T00:01:00+00:00")))
    exe = root / "grok.exe"; exe.write_bytes(b"synthetic pinned executable")
    monkeypatch.setattr(transport, "EXECUTABLE_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest())
    seen = []
    def spawn(command, cwd, env, stderr):
        seen.append((command, cwd, env))
        session = command[command.index("--session-id") + 1]
        return ProcessTree([sys.executable, str(PEER), session], cwd=cwd, env=env, stderr=stderr)
    monkeypatch.setattr(transport, "ProcessTree", spawn)
    source = root / "source.py"; source.write_text("source")
    descriptor = root / "request.json"; descriptor.write_bytes(json.dumps({"prompt": '{"question":"synthetic"}', "output_schema": SCHEMA}, separators=(",", ":")).encode())
    return root, dict(executable=exe, cwd=root / "cwd", private_home=home, private_profile=profile,
        private_dir=native, reservation=root / "native-reservation.json",
        frozen_files={str(source): hashlib.sha256(source.read_bytes()).hexdigest()}, prompt='{"question":"synthetic"}',
        schema=SCHEMA, main_output_cap=8192, observed_main_token_cap=262144, input_byte_cap=131072), seen, descriptor


def test_producer_reader_seam_and_safe_unknown_totals(tmp_path, monkeypatch):
    root, kwargs, seen, descriptor = prepared(tmp_path, monkeypatch); kwargs["cwd"].mkdir()
    result = transport.run_headless_diagnostic(**kwargs)
    assert result.receipt.data()["accepted"] and result.response.data() == {"ok": True}
    assert len(seen) == 1 and "XAI_API_KEY" not in seen[0][2]
    entry = {"opportunity_id": "o1", "prompt_sha256": result.receipt.data()["prompt_sha256"],
             "schema_digest": result.receipt.data()["schema_digest"], "input_bytes": len(kwargs["prompt"].encode()),
             "private_request": {"path": str(descriptor), "sha256": hashlib.sha256(descriptor.read_bytes()).hexdigest()}}
    summary = transport.verify_headless_request_binding(result, entry, root,
        {"main_output_cap": 8192, "observed_main_token_cap": 262144, "max_input_bytes": 131072, "timeout_seconds": 240},
        kwargs["frozen_files"]).data()
    assert summary["accepted"] and summary["usage"]["main"]["total_tokens"] == 10
    assert summary["usage"]["initial_title"] is None and summary["identity"]["request_id"] == "synthetic-request"


@pytest.mark.parametrize("kind", ["stream", "source", "account"])
def test_reader_rejects_tampering(tmp_path, monkeypatch, kind):
    root, kwargs, _, descriptor = prepared(tmp_path, monkeypatch); kwargs["cwd"].mkdir(); result = transport.run_headless_diagnostic(**kwargs)
    if kind == "stream": (root / "native" / "stdout.private.jsonl").write_bytes(b"bad")
    elif kind == "source": Path(next(iter(kwargs["frozen_files"]))).write_text("changed")
    else: (root / "native" / "account-postflight.private.json").write_text(json.dumps(account("not-a-time")))
    entry = {"opportunity_id": "o1", "prompt_sha256": result.receipt.data()["prompt_sha256"], "schema_digest": result.receipt.data()["schema_digest"], "input_bytes": len(kwargs["prompt"].encode()), "private_request":{"path":str(descriptor),"sha256":hashlib.sha256(descriptor.read_bytes()).hexdigest()}}
    with pytest.raises(ContractError):
        transport.verify_headless_request_binding(result, entry, root, {"main_output_cap":8192,"observed_main_token_cap":262144,"max_input_bytes":131072,"timeout_seconds":240}, kwargs["frozen_files"])


@pytest.mark.parametrize("field,value", [("remaining_percentage", 0), ("onDemandCap", 1), ("redirected", True)])
def test_account_denial_happens_before_dispatch(tmp_path, monkeypatch, field, value):
    root, kwargs, seen, _ = prepared(tmp_path, monkeypatch); kwargs["cwd"].mkdir(); row = account(); row[field] = value
    (root / "native" / "account-preflight.private.json").write_text(json.dumps(row))
    with pytest.raises(ContractError): transport.run_headless_diagnostic(**kwargs)
    assert not seen


def test_source_and_config_denials_happen_before_dispatch(tmp_path, monkeypatch):
    root, kwargs, seen, _ = prepared(tmp_path, monkeypatch); kwargs["cwd"].mkdir()
    Path(next(iter(kwargs["frozen_files"]))).write_text("changed")
    with pytest.raises(ContractError): transport.run_headless_diagnostic(**kwargs)
    assert not seen
    root, kwargs, seen, _ = prepared(tmp_path / "config", monkeypatch); kwargs["cwd"].mkdir()
    (root / "home" / "config.toml").write_text("wrong")
    with pytest.raises(ContractError): transport.run_headless_diagnostic(**kwargs)
    assert not seen
