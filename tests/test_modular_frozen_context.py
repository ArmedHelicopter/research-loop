"""Regression checks at the actual audit -> policy -> ledger -> provider seam.

All provider processes here are explicit fixtures. No test invokes a model.
"""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import (
    CodexModelPort, DISABLED_FEATURES, FrozenBaseContextPolicy,
    _base_context_bytes, audit_base_context, context_source_specs, shared_args,
)
from research_loop.ontology import ContractError


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}
RAW = json.dumps([{"type": "message", "id": "transport-id", "role": "developer",
                   "content": [{"type": "input_text", "text": "Audited common <skills_instructions> context"}],
                   "internal_chat_message_metadata_passthrough": {"create_time": 1}}])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request():
    return FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": {"identity": {"domain": "train"}},
        "lock_digest": "lock", "objective": {}, "slot": "plan", "instruction": "public instruction",
        "context": {}, "module_context": {}, "execution_feedback": []})


@pytest.fixture
def harness(tmp_path, monkeypatch):
    home = tmp_path / "user" / ".codex"
    home.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home.parent))
    monkeypatch.setenv("HOME", str(home.parent))
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("FAKE_SECRET", "never-archive-environment-values")
    config = home / "config.toml"
    config.write_text('model="base"\n[mcp_servers.fixture]\nenabled=true\n', encoding="utf-8")
    cli = tmp_path / "codex.exe"
    cli.write_bytes(b"fixture CLI, never executed")
    cwd = tmp_path / "empty"
    cwd.mkdir()
    probes, calls = [], []

    def probe(argv, **kwargs):
        probes.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=RAW, stderr="")

    candidate = audit_base_context(cli, cwd, tmp_path / "audit",
        config_overrides=('mcp_servers.fixture.enabled=false',), context_probe_runner=probe)
    # pytest itself rewrites this variable between fixture setup and test call.
    # The controller intentionally refuses any environment drift; hold this
    # test-runner variable constant within this explicit synthetic boundary.
    fixture_test_environment = os.environ.get("PYTEST_CURRENT_TEST", "")
    policy_data = json.loads(candidate.read_text(encoding="utf-8"))
    policy_data.update(status="REVIEWED", review={"reviewer": "test fixture", "reviewed_at": "2026-09-12T00:00:00Z",
        "rationale": "Synthetic source set for regression only", "source_completeness": "Fixture config and explicit default source inventory"})
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps(policy_data), encoding="utf-8")
    policy = FrozenBaseContextPolicy(reviewed, sha(reviewed))

    def paid(argv, **kwargs):
        calls.append((argv, kwargs))
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"fixture"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 1, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
            "output_tokens": 1, "reasoning_output_tokens": 0}}))

    def port(**overrides):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", fixture_test_environment)
        options = dict(max_calls=2, max_tokens=100, schema_by_slot={"plan": SCHEMA},
                       process_runner=paid, context_probe_runner=probe, frozen_base_context=policy)
        options.update(overrides)
        return CodexModelPort(cli, tmp_path / "port", **options)

    return SimpleNamespace(home=home, cli=cli, cwd=cwd, config=config, candidate=candidate,
        policy=policy, reviewed=reviewed, policy_data=policy_data, port=port,
        paid=paid, probe=probe, probes=probes, calls=calls, root=tmp_path)


def test_exact_shared_arguments_cwd_environment_and_frozen_slot_receipts(harness):
    h = harness
    instance = h.port()
    assert instance(request()).data() == {"answer": "fixture"}
    debug_argv, debug_kwargs = h.probes[-1]
    exec_argv, exec_kwargs = h.calls[-1]
    shared = shared_args("gpt-5.6-luna", "low", ('mcp_servers.fixture.enabled=false',))
    assert debug_argv[3:] == shared == exec_argv[2:2 + len(shared)]
    assert debug_kwargs["cwd"] == exec_kwargs["cwd"] == str(h.cwd)
    assert debug_kwargs["env"] == exec_kwargs["env"]
    assert list(h.cwd.iterdir()) == []
    assert "--ignore-user-config" not in exec_argv and "--ignore-rules" not in exec_argv
    assert all(["--disable", feature] == shared[shared.index(feature) - 1:shared.index(feature) + 1] for feature in DISABLED_FEATURES)
    ledger = json.loads((h.root / "port" / "ledger.json").read_text())
    assert ledger["config"]["context_policy"]["sha256"] == h.policy.sha256
    assert ledger["calls"][0]["argv"] == exec_argv
    assert ledger["calls"][0]["schema_hash"] == sha(Path(exec_argv[exec_argv.index("--output-schema") + 1]))
    assert h.port().ledger["tokens"] == 2
    assert "never-archive-environment-values" not in json.dumps(ledger)
    assert "never-archive-environment-values" not in h.candidate.read_text()


