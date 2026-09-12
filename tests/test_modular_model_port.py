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
    return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"total_tokens":7}}\n', stderr="")


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
    assert instance(request()).data() == {"answer": "ok"}
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
        return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"total_tokens":1}}', stderr="")
    instance = CodexModelPort("codex", tmp_path / "port", max_calls=2, max_tokens=10,
                              schema_by_slot={"plan": SCHEMA}, process_runner=bad_output)
    with pytest.raises(ContractError, match="valid slot"):
        instance(request())
    with pytest.raises(ContractError, match="configuration"):
        CodexModelPort("codex", tmp_path / "port", model="other", max_calls=2, max_tokens=10,
                       schema_by_slot={"plan": SCHEMA}, process_runner=bad_output)
