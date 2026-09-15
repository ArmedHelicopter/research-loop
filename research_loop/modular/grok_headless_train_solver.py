"""Closed, replayable public TRAIN port over the headless diagnostic transport."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import MODEL, TRAIN_OPPORTUNITY_CONTRACT, diagnostic_config
from research_loop.modular.grok_headless_transport import HeadlessResult, run_headless_diagnostic, verify_headless_request_binding
from research_loop.modular.grok_native_deployment import checked_headless_train_deployment
from research_loop.modular.model_port import _schema_witness, _validate_schema
from research_loop.ontology import ContractError, canonical

RECOVERY = {"schema": "headless-account-read-recovery-v1", "max_attempts": 2}
_PROMPT_PREFIX = "Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n"


def _sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(value), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _exclusive(path: Path):
    acquired = False
    try:
        with path.open("x", encoding="utf-8") as out:
            out.write(str(os.getpid())); out.flush(); os.fsync(out.fileno())
        acquired = True
        yield
    except FileExistsError as exc:
        raise ContractError("headless TRAIN allocator is already in use") from exc
    finally:
        if acquired:
            try: path.unlink()
            except FileNotFoundError: pass


def _source_pins(deployment=None) -> dict[str, str]:
    import research_loop.modular.grok_acp_transport as acp
    import research_loop.modular.contracts as contracts
    import research_loop.modular.grok_headless_transport as headless
    import research_loop.modular.grok_cli_protocol as protocol
    import research_loop.modular.model_port as model_port
    import research_loop.ontology as ontology
    paths = [Path(__file__).resolve(), Path(acp.__file__).resolve(), Path(contracts.__file__).resolve(),
             Path(headless.__file__).resolve(), Path(protocol.__file__).resolve(), Path(model_port.__file__).resolve(),
             Path(ontology.__file__).resolve()]
    if deployment is not None:
        paths.extend(Path(path) for path in checked_headless_train_deployment(deployment).source_pins())
    return {str(path): _sha(path.read_bytes()) for path in paths}


class GrokHeadlessTrainModelPort:
    """One persisted reservation per request. Any uncertain result permanently closes I/O."""
    provider_kind = "grok-headless-public-train-v1"

    def __init__(self, *, executable: Path | str, work_root: Path, private_home: Path, private_profile: Path,
                 public_cwd: Path, frozen_files: Mapping[str, str], max_calls: int, schemas: Mapping[str, Mapping],
                 slot_output_caps: Mapping[str, int], slot_input_byte_caps: Mapping[str, int],
                 observed_main_token_cap: int, account_read_recovery: Mapping[str, Any] | None = RECOVERY,
                 native_invoke=run_headless_diagnostic, deployment=None) -> None:
        if native_invoke is not run_headless_diagnostic:
            raise ContractError("headless TRAIN requires the native diagnostic transport")
        if (type(max_calls) is not int or max_calls < 1 or type(observed_main_token_cap) is not int or observed_main_token_cap < 2
                or not isinstance(schemas, Mapping) or not schemas or set(schemas) != set(slot_output_caps) or set(schemas) != set(slot_input_byte_caps)):
            raise ContractError("invalid frozen headless TRAIN port contract")
        for slot, schema in schemas.items():
            if not isinstance(slot, str) or not isinstance(schema, Mapping) or schema.get("type") != "object": raise ContractError("headless TRAIN schemas must be object slots")
            _validate_schema(schema, _schema_witness(schema))
            if type(slot_output_caps[slot]) is not int or slot_output_caps[slot] < 1 or type(slot_input_byte_caps[slot]) is not int or slot_input_byte_caps[slot] < 1: raise ContractError("headless TRAIN per-slot bounds must be positive integers")
        if any(observed_main_token_cap <= cap for cap in slot_output_caps.values()): raise ContractError("headless observed main token cap differs")
        if (account_read_recovery is not None and (not isinstance(account_read_recovery, Mapping) or set(account_read_recovery) != set(RECOVERY)
                or account_read_recovery.get("schema") != RECOVERY["schema"] or type(account_read_recovery.get("max_attempts")) is not int
                or account_read_recovery["max_attempts"] != 2)): raise ContractError("unsupported headless account recovery contract")
        self.native_deployment = None if deployment is None else checked_headless_train_deployment(deployment)
        self.executable = str(Path(executable).resolve()); self.root = Path(work_root).resolve()
        self.private_home, self.private_profile, self.public_cwd = Path(private_home).resolve(), Path(private_profile).resolve(), Path(public_cwd).resolve()
        if self.native_deployment is not None:
            self.native_deployment.verify_executable(self.executable)
        supplied = dict(frozen_files); actual = _sha(Path(self.executable).read_bytes())
        if supplied.get(self.executable) != actual: raise ContractError("supplied headless executable pin differs")
        generated = _source_pins(self.native_deployment)
        if any(path in supplied and supplied[path] != digest for path, digest in generated.items()): raise ContractError("supplied headless source pin differs")
        supplied.update(generated); self.frozen_files = supplied
        self.max_calls, self.schemas = max_calls, json.loads(canonical(schemas)); self.slot_output_caps, self.slot_input_byte_caps = dict(slot_output_caps), dict(slot_input_byte_caps)
        self.observed_main_token_cap, self.account_read_recovery = observed_main_token_cap, json.loads(canonical(account_read_recovery)) if account_read_recovery is not None else None
        self.model, self.effort = MODEL, "low"; self.root.mkdir(parents=True, exist_ok=True); self.calls_root = self.root / "calls"; self.calls_root.mkdir(exist_ok=True); self.ledger_path = self.root / "ledger.json"; self.lock_path = self.root / "allocator.lock"
        config = {"schema":"grok-headless-train-solver-port-v1", "provider_kind":self.provider_kind, "model":MODEL, "opportunity_contract":TRAIN_OPPORTUNITY_CONTRACT, "reasoning_effort":"low", "timeout_seconds":60, "max_retries":0, "paid_fallback":False, "max_calls":max_calls, "title_opportunities_per_main":1, "title_usage_and_all_call_totals":"unknown", "api_key_route_permitted":False, "included_only":True, "schemas":self.schemas, "slot_output_caps":self.slot_output_caps, "slot_input_byte_caps":self.slot_input_byte_caps, "observed_main_token_cap":observed_main_token_cap, "account_read_recovery":self.account_read_recovery, "executable":self.executable, "executable_sha256":actual, "private_home":str(self.private_home), "private_profile_root":str(self.private_profile), "public_cwd_root":str(self.public_cwd), "frozen_files":self.frozen_files}
        if self.native_deployment is not None:
            config.update(native_deployment=self.native_deployment.record.data(), native_deployment_digest=self.native_deployment.digest)
        self._config_record = FrozenRecord.from_dict(config)
        config = self._config_record.data()
        with _exclusive(self.lock_path):
            if self.ledger_path.exists():
                raw = self.ledger_path.read_bytes()
                try:
                    self.ledger = json.loads(raw)
                    if self.ledger.get("config") != config: raise ContractError("existing headless TRAIN ledger differs")
                    replay_headless_train_ledger(self, preserve_failure=True)
                except Exception as exc:
                    fault = self.root / "ledger.constructor-fault.json"
                    if not fault.exists(): fault.write_bytes(raw)
                    raise ContractError("existing headless TRAIN ledger is not replayable") from exc
            else:
                self.ledger = {"config":config, "calls":[], "known_main_tokens":0, "tokens":0, "usage_incomplete":False}; _write(self.ledger_path, self.ledger)

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        _verify_live_config(self)
        if not isinstance(request, FrozenRecord): raise ContractError("headless TRAIN port accepts frozen requests only")
        body=request.data(); slot=body.get("slot")
        if (set(body) != {"schema","task","lock_digest","objective","slot","instruction","context","module_context","execution_feedback"} or body.get("schema") != "public-model-request-v1" or slot not in self.schemas): raise ContractError("unexpected public headless TRAIN request")
        with _exclusive(self.lock_path):
            if json.loads(self.ledger_path.read_text(encoding="utf-8")) != self.ledger: raise ContractError("headless TRAIN ledger changed by another allocator")
            if self.ledger["usage_incomplete"] or len(self.ledger["calls"]) >= self.max_calls: raise ContractError("headless TRAIN ledger is closed")
            replay_headless_train_ledger(self)
            prompt = _PROMPT_PREFIX + request.encoded; raw=prompt.encode(); cap=self.slot_input_byte_caps[slot]
            if len(raw) > cap: raise ContractError("public TRAIN prompt exceeds frozen input cap")
            number=len(self.ledger["calls"])+1; directory=self.calls_root/f"{number:04d}-{slot}"; directory.mkdir(); request_path=directory/"headless-request.private.json"; public_path=directory/"request.private.json"; public_path.write_bytes(request.encoded.encode()); request_path.write_bytes(canonical({"prompt":prompt,"output_schema":self.schemas[slot]}).encode())
            row={"id":number,"slot":slot,"request_sha256":request.content_hash,"opportunity_id":f"headless-train-{number:04d}-{slot}","public_request":{"path":str(public_path),"sha256":_sha(public_path.read_bytes())},"private_request":{"path":str(request_path),"sha256":_sha(request_path.read_bytes())},"status":"reserved","main_opportunity":1,"possible_initial_title_opportunity":1,"known_headless_main_usage":None,"native_prompt_reservations":None,"main_dispatch_state":"unknown"}
            self.ledger["calls"].append(row); _write(self.ledger_path,self.ledger)
            try:
                home=directory/"native-home"; home.mkdir(); shutil.copyfile(self.private_home/"auth.json",home/"auth.json"); config=home/"config.toml"; config.write_bytes(diagnostic_config(self.slot_output_caps[slot]).encode()); profile=directory/"native-profile"; cwd=directory/"public-cwd"; profile.mkdir(); cwd.mkdir()
                frozen={**self.frozen_files,str(config):_sha(config.read_bytes()),str(request_path):row["private_request"]["sha256"]}; context=_expected_context(self, row); row.update(frozen_files=frozen,native_context=context,config_path=str(config),private_directory=str(directory/"native")); _write(self.ledger_path,self.ledger)
                result=run_headless_diagnostic(executable=self.executable,cwd=str(cwd),private_home=str(home),private_profile=str(profile),private_dir=str(directory/"native"),reservation=str(directory/"native-reservation.json"),frozen_files=frozen,prompt=prompt,schema=self.schemas[slot],main_output_cap=self.slot_output_caps[slot],observed_main_token_cap=self.observed_main_token_cap,input_byte_cap=cap,timeout=60,reasoning_effort="low",account_read_recovery=self.account_read_recovery,deployment=self.native_deployment)
                if not isinstance(result,HeadlessResult): raise ContractError("headless native result differs")
                receipt=result.receipt.data(); receipt_path=directory/"observer-receipt.private.json"; receipt_path.write_bytes(result.receipt.encoded.encode()); usage=(receipt.get("stream_inspection") or {}).get("usage") if isinstance(receipt,dict) else None
                if isinstance(usage,dict) and type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0: row["known_headless_main_usage"]=usage; self.ledger["known_main_tokens"] += usage["total_tokens"]; self.ledger["tokens"] += usage["total_tokens"]
                reservation=directory/"native-reservation.json"; row.update(native_receipt_sha256=_sha(receipt_path.read_bytes()),reservation_sha256=_sha(reservation.read_bytes()),accepted=receipt.get("accepted") is True,native_prompt_reservations=1 if receipt.get("prompt_process_launched") is True else 0 if receipt.get("prompt_process_launched") is False else None,main_dispatch_state="possibly_dispatched" if receipt.get("prompt_process_launched") is True else "not_dispatched")
                binding=_verify_row(self,row,result)
                if not (receipt.get("accepted") is True and result.response is not None and binding.data().get("accepted") is True): raise ContractError("headless main dispatch or binding is unknown")
                _validate_schema(self.schemas[slot],result.response.data()); (directory/"response.private.json").write_bytes(result.response.encoded.encode()); row.update(status="succeeded",response_sha256=result.response.content_hash,headless_binding=binding.data()); _write(self.ledger_path,self.ledger); replay_headless_train_ledger(self); _verify_live_config(self); return result.response
            except Exception as exc:
                row.update(status="unknown_or_failed",error_type=type(exc).__name__); self.ledger["usage_incomplete"]=True; _write(self.ledger_path,self.ledger); raise ContractError("headless native request is terminal; do not retry") from exc


def _directory(port, row): return port.calls_root/f"{row['id']:04d}-{row['slot']}"


def _verify_live_config(port):
    """Bind mutable Python attributes to the immutable constructor record before I/O."""
    frozen = port._config_record.data()
    expected = {"provider_kind":port.provider_kind, "model":port.model, "reasoning_effort":port.effort,
                "max_calls":port.max_calls, "schemas":port.schemas, "slot_output_caps":port.slot_output_caps,
                "slot_input_byte_caps":port.slot_input_byte_caps, "observed_main_token_cap":port.observed_main_token_cap,
                "account_read_recovery":port.account_read_recovery, "executable":port.executable,
                "private_home":str(port.private_home), "private_profile_root":str(port.private_profile),
                "public_cwd_root":str(port.public_cwd), "frozen_files":port.frozen_files}
    if port.native_deployment is None:
        if 'native_deployment' in frozen or 'native_deployment_digest' in frozen:
            raise ContractError("legacy headless TRAIN deployment drifted")
    else:
        expected.update(native_deployment=port.native_deployment.record.data(),
                        native_deployment_digest=port.native_deployment.digest)
    if any(frozen.get(key) != value for key, value in expected.items()): raise ContractError("live headless TRAIN configuration drifted")
    if _sha(Path(port.executable).read_bytes()) != frozen["executable_sha256"]: raise ContractError("live headless executable drifted")
    if port.ledger.get("config") != frozen: raise ContractError("headless TRAIN ledger configuration drifted")
    return frozen


def _expected_context(port, row):
    directory=_directory(port,row); context={"executable":port.executable,"cwd":str(directory/"public-cwd"),"private_home":str(directory/"native-home"),"private_profile":str(directory/"native-profile"),"reasoning_effort":"low"}
    if port.account_read_recovery is not None: context["account_read_recovery"]=port.account_read_recovery
    if port.native_deployment is not None: context['native_deployment'] = port.native_deployment.record.data()
    return context


def _expected_private(port, row):
    descriptor=row.get("private_request"); expected=_directory(port,row)/"headless-request.private.json"
    if not isinstance(descriptor,dict) or descriptor.get("path") != str(expected) or set(descriptor) != {"path","sha256"}: raise ContractError("private request location differs")
    raw=expected.read_bytes()
    if _sha(raw) != descriptor["sha256"]: raise ContractError("private request hash differs")
    private=json.loads(raw)
    if raw != canonical(private).encode() or set(private) != {"prompt","output_schema"} or private["output_schema"] != port.schemas[row["slot"]] or not isinstance(private["prompt"],str) or not private["prompt"].startswith(_PROMPT_PREFIX): raise ContractError("private request shape differs")
    public_path=_directory(port,row)/"request.private.json"; public_descriptor=row.get("public_request")
    if not isinstance(public_descriptor,dict) or public_descriptor != {"path":str(public_path),"sha256":_sha(public_path.read_bytes())}: raise ContractError("public request descriptor differs")
    public=FrozenRecord.from_dict(json.loads(public_path.read_text(encoding="utf-8")))
    data=public.data()
    if (public.content_hash != row.get("request_sha256") or public_path.read_bytes() != public.encoded.encode()
            or private["prompt"] != _PROMPT_PREFIX + public.encoded
            or set(data) != {"schema","task","lock_digest","objective","slot","instruction","context","module_context","execution_feedback"}
            or data.get("schema") != "public-model-request-v1" or data.get("slot") != row["slot"]): raise ContractError("private request public binding differs")
    return private


def _expected_frozen(port,row):
    directory=_directory(port,row); _expected_private(port,row); config=directory/"native-home"/"config.toml"; return {**port.frozen_files,str(config):_sha(config.read_bytes()),str(directory/"headless-request.private.json"):row["private_request"]["sha256"]}


def _verify_row(port, row, result=None):
    if not isinstance(row.get("id"),int) or row["id"] < 1 or row.get("slot") not in port.schemas: raise ContractError("malformed headless row")
    directory=_directory(port,row); private=_expected_private(port,row); frozen=_expected_frozen(port,row); context=_expected_context(port,row)
    if row.get("native_context") != context or row.get("frozen_files") != frozen: raise ContractError("row native authority differs")
    receipt_path=directory/"observer-receipt.private.json"; reservation=directory/"native-reservation.json"
    if _sha(receipt_path.read_bytes()) != row.get("native_receipt_sha256") or _sha(reservation.read_bytes()) != row.get("reservation_sha256"): raise ContractError("row native artifact hash differs")
    receipt=FrozenRecord.from_dict(json.loads(receipt_path.read_text(encoding="utf-8")))
    if result is None: result=HeadlessResult(receipt,FrozenRecord.from_dict(json.loads((directory/"response.private.json").read_text(encoding="utf-8"))))
    elif result.receipt != receipt: raise ContractError("persisted native receipt differs")
    prompt=private["prompt"].encode(); slot=row["slot"]; entry={"opportunity_id":row["opportunity_id"],"private_request":row["private_request"],"prompt_sha256":_sha(prompt),"schema_digest":_sha(canonical(port.schemas[slot]).encode()),"input_bytes":len(prompt)}; spec={"native_context":context,"reasoning_effort":"low","account_read_recovery":port.account_read_recovery,"main_output_cap":port.slot_output_caps[slot],"observed_main_token_cap":port.observed_main_token_cap,"max_input_bytes":port.slot_input_byte_caps[slot],"timeout_seconds":60}; binding=verify_headless_request_binding(result,entry,directory,spec,frozen,deployment=port.native_deployment)
    if row.get("known_headless_main_usage") != binding.data().get("usage",{}).get("main"): raise ContractError("known MAIN usage differs")
    return binding


def _replay_headless_native_call(port, row):
    binding=_verify_row(port,row); response=FrozenRecord.from_dict(json.loads((_directory(port,row)/"response.private.json").read_text(encoding="utf-8")))
    if binding.data() != row.get("headless_binding") or response.content_hash != row.get("response_sha256"): raise ContractError("headless replay binding differs")
    return binding


def replay_headless_train_ledger(port, *, preserve_failure=False):
    try:
        frozen = _verify_live_config(port)
        disk=json.loads(port.ledger_path.read_text(encoding="utf-8"))
        if disk != port.ledger or disk.get("config") != frozen: raise ContractError("headless ledger drifted")
        for path, expected in port.ledger["config"]["frozen_files"].items():
            if _sha(Path(path).read_bytes()) != expected: raise ContractError("headless source drifted")
        rows=port.ledger.get("calls")
        if not isinstance(rows,list) or len(rows) > frozen["max_calls"] or port.ledger.get("usage_incomplete") or any(row.get("status") != "succeeded" for row in rows): raise ContractError("headless ledger contains unresolved opportunity")
        if [row.get("id") for row in rows] != list(range(1,len(rows)+1)): raise ContractError("headless opportunity order differs")
        total=0
        for row in rows:
            if row.get("opportunity_id") != f"headless-train-{row['id']:04d}-{row['slot']}" or row.get("main_opportunity") != 1 or row.get("possible_initial_title_opportunity") != 1: raise ContractError("headless opportunity allocation differs")
            total += _replay_headless_native_call(port,row).data()["usage"]["main"]["total_tokens"]
        if total != port.ledger.get("known_main_tokens") or total != port.ledger.get("tokens"): raise ContractError("headless known MAIN accounting differs")
    except Exception as exc:
        if not preserve_failure:
            port.ledger["usage_incomplete"]=True; port.ledger["terminal_reason"]="headless_provenance_replay_failed"; _write(port.ledger_path,port.ledger)
        raise ContractError("headless provenance replay failed; ledger closed") from exc
