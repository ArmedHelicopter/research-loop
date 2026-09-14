import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort, RECOVERY
from research_loop.ontology import ContractError


SCHEMA={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
REQUEST=FrozenRecord.from_dict({"schema":"public-model-request-v1","task":{},"lock_digest":"a"*64,"objective":{},"slot":"m4_plan","instruction":"public","context":{},"module_context":{},"execution_feedback":[]})


def port(tmp_path, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    exe=tmp_path/"grok.exe"; exe.write_bytes(b"synthetic executable")
    home=tmp_path/"approved-home"; home.mkdir(); (home/"auth.json").write_text("{}",encoding="utf-8")
    return GrokHeadlessTrainModelPort(executable=exe,work_root=tmp_path/"ledger",private_home=home,
        private_profile=tmp_path/"profiles",public_cwd=tmp_path/"cwd",frozen_files={str(exe):__import__("hashlib").sha256(exe.read_bytes()).hexdigest()},
        max_calls=1,schemas={"m4_plan":SCHEMA},slot_output_caps={"m4_plan":2048},slot_input_byte_caps={"m4_plan":262144},
        observed_main_token_cap=131072,**kwargs)


def test_recovery_contract_is_explicit_and_defaulted(tmp_path):
    value=port(tmp_path)
    assert value.provider_kind == "grok-headless-public-train-v1"
    assert value.effort == "low" and value.account_read_recovery == RECOVERY
    assert value.ledger["config"]["timeout_seconds"] == 60 and value.ledger["config"]["max_retries"] == 0
    with pytest.raises(ContractError):
        port(tmp_path/"bad", account_read_recovery={"schema":"headless-account-read-recovery-v1","max_attempts":3})


def test_invalid_public_request_stops_before_native_context_creation(tmp_path):
    value=port(tmp_path)
    bad=FrozenRecord.from_dict({**REQUEST.data(),"slot":"foreign"})
    with pytest.raises(ContractError): value(bad)
    assert value.ledger["calls"] == []
    assert not list(value.calls_root.iterdir())
