"""Closed public TRAIN model port over the native headless Grok diagnostic seam."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import MODEL, TRAIN_OPPORTUNITY_CONTRACT, diagnostic_config
from research_loop.modular.grok_headless_transport import (
    EXECUTABLE_SHA256, HeadlessResult, run_headless_diagnostic, verify_headless_request_binding,
)
from research_loop.modular.model_port import _schema_witness, _validate_schema
from research_loop.ontology import ContractError, canonical


RECOVERY = {"schema": "headless-account-read-recovery-v1", "max_attempts": 2}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


class GrokHeadlessTrainModelPort:
    """One durable reservation per public request; any uncertainty closes I/O."""

    provider_kind = "grok-headless-public-train-v1"

    def __init__(self, *, executable: Path | str, work_root: Path, private_home: Path, private_profile: Path,
                 public_cwd: Path, frozen_files: Mapping[str, str], max_calls: int, schemas: Mapping[str, Mapping],
                 slot_output_caps: Mapping[str, int], slot_input_byte_caps: Mapping[str, int],
                 observed_main_token_cap: int, account_read_recovery: Mapping[str, Any] | None = RECOVERY,
                 native_invoke=run_headless_diagnostic) -> None:
        if (type(max_calls) is not int or max_calls < 1 or type(observed_main_token_cap) is not int
                or observed_main_token_cap < 2 or not isinstance(schemas, Mapping) or not schemas
                or set(schemas) != set(slot_output_caps) or set(schemas) != set(slot_input_byte_caps)):
            raise ContractError("invalid frozen headless TRAIN port contract")
        for slot, schema in schemas.items():
            if not isinstance(slot, str) or not isinstance(schema, Mapping) or schema.get("type") != "object":
                raise ContractError("headless TRAIN schemas must be object slots")
            _validate_schema(schema, _schema_witness(schema))
            if type(slot_output_caps[slot]) is not int or slot_output_caps[slot] < 1 or type(slot_input_byte_caps[slot]) is not int or slot_input_byte_caps[slot] < 1:
                raise ContractError("headless TRAIN per-slot bounds must be positive integers")
        if any(observed_main_token_cap < cap for cap in slot_output_caps.values()):
            raise ContractError("headless observed main token cap differs")
        if account_read_recovery is not None and account_read_recovery != RECOVERY:
            raise ContractError("unsupported headless account recovery contract")
        self.executable = str(Path(executable).resolve()); self.root = Path(work_root).resolve()
        self.private_home, self.private_profile, self.public_cwd = (Path(private_home).resolve(), Path(private_profile).resolve(), Path(public_cwd).resolve())
        self.frozen_files = dict(frozen_files); self.frozen_files[self.executable] = _sha(Path(self.executable).read_bytes())
        self.max_calls, self.schemas = max_calls, json.loads(canonical(schemas))
        self.slot_output_caps, self.slot_input_byte_caps = dict(slot_output_caps), dict(slot_input_byte_caps)
        self.observed_main_token_cap, self.account_read_recovery, self.native_invoke = observed_main_token_cap, account_read_recovery, native_invoke
        self.model, self.effort = MODEL, "low"; self.root.mkdir(parents=True, exist_ok=True)
        self.calls_root = self.root / "calls"; self.calls_root.mkdir(exist_ok=True); self.ledger_path = self.root / "ledger.json"
        config = {"schema":"grok-headless-train-solver-port-v1", "provider_kind":self.provider_kind, "model":MODEL,
                  "opportunity_contract":TRAIN_OPPORTUNITY_CONTRACT, "reasoning_effort":"low", "timeout_seconds":60,
                  "max_retries":0, "paid_fallback":False, "max_calls":max_calls, "schemas":self.schemas,
                  "slot_output_caps":self.slot_output_caps, "slot_input_byte_caps":self.slot_input_byte_caps,
                  "observed_main_token_cap":observed_main_token_cap, "account_read_recovery":account_read_recovery,
                  "executable":self.executable, "frozen_files":self.frozen_files}
        if self.ledger_path.exists():
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if self.ledger.get("config") != config: raise ContractError("existing headless TRAIN ledger differs")
            replay_headless_train_ledger(self)
        else:
            self.ledger = {"config":config, "calls":[], "known_main_tokens":0, "usage_incomplete":False}
            _write(self.ledger_path, self.ledger)

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        if not isinstance(request, FrozenRecord): raise ContractError("headless TRAIN port accepts frozen requests only")
        body=request.data(); slot=body.get("slot")
        if (set(body) != {"schema","task","lock_digest","objective","slot","instruction","context","module_context","execution_feedback"}
                or body.get("schema") != "public-model-request-v1" or slot not in self.schemas):
            raise ContractError("unexpected public headless TRAIN request")
        if self.ledger["usage_incomplete"] or len(self.ledger["calls"]) >= self.max_calls:
            raise ContractError("headless TRAIN ledger is closed")
        replay_headless_train_ledger(self)
        prompt = "Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n" + request.encoded
        raw=prompt.encode(); cap=self.slot_input_byte_caps[slot]
        if len(raw) > cap: raise ContractError("public TRAIN prompt exceeds frozen input cap")
        number=len(self.ledger["calls"])+1; directory=self.calls_root/f"{number:04d}-{slot}"; directory.mkdir()
        request_path=directory/"headless-request.private.json"; request_body={"prompt":prompt,"output_schema":self.schemas[slot]}
        request_path.write_bytes(canonical(request_body).encode())
        row={"id":number,"slot":slot,"request_sha256":request.content_hash,"opportunity_id":f"headless-train-{number:04d}-{slot}",
             "private_request":{"path":str(request_path),"sha256":_sha(request_path.read_bytes())},"status":"reserved",
             "main_opportunity":1,"possible_initial_title_opportunity":1,"known_headless_main_usage":None,
             "native_prompt_reservations":None,"main_dispatch_state":"unknown"}
        self.ledger["calls"].append(row); _write(self.ledger_path,self.ledger)
        try:
            home=directory/"native-home"; home.mkdir(); shutil.copyfile(self.private_home/"auth.json",home/"auth.json")
            config=home/"config.toml"; config.write_bytes(diagnostic_config(self.slot_output_caps[slot]).encode())
            profile=directory/"native-profile"; cwd=directory/"public-cwd"; profile.mkdir(); cwd.mkdir()
            frozen={**self.frozen_files,str(config):_sha(config.read_bytes()),str(request_path):row["private_request"]["sha256"]}
            context={"executable":self.executable,"cwd":str(cwd),"private_home":str(home),"private_profile":str(profile),"reasoning_effort":"low"}
            if self.account_read_recovery is not None: context["account_read_recovery"]=self.account_read_recovery
            row.update(frozen_files=frozen,native_context=context,config_path=str(config),private_directory=str(directory/"native"))
            _write(self.ledger_path,self.ledger)
            result=self.native_invoke(executable=self.executable,cwd=str(cwd),private_home=str(home),private_profile=str(profile),
                private_dir=str(directory/"native"),reservation=str(directory/"native-reservation.json"),frozen_files=frozen,
                prompt=prompt,schema=self.schemas[slot],main_output_cap=self.slot_output_caps[slot],
                observed_main_token_cap=self.observed_main_token_cap,input_byte_cap=cap,timeout=60,reasoning_effort="low",
                account_read_recovery=self.account_read_recovery)
            if not isinstance(result,HeadlessResult): raise ContractError("headless native result differs")
            receipt=result.receipt.data(); receipt_path=directory/"observer-receipt.private.json"; receipt_path.write_bytes(result.receipt.encoded.encode())
            inspection=receipt.get("stream_inspection") if isinstance(receipt,dict) else None
            usage=inspection.get("usage") if isinstance(inspection,dict) else None
            if isinstance(usage,dict) and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0:
                row["known_headless_main_usage"]=usage; self.ledger["known_main_tokens"] += usage["total_tokens"]
            row.update(native_receipt_sha256=_sha(receipt_path.read_bytes()),reservation_sha256=_sha((directory/"native-reservation.json").read_bytes()),
                       accepted=receipt.get("accepted") is True,native_prompt_reservations=1 if receipt.get("prompt_process_launched") is True else 0 if receipt.get("prompt_process_launched") is False else None,
                       main_dispatch_state="possibly_dispatched" if receipt.get("prompt_process_launched") is True else "not_dispatched")
            entry={"opportunity_id":row["opportunity_id"],"private_request":row["private_request"],"prompt_sha256":_sha(raw),
                   "schema_digest":_sha(canonical(self.schemas[slot]).encode()),"input_bytes":len(raw)}
            spec={"native_context":context,"reasoning_effort":"low","account_read_recovery":self.account_read_recovery,
                  "main_output_cap":self.slot_output_caps[slot],"observed_main_token_cap":self.observed_main_token_cap,
                  "max_input_bytes":cap,"timeout_seconds":60}
            binding=verify_headless_request_binding(result,entry,directory,spec,frozen)
            if not (receipt.get("accepted") is True and result.response is not None and binding.data().get("accepted") is True):
                raise ContractError("headless main dispatch or binding is unknown")
            _validate_schema(self.schemas[slot],result.response.data()); (directory/"response.private.json").write_bytes(result.response.encoded.encode())
            row.update(status="succeeded",response_sha256=result.response.content_hash,headless_binding=binding.data())
            _write(self.ledger_path,self.ledger); replay_headless_train_ledger(self); return result.response
        except Exception as exc:
            row.update(status="unknown_or_failed",error_type=type(exc).__name__); self.ledger["usage_incomplete"]=True
            _write(self.ledger_path,self.ledger); raise ContractError("headless native request is terminal; do not retry") from exc


def _replay_headless_native_call(port: GrokHeadlessTrainModelPort, row: Mapping[str,Any]) -> FrozenRecord:
    directory=port.calls_root/f"{row['id']:04d}-{row['slot']}"; receipt=FrozenRecord.from_dict(json.loads((directory/"observer-receipt.private.json").read_text(encoding="utf-8")))
    response=FrozenRecord.from_dict(json.loads((directory/"response.private.json").read_text(encoding="utf-8")))
    raw=json.loads(Path(row["private_request"]["path"]).read_text(encoding="utf-8")); prompt=raw["prompt"].encode(); slot=row["slot"]
    entry={"opportunity_id":row["opportunity_id"],"private_request":row["private_request"],"prompt_sha256":_sha(prompt),"schema_digest":_sha(canonical(port.schemas[slot]).encode()),"input_bytes":len(prompt)}
    spec={"native_context":row["native_context"],"reasoning_effort":"low","account_read_recovery":port.account_read_recovery,
          "main_output_cap":port.slot_output_caps[slot],"observed_main_token_cap":port.observed_main_token_cap,
          "max_input_bytes":port.slot_input_byte_caps[slot],"timeout_seconds":60}
    binding=verify_headless_request_binding(HeadlessResult(receipt,response),entry,directory,spec,row["frozen_files"])
    if binding.data() != row["headless_binding"] or response.content_hash != row["response_sha256"]: raise ContractError("headless replay binding differs")
    return binding


def replay_headless_train_ledger(port: GrokHeadlessTrainModelPort) -> None:
    try:
        disk=json.loads(port.ledger_path.read_text(encoding="utf-8"))
        if disk != port.ledger or disk.get("config") != port.ledger.get("config"): raise ContractError("headless ledger drifted")
        for path, expected in port.ledger["config"]["frozen_files"].items():
            if _sha(Path(path).read_bytes()) != expected: raise ContractError("headless source drifted")
        if port.ledger.get("usage_incomplete") or any(row.get("status") != "succeeded" for row in port.ledger["calls"]):
            raise ContractError("headless ledger contains unresolved opportunity")
        seen=set(); total=0
        for row in port.ledger["calls"]:
            if row["opportunity_id"] in seen: raise ContractError("duplicate headless opportunity")
            seen.add(row["opportunity_id"]); binding=_replay_headless_native_call(port,row)
            total += binding.data()["usage"]["main"]["total_tokens"]
        if total != port.ledger["known_main_tokens"]: raise ContractError("headless known MAIN accounting differs")
    except Exception as exc:
        port.ledger["usage_incomplete"]=True; port.ledger["terminal_reason"]="headless_provenance_replay_failed"; _write(port.ledger_path,port.ledger)
        raise ContractError("headless provenance replay failed; ledger closed") from exc
