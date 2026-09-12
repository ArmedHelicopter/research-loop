import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.model_port import CodexModelPort, inspect_terminal_call
from research_loop.ontology import ContractError


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}


def request(slot="plan"):
    return FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": {"identity": {"domain": "train"}}, "lock_digest": "lock", "objective": {}, "slot": slot, "instruction": "public instruction", "context": {}, "module_context": {}, "execution_feedback": []})


def runner(argv, **kwargs):
    assert "--ignore-user-config" not in argv and "--ephemeral" in argv and "--ignore-rules" not in argv
    assert "--disable" in argv and "shell_tool" in argv and "browser_use" in argv
    output = Path(argv[argv.index("-o") + 1])
    output.write_text(json.dumps({"answer": "bounded"}), encoding="utf-8")
    return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":5,"cached_input_tokens":2,"cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":1}}\n', stderr="")


def probe(argv, **kwargs):
    assert argv[1:3] == ["debug", "prompt-input"]
    return SimpleNamespace(returncode=0, stdout='[{"role":"developer","content":[{"type":"input_text","text":"base"}]}]', stderr="")


def port(tmp_path, **kwargs):
    return CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                          schema_by_slot={"plan": SCHEMA}, process_runner=runner, context_probe_runner=probe, allow_mock_context=True, **kwargs)


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
                              schema_by_slot={"plan": SCHEMA}, process_runner=without_usage, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    with pytest.raises(ContractError, match="usage incomplete"):
        instance(request())


def test_timeout_is_unknown_and_never_retried(tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("codex", 1)
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=timeout, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="unknown billing"):
        instance(request())
    ledger = json.loads((tmp_path / "port" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"][0]["status"] == "unknown"
    with pytest.raises(ContractError, match="usage incomplete"):
        instance(request())


def test_rejects_bad_slot_output_and_reopen_configuration_drift(tmp_path):
    def bad_output(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"unexpected":true}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":0,"reasoning_output_tokens":0}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=bad_output, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="valid slot"):
        instance(request())
    with pytest.raises(ContractError, match="configuration"):
        CodexModelPort("codex", tmp_path / "port", model="other", max_calls=2, max_tokens=10,
                       schema_by_slot={"plan": SCHEMA}, process_runner=bad_output, context_probe_runner=probe, allow_mock_context=True)


def test_execution_event_and_reserved_ledger_block_reopen(tmp_path):
    def tool_event(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}\n{"type":"item.completed","item":{"type":"command_execution"}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "tools", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=tool_event, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="forbidden execution"):
        instance(request())
    ledger = json.loads((tmp_path / "tools" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"][0]["status"] == "failed" and ledger["calls"][0]["tool_events"]
    with pytest.raises(ContractError, match="incomplete call"):
        CodexModelPort("codex", tmp_path / "tools", max_calls=2, max_tokens=10,
                       schema_by_slot={"plan": SCHEMA}, process_runner=tool_event, context_probe_runner=probe, allow_mock_context=True)


def test_rejects_duplicate_usage_and_records_over_budget(tmp_path):
    def duplicate_usage(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        event = '{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}\n'
        return SimpleNamespace(returncode=0, stdout=event + event, stderr="")
    instance = CodexModelPort("codex", tmp_path / "duplicate", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=duplicate_usage, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    def boolean_usage(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":true,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "boolean", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=boolean_usage, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="missing usage"):
        instance(request())
    def over_budget(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"ignored"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":8,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":3,"reasoning_output_tokens":0}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "budget", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=over_budget, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="exceeded"):
        instance(request())
    ledger = json.loads((tmp_path / "budget" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["tokens"] == 11 and ledger["calls"][0]["status"] == "over_budget"


def test_read_only_terminal_inspection_recovers_response_but_marks_skill_context_fault(tmp_path):
    def skill_fault(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text('{"answer":"already-paid"}', encoding="utf-8")
        event = '{"type":"turn.completed","usage":{"input_tokens":3,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":1}}\n'
        error = '{"type":"item.completed","item":{"type":"error","message":"Skill descriptions were shortened"}}'
        return SimpleNamespace(returncode=0, stdout=event + error, stderr="")
    root = tmp_path / "terminal"
    instance = CodexModelPort("codex", root, max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=skill_fault, context_probe_runner=probe, allow_mock_context=True)
    with pytest.raises(ContractError, match="forbidden execution"):
        instance(request())
    before = (root / "ledger.json").read_bytes()
    recovered = inspect_terminal_call(root, 1)
    assert recovered.response.data() == {"answer": "already-paid"}
    assert recovered.receipt.data()["usage"]["total_tokens"] == 5
    assert recovered.receipt.data()["context_faults"] == ["skill_context_detected"]
    assert recovered.receipt.data()["reconciled"] is False
    assert (root / "ledger.json").read_bytes() == before


def test_unqualified_default_refuses_before_paid_process(tmp_path):
    invoked = []
    def forbidden_probe(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout='[{"role":"developer","content":[{"type":"input_text","text":"<skills_instructions>"}]}]', stderr="")
    def paid(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("paid runner must not start")
    instance = CodexModelPort("codex", tmp_path / "blocked", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=paid, context_probe_runner=forbidden_probe)
    with pytest.raises(ContractError, match="unqualified"):
        instance(request())
    assert not invoked
    ledger = json.loads((tmp_path / "blocked" / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["calls"] == [] and ledger["context_probes"] == []
