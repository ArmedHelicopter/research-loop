import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort, RECOVERY
from research_loop.ontology import ContractError


SCHEMA={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
REQUEST=FrozenRecord.from_dict({"schema":"public-model-request-v1","task":{},"lock_digest":"a"*64,"objective":{},"slot":"m4_plan","instruction":"public","context":{},"module_context":{},"execution_feedback":[]})


def port(tmp_path, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    exe=tmp_path/"grok.exe"; exe.write_bytes(b"synthetic executable")
    home=tmp_path/"approved-home"; home.mkdir(); (home/"auth.json").write_text(json.dumps({"native":{
        "auth_mode":"oidc","oidc_issuer":"https://auth.x.ai","oidc_client_id":"b1a00492-073a-47ea-816f-4c329264a828",
        "key":"synthetic-private-token","user_id":"synthetic-account","expires_at":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}}),encoding="utf-8")
    max_calls=kwargs.pop("max_calls", 1)
    return GrokHeadlessTrainModelPort(executable=exe,work_root=tmp_path/"ledger",private_home=home,
        private_profile=tmp_path/"profiles",public_cwd=tmp_path/"cwd",frozen_files={str(exe):__import__("hashlib").sha256(exe.read_bytes()).hexdigest()},
        max_calls=max_calls,schemas={"m4_plan":SCHEMA},slot_output_caps={"m4_plan":2048},slot_input_byte_caps={"m4_plan":262144},
        observed_main_token_cap=131072,**kwargs)


def synthetic_native(tmp_path, monkeypatch, value):
    """A local CLI peer plus in-memory synthetic HTTP account observations."""
    from tests.helpers.headless_authoring_fixture import install_synthetic_native
    _, gets = install_synthetic_native(monkeypatch, {"native_deployment":{"slots":{},"executable":value.executable}})
    import research_loop.modular.grok_headless_transport as transport
    from research_loop.modular.grok_acp_transport import ProcessTree
    peer=tmp_path/"headless-peer.py"
    peer.write_text('''import json,sys
def value(s):
 t=s.get("type")
 if t=="object": return {k:value(v) for k,v in s.get("properties",{}).items() if k in s.get("required",[])}
 if t=="boolean": return True
 if t=="integer": return 0
 if t=="number": return 0.0
 if t=="array": return []
 return "synthetic"
if sys.argv[1]=="inspect":
 print(json.dumps({**{k:[] for k in ("skills","hooks","plugins","mcpServers","projectInstructions")},"loginPolicy":{"apiKeyAuthDisabled":True},"workflowGuide":None,"memoryDigest":None}))
else:
 session,prompt,schema=sys.argv[1:4]; answer=value(json.loads(schema)); usage={"input_tokens":8,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":2,"reasoning_tokens":0}
 for row in ([{"type":"available_commands","tools":[],"commands":[]}] * 3 + [{"type":"text","data":json.dumps(answer)},{"type":"usage","usage":usage,"signature":"synthetic"},{"type":"end","stopReason":"end_turn","sessionId":session,"requestId":"synthetic-"+session,"usage":usage|{"total_tokens":10},"num_turns":1,"modelUsage":{"grok-4.6":{"inputTokens":8,"outputTokens":2,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"modelCalls":1}},"structuredOutput":answer}]): print(json.dumps(row),flush=True)
''',encoding="utf-8")
    calls=[]
    def spawn(command,cwd,env,stderr):
        assert env["GROK_DISABLE_API_KEY_AUTH"] == "1"
        if "inspect" in command: args=["inspect"]
        else:
            calls.append(command)
            args=[command[command.index("--session-id")+1],command[command.index("--prompt-file")+1],command[command.index("--json-schema")+1]]
        return ProcessTree([sys.executable,str(peer),*args],cwd=cwd,env=env,stderr=stderr)
    monkeypatch.setattr(transport,"ProcessTree",spawn)
    return calls,gets


def test_recovery_contract_is_explicit_and_defaulted(tmp_path):
    value=port(tmp_path)
    assert value.provider_kind == "grok-headless-public-train-v1"
    assert value.effort == "low" and value.account_read_recovery == RECOVERY
    assert value.ledger["config"]["timeout_seconds"] == 60 and value.ledger["config"]["max_retries"] == 0
    with pytest.raises(ContractError):
        port(tmp_path/"bad", account_read_recovery={"schema":"headless-account-read-recovery-v1","max_attempts":3})


def test_supplied_executable_pin_is_an_input_not_overwritten(tmp_path):
    exe=tmp_path/"grok.exe"; exe.write_bytes(b"synthetic executable")
    home=tmp_path/"home"; home.mkdir(); (home/"auth.json").write_text("{}",encoding="utf-8")
    with pytest.raises(ContractError):
        GrokHeadlessTrainModelPort(executable=exe,work_root=tmp_path/"ledger",private_home=home,private_profile=tmp_path/"profile",public_cwd=tmp_path/"cwd",frozen_files={str(exe):"0"*64},max_calls=1,schemas={"m4_plan":SCHEMA},slot_output_caps={"m4_plan":2048},slot_input_byte_caps={"m4_plan":262144},observed_main_token_cap=131072)


def test_supplied_generated_source_pin_is_not_overwritten(tmp_path):
    import research_loop.modular.grok_headless_train_solver as solver
    exe=tmp_path/"grok.exe"; exe.write_bytes(b"synthetic executable")
    home=tmp_path/"home"; home.mkdir(); (home/"auth.json").write_text("{}",encoding="utf-8")
    with pytest.raises(ContractError):
        GrokHeadlessTrainModelPort(executable=exe,work_root=tmp_path/"ledger",private_home=home,private_profile=tmp_path/"profile",public_cwd=tmp_path/"cwd",frozen_files={str(exe):hashlib.sha256(exe.read_bytes()).hexdigest(),str(Path(solver.__file__).resolve()):"0"*64},max_calls=1,schemas={"m4_plan":SCHEMA},slot_output_caps={"m4_plan":2048},slot_input_byte_caps={"m4_plan":262144},observed_main_token_cap=131072)


def test_invalid_public_request_stops_before_native_context_creation(tmp_path):
    value=port(tmp_path)
    bad=FrozenRecord.from_dict({**REQUEST.data(),"slot":"foreign"})
    with pytest.raises(ContractError): value(bad)
    assert value.ledger["calls"] == []
    assert not list(value.calls_root.iterdir())


def test_synthetic_headless_producer_port_and_independent_replay(tmp_path, monkeypatch):
    """Real local peer plus synthetic account reads, never a provider/network call."""
    value=port(tmp_path)
    calls, gets=synthetic_native(tmp_path,monkeypatch,value)
    response=value(REQUEST)
    assert response.data()=={"ok":True} and len(calls)==1 and len(gets)==6
    row=value.ledger["calls"][0]
    assert row["status"]=="succeeded" and row["known_headless_main_usage"]["total_tokens"]==10
    from research_loop.modular.grok_headless_train_solver import _replay_headless_native_call, replay_headless_train_ledger
    assert _replay_headless_native_call(value,row).data()["accepted"] is True
    replay_headless_train_ledger(value)


def test_postflight_failure_retains_known_usage_and_closes_before_later_io(tmp_path, monkeypatch):
    value=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,value)
    import research_loop.modular.grok_headless_transport as transport
    original=transport._account_recovered; count={"n":0}
    def fail_after(*args,**kwargs):
        count["n"]+=1
        if count["n"]==2: raise transport.ContractError("synthetic postflight failure")
        return original(*args,**kwargs)
    monkeypatch.setattr(transport,"_account_recovered",fail_after)
    with pytest.raises(ContractError): value(REQUEST)
    row=value.ledger["calls"][0]
    assert row["status"]=="unknown_or_failed" and row["known_headless_main_usage"]["total_tokens"]==10
    native_response=Path(row["private_directory"])/"response.private.json"
    assert native_response.is_file() and FrozenRecord.from_dict(json.loads(native_response.read_text(encoding="utf-8"))).data()=={"ok":True}
    assert not (Path(row["private_directory"]).parent/"response.private.json").exists()
    assert value.ledger["usage_incomplete"] is True and len(calls)==1
    with pytest.raises(ContractError): value(REQUEST)
    assert len(calls)==1


def test_source_drift_closes_before_later_native_io(tmp_path, monkeypatch):
    value=port(tmp_path,max_calls=2)
    calls,_=synthetic_native(tmp_path,monkeypatch,value)
    value(REQUEST); Path(value.executable).write_bytes(b"drift")
    with pytest.raises(ContractError): value(REQUEST)
    assert len(calls)==1


def test_rehashed_private_request_closes_replay(tmp_path, monkeypatch):
    value=port(tmp_path,max_calls=2); synthetic_native(tmp_path,monkeypatch,value); value(REQUEST)
    row=value.ledger["calls"][0]; private=Path(row["private_request"]["path"])
    forged={"prompt":"foreign","output_schema":SCHEMA}; private.write_text(json.dumps(forged,sort_keys=True,separators=(",",":")),encoding="utf-8")
    row["private_request"]["sha256"]=hashlib.sha256(private.read_bytes()).hexdigest()
    row["frozen_files"][str(private)]=row["private_request"]["sha256"]
    value.ledger_path.write_text(json.dumps(value.ledger,sort_keys=True,separators=(",",":")),encoding="utf-8")
    with pytest.raises(ContractError):
        from research_loop.modular.grok_headless_train_solver import replay_headless_train_ledger
        replay_headless_train_ledger(value)
    assert value.ledger["usage_incomplete"] is True


@pytest.mark.parametrize("field",["native_receipt_sha256","reservation_sha256"])
def test_replay_rejects_persisted_native_hash_tamper(tmp_path, monkeypatch, field):
    value=port(tmp_path); synthetic_native(tmp_path,monkeypatch,value); value(REQUEST)
    value.ledger["calls"][0][field]="f"*64
    value.ledger_path.write_text(json.dumps(value.ledger,sort_keys=True,separators=(",",":")),encoding="utf-8")
    from research_loop.modular.grok_headless_train_solver import replay_headless_train_ledger
    with pytest.raises(ContractError): replay_headless_train_ledger(value)
    assert value.ledger["usage_incomplete"] is True


def test_second_port_with_stale_ledger_cannot_allocate_again(tmp_path, monkeypatch):
    first=port(tmp_path,max_calls=2); synthetic_native(tmp_path,monkeypatch,first)
    other=GrokHeadlessTrainModelPort(executable=first.executable,work_root=first.root,private_home=first.private_home,private_profile=first.private_profile,public_cwd=first.public_cwd,frozen_files={first.executable:hashlib.sha256(Path(first.executable).read_bytes()).hexdigest()},max_calls=2,schemas=first.schemas,slot_output_caps=first.slot_output_caps,slot_input_byte_caps=first.slot_input_byte_caps,observed_main_token_cap=first.observed_main_token_cap)
    first(REQUEST)
    with pytest.raises(ContractError): other(REQUEST)
    assert len(first.ledger["calls"]) == 1


def test_constructor_lock_and_corrupt_disk_bytes_are_preserved(tmp_path):
    first=port(tmp_path); original=first.ledger_path.read_bytes()
    first.lock_path.write_text("active",encoding="utf-8")
    with pytest.raises(ContractError):
        GrokHeadlessTrainModelPort(executable=first.executable,work_root=first.root,private_home=first.private_home,private_profile=first.private_profile,public_cwd=first.public_cwd,frozen_files={first.executable:hashlib.sha256(Path(first.executable).read_bytes()).hexdigest()},max_calls=1,schemas=first.schemas,slot_output_caps=first.slot_output_caps,slot_input_byte_caps=first.slot_input_byte_caps,observed_main_token_cap=first.observed_main_token_cap)
    assert first.ledger_path.read_bytes() == original and first.lock_path.exists()
    first.lock_path.unlink(); first.ledger_path.write_bytes(b'{"broken":')
    with pytest.raises(ContractError):
        GrokHeadlessTrainModelPort(executable=first.executable,work_root=first.root,private_home=first.private_home,private_profile=first.private_profile,public_cwd=first.public_cwd,frozen_files={first.executable:hashlib.sha256(Path(first.executable).read_bytes()).hexdigest()},max_calls=1,schemas=first.schemas,slot_output_caps=first.slot_output_caps,slot_input_byte_caps=first.slot_input_byte_caps,observed_main_token_cap=first.observed_main_token_cap)
    assert first.ledger_path.read_bytes() == b'{"broken":' and (first.root/"ledger.constructor-fault.json").read_bytes() == b'{"broken":'


@pytest.mark.parametrize("mutate",[
    lambda value: value.slot_output_caps.__setitem__("m4_plan", 1),
    lambda value: value.schemas.__setitem__("m4_plan", {"type":"object","properties":{},"additionalProperties":False}),
    lambda value: setattr(value, "model", "foreign-model"),
])
def test_live_port_configuration_mutation_rejects_before_native_io(tmp_path, mutate):
    value=port(tmp_path); mutate(value)
    with pytest.raises(ContractError): value(REQUEST)
    assert value.ledger["calls"] == [] and not list(value.calls_root.iterdir())
