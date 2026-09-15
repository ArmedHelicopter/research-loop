import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

import evaluation.modular.headless_evaluator_model_port as headless_port
from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import ProcessTree
from research_loop.ontology import ContractError, canonical


def _sha(raw): return hashlib.sha256(raw).hexdigest()


def port(tmp_path, *, mode="primary_v1", max_calls=1, max_tokens=1000):
    tmp_path.mkdir(parents=True, exist_ok=True)
    executable = tmp_path / "synthetic-headless.exe"; executable.write_bytes(b"synthetic native identity; never launched")
    home = tmp_path / "approved-home"; home.mkdir()
    auth = {"native": {"auth_mode": "oidc", "oidc_issuer": "https://auth.x.ai", "oidc_client_id": "b1a00492-073a-47ea-816f-4c329264a828", "key": "synthetic", "user_id": "synthetic-account", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}}
    (home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    return GrokHeadlessEvaluatorModelPort(executable=executable, work_root=tmp_path / "ledger", private_home=home,
        private_profile=tmp_path / "profiles", public_cwd=tmp_path / "contexts", frozen_files={str(executable.resolve()): _sha(executable.read_bytes())},
        evaluator_id="fixture", evaluator_version="v1", rubric_mode=mode, max_calls=max_calls, max_tokens=max_tokens)


def _install_native(monkeypatch, value):
    import research_loop.modular.grok_headless_transport as transport
    peer = Path(__file__).parent / "fixtures" / "headless_train_peer.py"; calls, gets = [], []
    monkeypatch.setattr(transport, "EXECUTABLE_SHA256", _sha(Path(value.executable).read_bytes()))
    def spawn(command, cwd, env, stderr):
        assert env["GROK_DISABLE_API_KEY_AUTH"] == "1" and not {"XAI_API_KEY", "GROK_API_KEY"} & set(env)
        assert not any(Path(cwd).iterdir())
        if "inspect" in command: args = ["inspect"]
        else:
            prompt_path = Path(command[command.index("--prompt-file") + 1]); prompt = prompt_path.read_text(encoding="utf-8")
            assert prompt.startswith("Return only JSON conforming to the supplied schema.\n") and "\nTASK=" in prompt and "\nREFERENCE=" in prompt and "\nANONYMOUS_CANDIDATE=" in prompt
            schema = json.loads(command[command.index("--json-schema") + 1])
            answer = {"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic"} if "cvars" in schema["properties"] else {"context": 1, "variable_f1": 1, "relation": 1, "reason": "synthetic"}
            answer_path = prompt_path.parent.parent / "synthetic-peer-answer.json"; answer_path.write_text(json.dumps(answer), encoding="utf-8")
            calls.append(prompt); args = [command[command.index("--session-id") + 1], str(answer_path)]
        return ProcessTree([sys.executable, str(peer), *args], cwd=cwd, env=env, stderr=stderr)
    class Response:
        status = 200
        def __init__(self, request): self.url = request.full_url; gets.append(self.url)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return self.url
        def read(self, maximum):
            now = datetime.now(timezone.utc)
            if self.url.endswith("/billing?format=credits"):
                body = {"config": {"isUnifiedBillingUser": True, "onDemandCap": {}, "onDemandUsed": {}, "prepaidBalance": {}, "on_demand_enabled": False, "creditUsagePercent": 2, "currentPeriod": {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1)).isoformat()}}}
            elif self.url.endswith("/auto-topup-rule"): body = {}
            else: body = {"userId": "synthetic-account", "hasGrokCodeAccess": True, "userBlockedReason": None, "teamBlockedReasons": []}
            return json.dumps(body).encode("utf-8")
    class Opener:
        def open(self, request, timeout): return Response(request)
    monkeypatch.setattr(transport, "ProcessTree", spawn)
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: Opener())
    return calls, gets


class Resolver:
    def __call__(self, handle, benchmark):
        identity = handle.removeprefix("synthetic:")
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark, "task_handle_digest": _sha(handle.encode()), "identity_digest": identity, "task_context": {"question": "synthetic"}, "references": [{"reference": "X relates to Y"}]})


def endpoint(value): return FrozenBenchmarkRubricEndpoint(resolver=Resolver(), evaluator=value, evaluator_id="fixture", evaluator_version="v1")


def request(benchmark="blade"):
    identity = "a" * 64; candidate = {"analysis": "synthetic candidate"}
    return FrozenRecord.from_dict({"schema": "adapted-rubric-evaluation-request-v1", "panel_digest": "p" * 64, "scorer_config_digest": "s" * 64, "benchmark": benchmark, "task_handle": "synthetic:" + identity, "identity_digest": identity, "candidate": candidate, "candidate_digest": FrozenRecord.from_dict(candidate).content_hash})