@pytest.mark.parametrize("drift", ["cli", "config", "new_rule", "cwd", "environment", "shared", "policy", "review_material", "slot_schema"])
def test_preflight_drift_never_starts_paid_runner(harness, drift):
    h = harness
    instance = h.port()
    if drift == "cli":
        h.cli.write_bytes(b"changed CLI")
    elif drift == "config":
        h.config.write_text('model="changed"')
    elif drift == "new_rule":
        (h.home / "rules").mkdir()
        (h.home / "rules" / "new.rules").write_text("new rule")
    elif drift == "cwd":
        (h.cwd / "unexpected.txt").write_text("unexpected")
    elif drift == "environment":
        instance.environment["UNREVIEWED"] = "change"
    elif drift == "shared":
        instance.shared.extend(("--enable", "shell_tool"))
    elif drift == "policy":
        h.reviewed.write_text(h.reviewed.read_text() + " ")
    elif drift == "review_material":
        Path(h.policy_data["audit_path"]).write_text("{}")
    elif drift == "slot_schema":
        instance.schemas["plan"]["properties"]["answer"]["type"] = "integer"
    with pytest.raises(ContractError):
        instance(request())
    assert h.calls == [] and instance.ledger["calls"] == []


@pytest.mark.parametrize("render", ["", "[]", "null", "not json", '[{"role":"developer","content":[]}]',
    '[{"role":"developer","content":[{"type":"input_text","text":""}]}]',
    '[{"role":"developer","content":[{"type":"image","text":"x"}]}]',
    RAW.replace("Audited common", "Changed common")])
def test_empty_malformed_or_changed_render_blocks_paid_runner(harness, render):
    h = harness
    instance = h.port(context_probe_runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=render, stderr=""))
    with pytest.raises(ContractError, match="context"):
        instance(request())
    assert h.calls == [] and instance.ledger["calls"] == []
    assert instance.ledger["context_probes"][-1]["status"] == "rejected"


def test_config_drift_during_render_is_rechecked_before_paid_runner(harness):
    h = harness
    def probe(*args, **kwargs):
        h.config.write_text('model="changed during render"')
        return SimpleNamespace(returncode=0, stdout=RAW, stderr="")
    instance = h.port(context_probe_runner=probe)
    with pytest.raises(ContractError, match="drifted"):
        instance(request())
    assert not h.calls and not instance.ledger["calls"]


def test_new_reviewed_policy_cannot_reopen_existing_ledger(harness):
    h = harness
    h.port()(request())
    h.policy_data["review"]["rationale"] = "different review, same rendered prompt"
    h.reviewed.write_text(json.dumps(h.policy_data))
    with pytest.raises(ContractError, match="configuration"):
        h.port(frozen_base_context=FrozenBaseContextPolicy(h.reviewed, sha(h.reviewed)))
    assert len(h.calls) == 1


def test_unqualified_and_boolean_only_policies_cannot_start(harness):
    h = harness
    with pytest.raises(ContractError, match="unqualified"):
        h.port(frozen_base_context=FrozenBaseContextPolicy(h.candidate, sha(h.candidate)))
    data = json.loads(h.candidate.read_text())
    data.update(status="REVIEWED", reviewed=True)
    h.reviewed.write_text(json.dumps(data))
    with pytest.raises(ContractError, match="provenance"):
        h.port(frozen_base_context=FrozenBaseContextPolicy(h.reviewed, sha(h.reviewed)))
    assert not h.calls


def test_explicit_mock_boundary_cannot_use_real_process(harness):
    with pytest.raises(ContractError, match="fixture runners"):
        CodexModelPort(harness.cli, harness.root / "mock", max_calls=1, max_tokens=1,
                       schema_by_slot={"plan": SCHEMA}, allow_mock_context=True)


def test_transport_metadata_only_is_ignored():
    other = RAW.replace("transport-id", "new-transport-id").replace('"create_time": 1', '"create_time": 2')
    assert _base_context_bytes(RAW.encode()) == _base_context_bytes(other.encode())


def test_label_ancestor_rejects_audit_without_reading_labels(harness):
    h = harness
    (h.root / "data" / "labels").mkdir(parents=True)
    before = len(h.probes)
    with pytest.raises(ContractError, match="label ancestor"):
        audit_base_context(h.cli, h.cwd, h.root / "blocked-audit", context_probe_runner=h.probe)
    assert len(h.probes) == before and not h.calls


def test_frozen_catalog_ignores_unused_cache_refresh_but_blocks_catalog_changes(harness):
    h = harness
    catalog = h.root / "frozen-models.json"
    catalog.write_text('{"models":[{"slug":"gpt-5.6-luna"}]}')
    overrides = ('mcp_servers.fixture.enabled=false', 'model_catalog_json=' + json.dumps(str(catalog)))
    candidate = audit_base_context(h.cli, h.cwd, h.root / "catalog-audit", config_overrides=overrides,
        source_specs=context_source_specs(h.home, h.cwd, model_catalog_path=catalog), context_probe_runner=h.probe)
    data = json.loads(candidate.read_text())
    data.update(status="REVIEWED", review=h.policy_data["review"])
    reviewed = h.root / "catalog-reviewed.json"
    reviewed.write_text(json.dumps(data))
    (h.home / "models_cache.json").write_text('{"fetched_at":"unrelated refresh"}')
    instance = CodexModelPort(h.cli, h.root / "catalog-port", max_calls=2, max_tokens=100,
        schema_by_slot={"plan": SCHEMA}, process_runner=h.paid, context_probe_runner=h.probe,
        frozen_base_context=FrozenBaseContextPolicy(reviewed, sha(reviewed)))
    assert instance(request()).data() == {"answer": "fixture"}
    catalog.write_text('{"models":[{"slug":"changed-model"}]}')
    with pytest.raises(ContractError, match="drifted"):
        instance(request())
    assert len(h.calls) == 1
