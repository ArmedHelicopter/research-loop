import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import CodexModelPort
from research_loop.ontology import ContractError


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}


def request(slot="plan"):
    return FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": {"identity": {"domain": "train"}}, "lock_digest": "lock", "objective": {}, "slot": slot, "instruction": "public instruction", "context": {}, "module_context": {}, "execution_feedback": []})


def runner(argv, **kwargs):
    assert "--ignore-user-config" in argv and "--ephemeral" in argv and "--ignore-rules" in argv
    assert "--disable" in argv and "shell_tool" in argv and "browser_use" in argv
    output = Path(argv[argv.index("-o") + 1])
    output.write_text(json.dumps({"answer": "bounded"}), encoding="utf-8")
    return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":5,"cached_input_tokens":2,"output_tokens":2}}\n', stderr="")


def port(tmp_path, **kwargs):
    return CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                          schema_by_slot={"plan": SCHEMA}, process_runner=runner, **kwargs)


def test_reserves_persists_and_returns_immutable_response(tmp_path):
    instance = port(tmp_path)
    response = instance(request())
    assert response.data() == {"answer": "bounded"}
    ledger = json.loads((tmp_path / "port" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"][0]["status"] == "succeeded"
    assert ledger["calls"][0]["request_hash"] == request().content_hash
    assert ledger["calls"][0]["output_hash"] == response.content_hash
    reopened = port(tmp_path)
    assert reopened.ledger["tokens"] == 7


def test_missing_usage_blocks_following_call_after_recorded_response(tmp_path):
    def without_usage(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ok"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=without_usage)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    with pytest.raises(ContractError, match="usage incomplete"):
        instance(request())


def test_timeout_is_unknown_and_never_retried(tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("codex", 1)
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=timeout)
    with pytest.raises(ContractError, match="unknown billing"):
        instance(request())
    ledger = json.loads((tmp_path / "port" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"][0]["status"] == "unknown"
    with pytest.raises(ContractError, match="usage incomplete"):
        instance(request())


def test_rejects_bad_slot_output_and_reopen_configuration_drift(tmp_path):
    def bad_output(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"unexpected":true}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":0}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=bad_output)
    with pytest.raises(ContractError, match="valid slot"):
        instance(request())
    with pytest.raises(ContractError, match="configuration"):
        CodexModelPort("codex", tmp_path / "port", model="other", max_calls=2, max_tokens=10,
                       schema_by_slot={"plan": SCHEMA}, process_runner=bad_output)


def test_execution_event_and_reserved_ledger_block_reopen(tmp_path):
    def tool_event(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n{"type":"item.completed","item":{"type":"command_execution"}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "tools", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=tool_event)
    with pytest.raises(ContractError, match="forbidden execution"):
        instance(request())
    ledger = json.loads((tmp_path / "tools" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"][0]["status"] == "failed" and ledger["calls"][0]["tool_events"]
    with pytest.raises(ContractError, match="incomplete call"):
        CodexModelPort("codex", tmp_path / "tools", max_calls=2, max_tokens=10,
                       schema_by_slot={"plan": SCHEMA}, process_runner=tool_event)


def test_rejects_duplicate_usage_and_records_over_budget(tmp_path):
    def duplicate_usage(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        event = '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        return SimpleNamespace(returncode=0, stdout=event + event, stderr="")
    instance = CodexModelPort("codex", tmp_path / "duplicate", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=duplicate_usage)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    def boolean_usage(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":1}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "boolean", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=boolean_usage)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    def over_budget(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":8,"output_tokens":3}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "budget", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=over_budget)
    with pytest.raises(ContractError, match="exceeded"):
        instance(request())
    ledger = json.loads((tmp_path / "budget" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["tokens"] == 11 and ledger["calls"][0]["status"] == "over_budget"