def test_private_evaluator_identity_mismatch_stops_before_native(tmp_path):
    value = port(tmp_path)
    body = {"schema": "frozen-independent-evaluator-call-v1", "evaluator_id": "foreign", "evaluator_version": "v1", "benchmark": "blade", "prompt": "foreign", "output_schema": {}, "prompt_digest": "a" * 64, "schema_digest": "a" * 64, "reference_digest": "a" * 64, "rubric_digest": "a" * 64}
    with pytest.raises(ContractError): value(FrozenRecord.from_dict(body))
    assert value.ledger["calls"] == []


def test_endpoint_port_native_and_raw_reader_positive(tmp_path, monkeypatch):
    value = port(tmp_path); calls, gets = _install_native(monkeypatch, value)
    result = endpoint(value)(request()).data()
    assert result["dimensions"] == {"cvars": 1.0, "transform": 1.0, "model": 1.0}
    assert len(calls) == 1 and len(gets) == 6
    row = value.ledger["calls"][0]
    assert row["known_headless_main_usage"]["total_tokens"] == 10 and row["headless_binding"]["accepted"] is True
    headless_port.replay_headless_evaluator_ledger(value)


def test_postflight_failure_retains_known_usage_and_never_consumes_rejected_raw_response(tmp_path, monkeypatch):
    value = port(tmp_path, max_calls=2); calls, _ = _install_native(monkeypatch, value)
    import research_loop.modular.grok_headless_transport as transport
    original = transport._account_recovered; observed = []
    def fail_after(*args, **kwargs):
        observed.append(1)
        if len(observed) == 2: raise ContractError("synthetic postflight failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(transport, "_account_recovered", fail_after)
    with pytest.raises(ContractError): endpoint(value)(request())
    row = value.ledger["calls"][0]
    assert len(calls) == 1 and row["status"] == "unknown_or_failed" and value.ledger["known_main_tokens"] == 10 and value.ledger["usage_incomplete"] is True
    assert "response_sha256" not in row and (value.calls_root / "0001-blade" / "native" / "response.private.json").exists()
    with pytest.raises(ContractError): endpoint(value)(request())
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["identity", "source", "executable", "config", "raw"])
def test_tampering_stops_before_a_second_native_call(tmp_path, monkeypatch, change):
    value = port(tmp_path, max_calls=2); calls, _ = _install_native(monkeypatch, value); endpoint(value)(request())
    row = value.ledger["calls"][0]
    if change == "identity": value.evaluator_id = "foreign"
    elif change == "source": monkeypatch.setattr(headless_port, "_source_pins", lambda mode: {"source": "0" * 64})
    elif change == "executable": Path(value.executable).write_bytes(b"tampered executable")
    elif change == "config": (value.calls_root / "0001-blade" / "native-home" / "config.toml").write_text("tampered", encoding="utf-8")
    else: (value.calls_root / "0001-blade" / "native" / "stdout.private.jsonl").write_bytes(b"{}\n")
    with pytest.raises(ContractError): endpoint(value)(request())
    assert len(calls) == 1
    if change in {"config", "raw"}: assert value.ledger["usage_incomplete"] is True
    else: assert value.ledger["calls"][0] is row


def test_primary_and_lineage_modes_have_distinct_frozen_schemas_and_templates(tmp_path):
    primary = port(tmp_path / "primary", mode="primary_v1"); lineage = port(tmp_path / "lineage", mode="lineage_v1")
    assert primary.rubric_digest != lineage.rubric_digest
    assert "lineage_endpoints" not in primary.schemas["blade"]["properties"] and "lineage_endpoints" in lineage.schemas["blade"]["properties"]
    prompt = FrozenBenchmarkRubricEndpoint._prompt("blade", FrozenBenchmarkRubricEndpoint._BLADE_RUBRIC, {}, {}, {})
    schema = FrozenBenchmarkRubricEndpoint._output_schema("blade")
    private = FrozenRecord.from_dict({"schema": "frozen-independent-evaluator-call-v1", "evaluator_id": "fixture", "evaluator_version": "v1", "benchmark": "blade", "prompt": prompt, "output_schema": schema, "prompt_digest": _sha(prompt.encode()), "schema_digest": _sha(canonical(schema).encode()), "reference_digest": "a" * 64, "rubric_digest": FrozenBenchmarkRubricEndpoint.rubric_digest()})
    with pytest.raises(ContractError): lineage(private)
    assert lineage.ledger["calls"] == []
