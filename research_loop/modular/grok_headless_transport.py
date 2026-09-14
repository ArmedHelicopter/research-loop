"""Bounded Grok headless diagnostics with an independently readable receipt.

This is deliberately separate from ACP.  The service stream is evidence about
one main call; it neither settles billing nor proves that a requested output
limit was enforced on the wire.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import (
    DENIED_TOOLS, EXECUTABLE_SHA256, ProcessTree, diagnostic_config, profile,
)
from research_loop.modular.grok_cli_protocol import inspect_grok_stream
from research_loop.ontology import ContractError

MODEL = "grok-4.6"
ACCOUNT_ISSUER = "https://auth.x.ai"
PROXY = "https://cli-chat-proxy.grok.com/v1"
RECEIPT_SCHEMA = "grok-headless-diagnostic-receipt-v1"


@dataclass(frozen=True)
class HeadlessResult:
    receipt: FrozenRecord
    response: FrozenRecord | None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ContractError("required headless artifact is unreadable") from exc


def _write(path: Path, value) -> str:
    raw = _canon(value) if not isinstance(value, bytes) else value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return _sha(raw)


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _strict_json(raw: bytes):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))


def _account_projection(raw: bytes):
    """Gate a private official-proxy observation and return a safe projection.

    The provisioner owns the GET.  Its raw response is retained only under the
    private native directory, while this projection keeps no email/name/token.
    """
    try:
        value = _strict_json(raw)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid private account observation") from exc
    _require(isinstance(value, dict), "invalid private account observation")
    required = {"issuer", "client_id", "endpoint", "redirected", "api_key_auth", "account_id",
                "code_access", "unified_pool", "remaining_percentage", "onDemandCap",
                "onDemandUsed", "prepaidBalance", "auto_topup", "observed_at"}
    _require(required <= set(value), "account observation fields missing")
    _require(value["issuer"] == ACCOUNT_ISSUER and isinstance(value["client_id"], str)
             and value["client_id"], "first party OIDC binding missing")
    _require(value["endpoint"] == "/user?include=subscription" and value["redirected"] is False
             and value["api_key_auth"] is False, "account query transport not admitted")
    _require(isinstance(value["account_id"], str) and value["account_id"], "account identity missing")
    _require(value["code_access"] is True and value["unified_pool"] is True, "account access unavailable")
    remaining = value["remaining_percentage"]
    _require(type(remaining) in (int, float) and not isinstance(remaining, bool)
             and 0 < remaining <= 100, "included allowance unavailable")
    for field in ("onDemandCap", "onDemandUsed", "prepaidBalance"):
        _require(type(value[field]) in (int, float) and value[field] == 0, "paid fallback available")
    _require(value["auto_topup"] is False, "auto topup available")
    observed = value["observed_at"]
    _require(isinstance(observed, str) and observed, "account observation time missing")
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("account observation time invalid") from exc
    return {"raw_sha256": _sha(raw), "account_binding": _sha(value["account_id"].encode()),
            "issuer": ACCOUNT_ISSUER, "client_id": value["client_id"], "endpoint": value["endpoint"],
            "observed_at": observed, "remaining_percentage": remaining,
            "code_access": True, "unified_pool": True, "on_demand_cap": 0,
            "on_demand_used": 0, "prepaid_balance": 0, "auto_topup": False}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def _account(home: Path, destination: Path):
    """Three first-party CLI proxy GETs using only copied native OIDC."""
    destination.mkdir(exist_ok=False)
    store = _strict_json(_read(home / "auth.json"))
    choices = [v for v in store.values() if type(v) is dict and v.get("auth_mode") == "oidc"
               and v.get("oidc_issuer") == ACCOUNT_ISSUER
               and v.get("oidc_client_id") == "b1a00492-073a-47ea-816f-4c329264a828"]
    _require(len(choices) == 1, "native login identity")
    auth = choices[0]
    _require(all(isinstance(auth.get(k), str) and auth[k] and "\n" not in auth[k] and "\r" not in auth[k]
                 for k in ("key", "user_id")), "native login shape")
    _require(datetime.fromisoformat(auth["expires_at"].replace("Z", "+00:00")).timestamp() > time.time()+120,
             "native login near expiry")
    raws = {}; rows=[]; first=time.monotonic(); opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    for name, route in (("credits", "/billing?format=credits"), ("topup", "/auto-topup-rule"), ("user", "/user?include=subscription")):
        url=PROXY+route; request=urllib.request.Request(url, method="GET", headers={"Authorization":"Bearer "+auth["key"],"X-XAI-Token-Auth":"xai-grok-cli","x-userid":auth["user_id"],"x-grok-client-version":"1.0.13","Accept":"application/json"})
        row={"name":name,"method":"GET","url":url,"status":"reserved","started_at":datetime.now(timezone.utc).isoformat()}; rows.append(row); _write(destination/"requests.json",rows)
        try:
            with opener.open(request, timeout=10) as response:
                _require(response.geturl()==url, "account redirect")
                _require(response.status == 200, "account status"); raw=response.read(1048577); _require(len(raw)<=1048576,"account response size"); row["http_status"]=response.status
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc: raise ContractError("account http error") from exc
        _write(destination/(name+".private.json"),raw); row.update(status="received",bytes=len(raw),sha256=_sha(raw),received_at=datetime.now(timezone.utc).isoformat()); _write(destination/"requests.json",rows); raws[name]=_strict_json(raw)
    credits,topup,user=raws["credits"],raws["topup"],raws["user"]
    _require(user.get("userId")==auth["user_id"] and user.get("hasGrokCodeAccess") is True and user.get("userBlockedReason") in (None,"") and user.get("teamBlockedReasons")==[],"account access")
    cfg=credits.get("config") if isinstance(credits,dict) else None; _require(isinstance(cfg,dict) and cfg.get("isUnifiedBillingUser") is True,"unified pool")
    for k in ("onDemandCap","onDemandUsed","prepaidBalance"): _require(isinstance(cfg.get(k),dict) and set(cfg[k]) <= {"val"} and type(cfg[k].get("val",0)) is int and cfg[k].get("val",0)==0,"paid fallback")
    _require(credits.get("on_demand_enabled", False) is False, "on demand enabled")
    _require(topup in ({},{"rule":None}),"auto topup")
    period=cfg.get("currentPeriod"); now=datetime.now(timezone.utc); _require(isinstance(period,dict) and datetime.fromisoformat(period["start"].replace("Z","+00:00"))<=now<datetime.fromisoformat(period["end"].replace("Z","+00:00")),"period stale")
    pct=cfg.get("creditUsagePercent"); _require(type(pct) in (int,float) and not isinstance(pct,bool) and 0<=pct<100,"included balance")
    projection={"raw_sha256":{k:_sha(_read(destination/(k+".private.json"))) for k in raws},"account_binding":_sha(auth["user_id"].encode()),"issuer":ACCOUNT_ISSUER,"client_id":"b1a00492-073a-47ea-816f-4c329264a828","observed_at":now.isoformat(),"first_request_age_seconds":time.monotonic()-first,"remaining_percentage":100-pct,"code_access":True,"unified_pool":True,"on_demand_cap":0,"on_demand_used":0,"prepaid_balance":0,"auto_topup":False,"reported_subscription_tier":user.get("subscriptionTier")}
    _write(destination/"observation.json",projection); return projection


def _fresh_env(home: Path, profile_dir: Path):
    keep = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"}}
    temp = profile_dir / "temp"; temp.mkdir(parents=True, exist_ok=True)
    keep.update({"GROK_HOME": str(home), "USERPROFILE": str(profile_dir), "HOME": str(profile_dir),
                 "APPDATA": str(profile_dir / "AppData" / "Roaming"),
                 "LOCALAPPDATA": str(profile_dir / "AppData" / "Local"), "TEMP": str(temp), "TMP": str(temp),
                 "GROK_DISABLE_AUTOUPDATER": "1", "GROK_TITLE_REFRESH": "false",
                 "GROK_TURN_SUMMARY": "false", "GROK_MEMORY": "false", "GROK_WORKFLOWS": "false",
                 "GROK_SUBAGENTS": "false"})
    for key in ("APPDATA", "LOCALAPPDATA"):
        Path(keep[key]).mkdir(parents=True, exist_ok=True)
    return keep


def _empty_fresh(path: Path, code: str):
    _require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()), code)


def _stream_session(raw: bytes):
    for line in reversed(raw.decode("utf-8", "replace").splitlines()):
        try:
            item = _strict_json(line.encode())
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("type") == "end" and isinstance(item.get("sessionId"), str):
            return item["sessionId"]
    return "unobserved-session"


def _end_identity(raw: bytes):
    """Read only the terminal public identifiers; stream validation remains authoritative."""
    try:
        rows = [_strict_json(line.encode()) for line in raw.decode("utf-8").splitlines() if line.strip()]
        ends = [row for row in rows if isinstance(row, dict) and row.get("type") == "end"]
        if len(ends) == 1 and isinstance(ends[0].get("sessionId"), str) and isinstance(ends[0].get("requestId"), str):
            return ends[0]["sessionId"], ends[0]["requestId"]
    except (UnicodeError, TypeError, ValueError):
        pass
    return "unobserved-session", None


def run_headless_diagnostic(*, executable, cwd, private_home, private_profile, private_dir,
                            reservation, frozen_files, prompt, schema, main_output_cap,
                            observed_main_token_cap, input_byte_cap, timeout=240) -> HeadlessResult:
    """Run exactly one headless main turn.  No retry is performed after reservation."""
    executable, cwd = Path(executable).resolve(), Path(cwd).resolve()
    home, user, native = Path(private_home).resolve(), Path(private_profile).resolve(), Path(private_dir).resolve()
    _require(type(prompt) is str and isinstance(schema, dict), "headless request shape")
    _require(type(main_output_cap) is int and main_output_cap > 0, "headless output cap")
    _require(type(observed_main_token_cap) is int and observed_main_token_cap >= main_output_cap,
             "headless observed cap")
    _require(type(input_byte_cap) is int and 0 < len(prompt.encode("utf-8")) <= input_byte_cap,
             "headless input bound")
    _require(type(timeout) in (int, float) and 0 < timeout <= 240, "headless timeout")
    _require(executable.is_file() and _sha(_read(executable)) == EXECUTABLE_SHA256, "headless executable pin")
    _require((home / "auth.json").is_file() and _read(home / "config.toml") == diagnostic_config(main_output_cap).encode(),
             "fresh headless provisioner contract")
    _empty_fresh(cwd, "fresh cwd required")
    _require(not home.is_symlink() and not user.is_symlink() and not native.is_symlink(), "linked private context")
    _require(isinstance(frozen_files, dict) and frozen_files, "headless source manifest")
    for path, digest in frozen_files.items():
        _require(isinstance(path, str) and isinstance(digest, str) and _sha(_read(Path(path))) == digest,
                 "frozen source changed")
    native.mkdir(parents=True, exist_ok=True)
    prompt_raw, schema_raw = prompt.encode("utf-8"), _canon(schema)
    prompt_sha, schema_sha = _sha(prompt_raw), _sha(schema_raw)
    reservation_path = Path(reservation)
    _require(reservation_path.name == "native-reservation.json" and not reservation_path.exists(),
             "exclusive reservation path required")
    reservation_value = {"session_id": str(uuid.uuid4())}
    reservation_body = {"schema": "grok-headless-reservation-v1", "reservation": reservation_value,
                        "prompt_sha256": prompt_sha, "schema_digest": schema_sha, "input_bytes": len(prompt_raw),
                        "main_output_cap": main_output_cap, "observed_main_token_cap": observed_main_token_cap,
                        "timeout_seconds": timeout, "frozen_files": dict(sorted(frozen_files.items())), "retries": 0}
    reservation_sha = _write(reservation_path, reservation_body)
    _write(native / "prompt.private.txt", prompt_raw); _write(native / "schema.private.json", schema_raw)
    inspect_dir=native/"inspect"
    try:
        pre = _account(home,native/"billing-before")
    except Exception as exc:
        receipt = FrozenRecord.from_dict({"schema": RECEIPT_SCHEMA,"accepted":False,"faults":["preflight_account_failed"],"requested_model":MODEL,"headless_profile":profile(),"denied_tools":list(DENIED_TOOLS),"prompt_sha256":prompt_sha,"schema_digest":schema_sha,"input_bytes":len(prompt_raw),"command_sha256":None,"reservation_sha256":reservation_sha,"frozen_files":dict(sorted(frozen_files.items())),"native":{"stream_sha256":None,"stderr_sha256":None,"process_exit_code":None,"launched_at":None,"session_id":reservation_value["session_id"],"terminal_session_id":None,"request_id":None},"stream_inspection":None,"account_preflight":None,"account_postflight":None,"prompt_process_launched":False,"response_sha256":None,"initial_title_usage":None,"all_opportunity_usage":None,"billing_settlement":"not_established_by_headless_receipt","output_cap_wire_certified":False})
        _write(native/"observer-receipt.json",receipt.data()); return HeadlessResult(receipt,None)
    command = [str(executable), "--no-auto-update", "--cwd", str(cwd), "--model", MODEL, "--prompt-file", str(native / "prompt.private.txt"), "--json-schema", _canon(schema).decode(), "--output-format", "streaming-json", "--max-turns", "1", "--session-id", reservation_value["session_id"], "--no-subagents", "--no-plan", "--disable-web-search", "--disallowed-tools", ",".join(DENIED_TOOLS), "--agents", _canon({"transport-no-tools":profile()}).decode(), "--agent", "transport-no-tools", "--permission-mode", "dontAsk", "--deny", "MCPTool", "--system-prompt-override", "Return only the requested JSON. Do not use tools.", "--verbatim"]
    command_sha = _write(native / "command.json", command)
    launched_at = datetime.now(timezone.utc).isoformat()
    _require(pre["first_request_age_seconds"] <= 5, "account snapshot stale")
    raw = b""; stderr = b""; exit_code = None; fault = None; launched = False
    tree = None
    try:
        tree = ProcessTree(command, cwd=str(cwd), env=_fresh_env(home, user), stderr=subprocess.PIPE)
        launched = True
        raw, stderr = tree.process.communicate(timeout=timeout)
        exit_code = tree.process.returncode
    except subprocess.TimeoutExpired:
        fault = "timeout"
        if tree is not None:
            # Closing the Windows KILL_ON_JOB_CLOSE handle kills descendants before
            # the bounded reap; never wait indefinitely on an orphaned tree.
            if tree.job is not None:
                kernel, handle = tree.job; kernel.CloseHandle(handle); tree.job = None
            else:
                tree.process.kill()
            try: raw, stderr = tree.process.communicate(timeout=5)
            except subprocess.TimeoutExpired: fault = "process_tree_shutdown_failed"; raw = b""; stderr = b""; exit_code = -1
            else: exit_code = tree.process.returncode
    except (OSError, ContractError) as exc:
        fault = "launch_failed"
        stderr = str(exc).encode(); exit_code = -1
    finally:
        if tree is not None:
            try: tree.close()
            except (OSError, subprocess.TimeoutExpired): pass
    stream_sha, stderr_sha = _write(native / "stdout.private.jsonl", raw), _write(native / "stderr.private.txt", stderr)
    terminal_session, request_id = _end_identity(raw)
    inspection = inspect_grok_stream(raw, schema=schema, session_id=reservation_value["session_id"], max_output_tokens=main_output_cap,
                                     max_total_tokens=observed_main_token_cap, process_exit_code=exit_code if isinstance(exit_code, int) else -1)
    response_sha = None
    if inspection.response is not None:
        response_sha = _write(native / "response.private.json", inspection.response.data())
    post = None
    try: post = _account(home,native/"billing-after")
    except ContractError: fault = fault or "postflight_account_unavailable"
    body = inspection.receipt.data(); faults = list(body["faults"])
    if fault and fault not in faults: faults.append(fault)
    if post is not None and post["account_binding"] != pre["account_binding"]: faults.append("account_identity_changed")
    receipt = FrozenRecord.from_dict({"schema": RECEIPT_SCHEMA, "accepted": not faults, "faults": faults,
        "requested_model": MODEL, "headless_profile": profile(), "denied_tools": list(DENIED_TOOLS),
        "prompt_sha256": prompt_sha, "schema_digest": schema_sha, "input_bytes": len(prompt_raw),
        "command_sha256": command_sha, "reservation_sha256": reservation_sha, "frozen_files": dict(sorted(frozen_files.items())),
        "native": {"stream_sha256": stream_sha, "stderr_sha256": stderr_sha, "process_exit_code": exit_code,
                   "launched_at": launched_at, "session_id": reservation_value["session_id"], "terminal_session_id": terminal_session, "request_id": request_id if terminal_session == reservation_value["session_id"] else None},
        "stream_inspection": body, "account_preflight": pre, "account_postflight": post,
        "prompt_process_launched": launched,
        "response_sha256": response_sha,
        "initial_title_usage": None, "all_opportunity_usage": None,
        "billing_settlement": "not_established_by_headless_receipt", "output_cap_wire_certified": False})
    _write(native / "observer-receipt.json", receipt.data())
    return HeadlessResult(receipt, inspection.response if not faults else None)


def verify_headless_request_binding(result, entry, directory, spec, frozen_files) -> FrozenRecord:
    """Independently reread every bound artifact; never trust receipt acceptance alone."""
    _require(type(result) is HeadlessResult and type(result.receipt) is FrozenRecord, "headless result required")
    _require(isinstance(entry, dict) and isinstance(spec, dict) and isinstance(frozen_files, dict), "binding shape")
    directory = Path(directory); native = directory / "native"; receipt = result.receipt.data()
    _require(receipt.get("schema") == RECEIPT_SCHEMA, "not a headless receipt")
    _require(_strict_json(_read(native / "observer-receipt.json")) == receipt, "observer receipt changed")
    for path, digest in frozen_files.items(): _require(_sha(_read(Path(path))) == digest, "frozen source changed")
    for key in ("prompt_sha256", "schema_digest", "input_bytes"):
        _require(entry.get(key) == receipt.get(key), "authoring entry binding mismatch")
    descriptor = entry.get("private_request")
    _require(isinstance(descriptor, dict) and set(descriptor) == {"path", "sha256"}
             and isinstance(descriptor["path"], str) and isinstance(descriptor["sha256"], str),
             "private request descriptor malformed")
    descriptor_raw = _read(Path(descriptor["path"]))
    _require(_sha(descriptor_raw) == descriptor["sha256"], "private request descriptor changed")
    descriptor_body = _strict_json(descriptor_raw)
    _require(isinstance(descriptor_body, dict) and set(descriptor_body) == {"prompt", "output_schema"}
             and isinstance(descriptor_body["prompt"], str) and isinstance(descriptor_body["output_schema"], dict)
             and _sha(descriptor_body["prompt"].encode()) == receipt["prompt_sha256"]
             and _sha(_canon(descriptor_body["output_schema"])) == receipt["schema_digest"],
             "private request contents mismatch")
    reservation_path = directory / "native-reservation.json"
    _require(spec.get("main_output_cap") == _strict_json(_read(reservation_path))["main_output_cap"], "main cap mismatch")
    reservation = _strict_json(_read(reservation_path))
    _require(_sha(_canon(reservation)) == receipt["reservation_sha256"], "reservation digest mismatch")
    _require(receipt["native"]["session_id"] == reservation["reservation"]["session_id"], "reserved session mismatch")
    _require(reservation["observed_main_token_cap"] == spec.get("observed_main_token_cap")
             and reservation["input_bytes"] <= spec.get("max_input_bytes")
             and reservation["timeout_seconds"] == spec.get("timeout_seconds"), "request bounds mismatch")
    _require(_sha(_read(native / "prompt.private.txt")) == receipt["prompt_sha256"]
             and _sha(_read(native / "schema.private.json")) == receipt["schema_digest"], "private request changed")
    command = _strict_json(_read(native / "command.json")); _require(_sha(_canon(command)) == receipt["command_sha256"], "command changed")
    raw = _read(native / "stdout.private.jsonl"); _require(_sha(raw) == receipt["native"]["stream_sha256"], "raw stream changed")
    schema = _strict_json(_read(native / "schema.private.json")); session = receipt["native"]["session_id"]
    inspected = inspect_grok_stream(raw, schema=schema, session_id=session, max_output_tokens=spec["main_output_cap"],
                                    max_total_tokens=spec["observed_main_token_cap"], process_exit_code=receipt["native"]["process_exit_code"])
    _require(inspected.receipt.data() == receipt["stream_inspection"], "stream inspection mismatch")
    if inspected.response is None:
        _require(receipt["response_sha256"] is None, "unexpected response artifact")
    else:
        _require(receipt["response_sha256"] == _sha(_read(native / "response.private.json"))
                 and _strict_json(_read(native / "response.private.json")) == inspected.response.data(),
                 "response artifact mismatch")
        _require(result.response is not None and result.response.data() == inspected.response.data(),
                 "result response swap")
    try:
        pre = _strict_json(_read(native / "billing-before" / "observation.json")); post = _strict_json(_read(native / "billing-after" / "observation.json"))
    except (TypeError, ValueError) as exc:
        raise ContractError("account observation changed") from exc
    _require(pre == receipt["account_preflight"] and post == receipt["account_postflight"]
             and pre["account_binding"] == post["account_binding"], "account observation binding mismatch")
    accepted = bool(receipt["accepted"] and inspected.receipt.data()["accepted"] and result.response is not None)
    usage = inspected.receipt.data()["usage"]
    return FrozenRecord.from_dict({"schema": "grok-headless-request-binding-v1", "accepted": accepted,
        "opportunity_id": entry.get("opportunity_id"), "request": {"prompt_sha256": receipt["prompt_sha256"],
        "schema_digest": receipt["schema_digest"], "input_bytes": receipt["input_bytes"]},
        "identity": {"requested_model": MODEL, "accounting_model": inspected.receipt.data()["accounting_model"],
        "session_id": session, "request_id": receipt["native"]["request_id"]}, "usage": {"main": usage,
        "main_model_calls": inspected.receipt.data()["reported_main_model_calls"], "num_turns": 1 if usage is not None else None,
        "initial_title": None, "all_opportunities": None}, "account": {"preflight": pre, "postflight": post,
        "oldest_observed_at": min(pre["observed_at"], post["observed_at"])}, "faults": receipt["faults"]})
