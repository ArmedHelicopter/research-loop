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
from research_loop.modular.grok_native_deployment import checked_headless_train_deployment
from research_loop.modular.grok_cli_protocol import inspect_grok_stream
from research_loop.ontology import ContractError

MODEL = "grok-4.6"
ALLOWED_REASONING_EFFORTS = frozenset({'low', 'medium', 'high', 'xhigh'})
ACCOUNT_ISSUER = "https://auth.x.ai"
PROXY = "https://cli-chat-proxy.grok.com/v1"
RECEIPT_SCHEMA = "grok-headless-diagnostic-receipt-v1"
RECOVERY_RECEIPT_SCHEMA = "grok-headless-diagnostic-receipt-v2"
RECOVERY_RESERVATION_SCHEMA = "grok-headless-reservation-v2"
ACCOUNT_RECOVERY_SCHEMA = 'headless-account-read-recovery-v1'
LEGACY_ACCOUNT_CLIENT_VERSION = '1.0.13'
INSPECT_EMPTY_COLLECTIONS = ('skills', 'hooks', 'plugins', 'mcpServers', 'projectInstructions')
# The account preflight has three sequential first-party GETs, each with a
# ten-second transport timeout.  Keep a finite age bound, but do not make a
# successful, policy-compliant sequential observation impossible to launch.
# This value is copied into every reservation and checked by the independent
# rereader, so it is a per-attempt frozen transport policy rather than ambient
# timing.
ACCOUNT_PRELAUNCH_MAX_AGE_SECONDS = 35


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


def _instant(value):
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(instant.utcoffset() is not None, 'timestamp timezone missing')
        return instant
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError('invalid timestamp') from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


ACCOUNT_ROUTES = (("credits", "/billing?format=credits"), ("topup", "/auto-topup-rule"),
                  ("user", "/user?include=subscription"))


def _project_account(raws, rows, observed_at, *, expected_user_id=None, client_version=None):
    """Derive the safe account projection from the retained raw GET evidence."""
    _require(isinstance(raws, dict) and set(raws) == {name for name, _ in ACCOUNT_ROUTES},
             "account raw inventory")
    _require(isinstance(rows, list) and len(rows) == 3, "account request inventory")
    now = _instant(observed_at)
    previous = None
    for row, (name, route) in zip(rows, ACCOUNT_ROUTES):
        _require(isinstance(row, dict) and row.get("name") == name and row.get("method") == "GET"
                 and row.get("url") == PROXY + route and row.get("status") == "received"
                 and row.get("http_status") == 200 and row.get("sha256") == _sha(raws[name]),
                 "account request binding")
        if client_version is not None:
            _require(row.get('client_version') == client_version, 'account client version binding')
        started, received = _instant(row.get('started_at')), _instant(row.get('received_at'))
        _require((previous is None or previous <= started) and started <= received <= now
                 and row.get('bytes') == len(raws[name]), 'account request timing')
        previous = received
    try:
        credits, topup, user = (_strict_json(raws[name]) for name, _ in ACCOUNT_ROUTES)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid private account observation") from exc
    _require(isinstance(user, dict) and isinstance(user.get("userId"), str) and user["userId"],
             "account identity")
    _require(expected_user_id is None or user["userId"] == expected_user_id, "account binding")
    _require(user.get("hasGrokCodeAccess") is True and user.get("userBlockedReason") in (None, "")
             and user.get("teamBlockedReasons") == [], "account access")
    cfg = credits.get("config") if isinstance(credits, dict) else None
    _require(isinstance(cfg, dict) and cfg.get("isUnifiedBillingUser") is True, "unified pool")
    for key in ("onDemandCap", "onDemandUsed", "prepaidBalance"):
        _require(isinstance(cfg.get(key), dict) and set(cfg[key]) <= {"val"}
                 and type(cfg[key].get("val", 0)) is int and cfg[key].get("val", 0) == 0,
                 "paid fallback")
    _require(credits.get("on_demand_enabled", False) is False and topup in ({}, {"rule": None}),
             "paid fallback")
    period = cfg.get("currentPeriod")
    try:
        _require(isinstance(period, dict) and _instant(period["start"])
                 <= now < _instant(period["end"]), "period stale")
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("period stale") from exc
    percent = cfg.get("creditUsagePercent")
    _require(type(percent) in (int, float) and not isinstance(percent, bool) and 0 <= percent < 100,
             "included balance")
    return {"raw_sha256": {name: _sha(raws[name]) for name, _ in ACCOUNT_ROUTES},
            "account_binding": _sha(user["userId"].encode()), "issuer": ACCOUNT_ISSUER,
            "client_id": "b1a00492-073a-47ea-816f-4c329264a828", "observed_at": observed_at,
            "oldest_observed_at": rows[0]['started_at'],
            "remaining_percentage": 100-percent, "code_access": True, "unified_pool": True,
            "on_demand_cap": 0, "on_demand_used": 0, "prepaid_balance": 0, "auto_topup": False,
            "reported_subscription_tier": user.get("subscriptionTier")}


def _account(home: Path, destination: Path, *, client_version=None):
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
    version = LEGACY_ACCOUNT_CLIENT_VERSION if client_version is None else client_version
    _require(type(version) is str and version in (LEGACY_ACCOUNT_CLIENT_VERSION, '1.0.30'), 'account client version')
    raws = {}; rows=[]; first=time.monotonic(); opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    for name, route in ACCOUNT_ROUTES:
        url=PROXY+route; request=urllib.request.Request(url, method="GET", headers={"Authorization":"Bearer "+auth["key"],"X-XAI-Token-Auth":"xai-grok-cli","x-userid":auth["user_id"],"x-grok-client-version":version,"Accept":"application/json"})
        extra = {} if client_version is None else {'client_version': version}
        row={"name":name,"method":"GET","url":url,"status":"reserved","started_at":datetime.now(timezone.utc).isoformat(), **extra}; rows.append(row); _write(destination/"requests.json",rows)
        try:
            with opener.open(request, timeout=10) as response:
                _require(response.geturl()==url, "account redirect")
                _require(response.status == 200, "account status"); raw=response.read(1048577); _require(len(raw)<=1048576,"account response size"); row["http_status"]=response.status
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc: raise ContractError("account http error") from exc
        _write(destination/(name+".private.json"),raw); row.update(status="received",bytes=len(raw),sha256=_sha(raw),received_at=datetime.now(timezone.utc).isoformat()); _write(destination/"requests.json",rows); raws[name]=_strict_json(raw)
    projection = _project_account({name: _read(destination / (name + ".private.json"))
                                   for name, _ in ACCOUNT_ROUTES}, rows, datetime.now(timezone.utc).isoformat(),
                                  expected_user_id=auth["user_id"], client_version=client_version)
    _write(destination/"observation.json",projection); return projection


class _AccountReadTransportError(ContractError):
    def __init__(self, route, error_class, status=None):
        super().__init__('account http error')
        self.route, self.error_class, self.status = route, error_class, status


def _recovery(value):
    if value is None:
        return None
    _require(isinstance(value, dict) and set(value) == {'schema', 'max_attempts'}
             and value['schema'] == ACCOUNT_RECOVERY_SCHEMA and type(value['max_attempts']) is int and value['max_attempts'] == 2,
             'account recovery contract')
    return dict(value)


def _account_once(home: Path, destination: Path, *, client_version=None):
    """One recorded full observation attempt; only named transient HTTP errors escape typed."""
    destination.mkdir(exist_ok=False)
    store = _strict_json(_read(home / 'auth.json'))
    choices = [v for v in store.values() if type(v) is dict and v.get('auth_mode') == 'oidc'
               and v.get('oidc_issuer') == ACCOUNT_ISSUER and v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    _require(len(choices) == 1, 'native login identity'); auth = choices[0]
    _require(all(isinstance(auth.get(k), str) and auth[k] and '\n' not in auth[k] and '\r' not in auth[k] for k in ('key','user_id')), 'native login shape')
    _require(datetime.fromisoformat(auth['expires_at'].replace('Z','+00:00')).timestamp() > time.time()+120, 'native login near expiry')
    version = LEGACY_ACCOUNT_CLIENT_VERSION if client_version is None else client_version
    _require(type(version) is str and version in (LEGACY_ACCOUNT_CLIENT_VERSION, '1.0.30'), 'account client version')
    raws={}; rows=[]; opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    for name, route in ACCOUNT_ROUTES:
        url=PROXY+route; request=urllib.request.Request(url, method='GET', headers={'Authorization':'Bearer '+auth['key'],'X-XAI-Token-Auth':'xai-grok-cli','x-userid':auth['user_id'],'x-grok-client-version':version,'Accept':'application/json'})
        extra = {} if client_version is None else {'client_version': version}
        row={'name':name,'method':'GET','url':url,'status':'reserved','started_at':datetime.now(timezone.utc).isoformat(), **extra}; rows.append(row); _write(destination/'requests.json',rows)
        try:
            with opener.open(request, timeout=10) as response:
                _require(response.geturl()==url, 'account redirect'); _require(response.status == 200, 'account status')
                raw=response.read(1048577); _require(len(raw)<=1048576,'account response size'); row['http_status']=response.status
        except urllib.error.HTTPError as exc:
            row.update(status='failed', error_class='HTTPError', http_status=exc.code, received_at=datetime.now(timezone.utc).isoformat()); _write(destination/'requests.json',rows)
            if exc.code in (429,502,503,504): raise _AccountReadTransportError(name, 'HTTPError', exc.code) from exc
            raise ContractError('account http error') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            row.update(status='failed', error_class=type(exc).__name__, received_at=datetime.now(timezone.utc).isoformat()); _write(destination/'requests.json',rows)
            raise _AccountReadTransportError(name, type(exc).__name__) from exc
        _write(destination/(name+'.private.json'),raw); row.update(status='received',bytes=len(raw),sha256=_sha(raw),received_at=datetime.now(timezone.utc).isoformat()); _write(destination/'requests.json',rows); raws[name]=_strict_json(raw)
        # A received bad account body is a contract failure, never a reason to
        # retry a later transient route and discard the already retained bytes.
        if name == 'credits':
            cfg=raws[name].get('config') if isinstance(raws[name],dict) else None
            _require(isinstance(cfg,dict) and cfg.get('isUnifiedBillingUser') is True
                     and all(isinstance(cfg.get(k),dict) and set(cfg[k]) <= {'val'} and type(cfg[k].get('val',0)) is int and cfg[k].get('val',0) == 0 for k in ('onDemandCap','onDemandUsed','prepaidBalance'))
                     and raws[name].get('on_demand_enabled',False) is False, 'paid fallback')
            period=cfg.get('currentPeriod'); percent=cfg.get('creditUsagePercent')
            _require(isinstance(period,dict) and _instant(period.get('start')) <= datetime.now(timezone.utc) < _instant(period.get('end'))
                     and type(percent) in (int,float) and not isinstance(percent,bool) and 0 <= percent < 100, 'included balance')
        elif name == 'topup':
            _require(raws[name] in ({},{'rule':None}), 'paid fallback')
        elif name == 'user':
            _require(isinstance(raws[name],dict) and isinstance(raws[name].get('userId'),str) and raws[name]['userId'] and raws[name].get('hasGrokCodeAccess') is True
                     and raws[name].get('userBlockedReason') in (None,'') and raws[name].get('teamBlockedReasons') == [], 'account access')
    projection=_project_account({name:_read(destination/(name+'.private.json')) for name,_ in ACCOUNT_ROUTES},rows,datetime.now(timezone.utc).isoformat(),expected_user_id=auth['user_id'],client_version=client_version)
    _write(destination/'observation.json',projection); return projection


def _account_recovered(home: Path, destination: Path, recovery, *, client_version=None):
    recovery=_recovery(recovery); destination.mkdir(exist_ok=False); attempts=[]
    for index in range(recovery['max_attempts']):
        attempt=destination/f'attempt-{index:03d}'
        try:
            projection=_account_once(home, attempt, client_version=client_version)
            attempts.append({'index':index,'status':'accepted','projection_sha256':_sha(_read(attempt/'observation.json')),
                             'requests_sha256':_sha(_read(attempt/'requests.json'))})
            manifest={'schema':ACCOUNT_RECOVERY_SCHEMA,'recovery':recovery,'attempts':attempts,'winning_attempt':index,'projection':projection}
            _write(destination/'attempts.json',manifest); return manifest
        except _AccountReadTransportError as exc:
            failure={'route':exc.route,'error_class':exc.error_class,'http_status':exc.status,'failed_at':datetime.now(timezone.utc).isoformat()}
            _write(attempt/'failure.json',failure); attempts.append({'index':index,'status':'transient_failed','failure_sha256':_sha(_read(attempt/'failure.json')),
                                                                      'requests_sha256':_sha(_read(attempt/'requests.json'))})
            _write(destination/'attempts.json',{'schema':ACCOUNT_RECOVERY_SCHEMA,'recovery':recovery,'attempts':attempts,'winning_attempt':None,'projection':None})
        except (ContractError, ValueError, TypeError, KeyError):
            # Retain the received prefix and a non-secret terminal category; it
            # is policy/schema evidence, not a retryable transport condition.
            rows=_strict_json(_read(attempt/'requests.json')) if (attempt/'requests.json').exists() else []
            failure={'route':rows[-1]['name'] if rows else None,'error_class':'ContractError','http_status':None,'failed_at':datetime.now(timezone.utc).isoformat()}
            _write(attempt/'failure.json',failure); attempts.append({'index':index,'status':'terminal_failed','failure_sha256':_sha(_read(attempt/'failure.json')),
                                                                      'requests_sha256':_sha(_read(attempt/'requests.json')) if rows else None})
            _write(destination/'attempts.json',{'schema':ACCOUNT_RECOVERY_SCHEMA,'recovery':recovery,'attempts':attempts,'winning_attempt':None,'projection':None})
            raise ContractError('account observation terminal failure') from None
    raise ContractError('account recovery exhausted')


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
                 "GROK_SUBAGENTS": "false", "GROK_DISABLE_API_KEY_AUTH": "1",
                 "HOMEDRIVE": profile_dir.drive, "HOMEPATH": str(profile_dir)[len(profile_dir.drive):]})
    for key in ("APPDATA", "LOCALAPPDATA"):
        Path(keep[key]).mkdir(parents=True, exist_ok=True)
    return keep


def _plain(path):
    path = Path(path)
    _require(path.is_absolute(), 'absolute native path required')
    for part in (path, *path.parents):
        _require(not part.is_symlink() and not part.is_junction(), 'linked native path')
    return path


def _sources(files):
    _require(isinstance(files, dict) and files, 'frozen source inventory required')
    for path, expected in files.items():
        _require(_sha(_read(_plain(path))) == expected, 'frozen source changed')


def _command(context, native, session, schema, reasoning_effort=None):
    command = [context['executable'], '--no-auto-update', '--cwd', context['cwd'], '--model', MODEL]
    if reasoning_effort is not None:
        command.extend(('--reasoning-effort', reasoning_effort))
    return command + [
        '--prompt-file', str(native / 'prompt.private.txt'), '--json-schema', _canon(schema).decode(),
        '--output-format', 'streaming-json', '--max-turns', '1', '--session-id', session,
        '--no-subagents', '--no-plan', '--disable-web-search', '--disallowed-tools', ','.join(DENIED_TOOLS),
        '--agents', _canon({'transport-no-tools': profile()}).decode(), '--agent', 'transport-no-tools',
        '--permission-mode', 'dontAsk', '--deny', 'MCPTool', '--system-prompt-override',
        'Return only the requested JSON. Do not use tools.', '--verbatim']


def _inspect_command(context):
    return [context['executable'], '--no-auto-update', '--cwd', context['cwd'], 'inspect', '--json']


def _inspect(raw, deployment=None):
    value = _strict_json(raw)
    if deployment is not None:
        checked_headless_train_deployment(deployment)
        _require(deployment.record.data()['inspect_inventory_contract'] == 'grok-headless-inspect-empty-v1',
                 'headless inspect deployment contract')
    _require(isinstance(value, dict) and all(value.get(k) == [] for k in
        INSPECT_EMPTY_COLLECTIONS), 'external native context')
    _require(value.get('loginPolicy', {}).get('apiKeyAuthDisabled') is True,
        'API key authentication disablement unobserved')
    return value


def _child(command, context, environment, directory, timeout):
    directory.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    raw = error = b''; tree = None; expired = False; failure = None; closed = False; code = None
    try:
        tree = ProcessTree(command, cwd=context['cwd'], env=environment, stderr=subprocess.PIPE)
        try:
            raw, error = tree.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            expired = True; raw, error = exc.stdout or b'', exc.stderr or b''
            if tree.job is not None:
                kernel, handle = tree.job; kernel.CloseHandle(handle); tree.job = None
            else:
                tree.process.kill()
            try:
                raw, error = tree.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                failure = 'process_tree_shutdown_failed'
        code = tree.process.poll()
    except Exception:
        failure = 'process_launch_or_io_failed'
    finally:
        if tree is not None:
            try:
                if os.name == 'nt' and tree.job is None:
                    tree.process.wait(timeout=5)
                    for stream in (tree.process.stdin, tree.process.stdout, tree.process.stderr):
                        if stream is not None: stream.close()
                else:
                    tree.close()
                closed = tree.job is None and tree.process.poll() is not None
            except Exception:
                failure = 'process_tree_shutdown_failed'
        else:
            closed = None
    observation = {'command': command, 'environment': environment, 'cwd': context['cwd'],
        'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'timeout_seconds': timeout, 'timed_out': expired, 'failure': failure,
        'pid': tree.process.pid if tree is not None else None,
        # A constructor may spawn and then fail while assigning the Job. Without
        # a returned process handle, absence of a launch is not established.
        'launched': True if tree is not None else None,
        'process_exit_code': code, 'owned_tree_closed': closed,
        'stdout_sha256': _write(directory / 'stdout.private.jsonl', raw),
        'stderr_sha256': _write(directory / 'stderr.private.txt', error)}
    _write(directory / 'process.json', observation)
    return raw, observation


def _process_ok(process):
    return (process.get('launched') is True and process.get('process_exit_code') == 0
        and process.get('failure') is None and process.get('timed_out') is False
        and process.get('owned_tree_closed') is True)


def run_headless_diagnostic(*, executable, cwd, private_home, private_profile, private_dir,
                            reservation, frozen_files, prompt, schema, main_output_cap,
                            observed_main_token_cap, input_byte_cap, timeout=240,
                            reasoning_effort=None, account_read_recovery=None,
                            deployment=None) -> HeadlessResult:
    """Reserve once; inspect, query account, launch once, then retain a terminal receipt."""
    deployment = None if deployment is None else checked_headless_train_deployment(deployment)
    context = {k: str(_plain(v)) for k, v in dict(executable=executable, cwd=cwd,
        private_home=private_home, private_profile=private_profile).items()}
    if deployment is not None:
        _require(context['executable'] == deployment.executable, 'headless deployment executable binding')
        context['native_deployment'] = deployment.record.data()
    if reasoning_effort is not None:
        context['reasoning_effort'] = reasoning_effort
    native = _plain(private_dir); reservation_path = _plain(reservation)
    home, user = Path(context['private_home']), Path(context['private_profile'])
    _require(type(prompt) is str and isinstance(schema, dict), 'headless request shape')
    _require(type(main_output_cap) is int and main_output_cap > 0
        and type(observed_main_token_cap) is int and observed_main_token_cap >= main_output_cap
        and type(input_byte_cap) is int and 0 < len(prompt.encode()) <= input_byte_cap
        and type(timeout) in (int, float) and 0 < timeout <= 240, 'headless request bounds')
    _require(reasoning_effort is None or reasoning_effort in ALLOWED_REASONING_EFFORTS,
        'unsupported headless reasoning effort')
    recovery = _recovery(account_read_recovery)
    if recovery:
        context['account_read_recovery'] = recovery
    expected_sha = EXECUTABLE_SHA256 if deployment is None else deployment.record.data()['executable_sha256']
    _require(_sha(_read(Path(context['executable']))) == expected_sha, 'headless executable pin')
    _require(home.is_dir() and {p.name for p in home.iterdir()} == {'auth.json', 'config.toml'}
        and (home / 'auth.json').is_file()
        and _read(home / 'config.toml') == diagnostic_config(main_output_cap).encode(), 'fresh native home')
    for path in (Path(context['cwd']), user):
        _require(path.is_dir() and not any(path.iterdir()), 'fresh native context')
    _require(reservation_path == native.parent / 'native-reservation.json', 'reservation location')
    if deployment is not None:
        _require(all(frozen_files.get(path) == digest for path, digest in deployment.source_pins().items()),
                 'headless deployment source manifest')
    _sources(frozen_files)
    native.mkdir(parents=True, exist_ok=False)
    for path in (context['executable'], str(home / 'config.toml')):
        _require(frozen_files.get(path) == _sha(_read(Path(path))), 'native source not frozen')
    environment = _fresh_env(home, user)
    session = str(uuid.uuid4()); prompt_raw = prompt.encode(); schema_raw = _canon(schema)
    command = _command(context, native, session, schema, reasoning_effort)
    bound = {'schema': RECOVERY_RESERVATION_SCHEMA if recovery else 'grok-headless-reservation-v1', 'session_id': session, 'context': context,
        'environment': environment, 'prompt_sha256': _sha(prompt_raw), 'schema_digest': _sha(schema_raw),
        'input_bytes': len(prompt_raw), 'input_byte_cap': input_byte_cap,
        'main_output_cap': main_output_cap, 'observed_main_token_cap': observed_main_token_cap,
        'reasoning_effort': reasoning_effort,
        'timeout_seconds': timeout, 'frozen_files': frozen_files, 'retries': 0,
        'account_prelaunch_max_age_seconds': ACCOUNT_PRELAUNCH_MAX_AGE_SECONDS,
        'reserved_at': datetime.now(timezone.utc).isoformat(), 'command': command,
        'inspect_command': _inspect_command(context), 'inspect_timeout_seconds': 10,
        **({'account_read_recovery': recovery} if recovery else {})}
    # The exclusive file, with fsync, is the no-retry anchor before ANY process or GET.
    with reservation_path.open('xb') as out:
        out.write(_canon(bound)); out.flush(); os.fsync(out.fileno())
    _write(native / 'prompt.private.txt', prompt_raw); _write(native / 'schema.private.json', schema_raw)
    _write(native / 'command.json', command)
    receipt = {'schema': RECOVERY_RECEIPT_SCHEMA if recovery else RECEIPT_SCHEMA, 'accepted': False, 'faults': [],
        'reservation_sha256': _sha(_canon(bound)), 'context': context,
        'prompt_sha256': bound['prompt_sha256'], 'schema_digest': bound['schema_digest'],
        'input_bytes': len(prompt_raw), 'requested_model': MODEL,
        'requested_reasoning_effort': reasoning_effort, 'frozen_files': frozen_files,
        'inspect_process': None, 'native_process': None, 'stream_inspection': None,
        'account_preflight': None, 'account_postflight': None, 'prompt_process_launched': False,
        'response_sha256': None, 'initial_title_usage': None, 'all_opportunity_usage': None,
        'billing_settlement': 'not_established_by_headless_receipt', 'output_cap_wire_certified': False,
        **({'account_read_recovery': recovery} if recovery else {})}
    response = None; stage = 'context_inspection'
    try:
        raw, receipt['inspect_process'] = _child(bound['inspect_command'], context, environment, native/'inspect', 10)
        _require(_process_ok(receipt['inspect_process']), 'context inspection process failed')
        _inspect(raw, deployment)
        version = None if deployment is None else deployment.account_client_version
        stage = 'account_preflight'
        if recovery:
            pre = (_account_recovered(home, native/'billing-before', recovery) if deployment is None
                   else _account_recovered(home, native/'billing-before', recovery, client_version=version))
        else:
            pre = (_account(home, native/'billing-before') if deployment is None
                   else _account(home, native/'billing-before', client_version=version))
        receipt['account_preflight'] = pre['projection'] if recovery else pre
        if recovery: receipt['account_preflight_attempts_sha256'] = _sha(_read(native/'billing-before/attempts.json'))
        stage = 'prelaunch_guard'; _sources(frozen_files)
        age = (datetime.now(timezone.utc)-_instant(receipt['account_preflight']['oldest_observed_at'])).total_seconds()
        _require(0 <= age <= bound['account_prelaunch_max_age_seconds'], 'account snapshot stale')
        stage = 'prompt_process'
        raw, process = _child(command, context, environment, native, timeout)
        receipt['native_process'] = process; receipt['prompt_process_launched'] = process['launched']
        inspection = inspect_grok_stream(raw, schema=schema, session_id=session,
            max_output_tokens=main_output_cap, max_total_tokens=observed_main_token_cap,
            process_exit_code=process['process_exit_code'] if type(process['process_exit_code']) is int else -1)
        receipt['stream_inspection'] = inspection.receipt.data()
        receipt['faults'].extend(inspection.receipt.data()['faults'])
        if not _process_ok(process): receipt['faults'].append('prompt_process_failed')
        if inspection.response is not None:
            response = inspection.response
            receipt['response_sha256'] = _write(native/'response.private.json', response.data())
        stage = 'account_postflight'
        if recovery:
            post = (_account_recovered(home, native/'billing-after', recovery) if deployment is None
                    else _account_recovered(home, native/'billing-after', recovery, client_version=version))
        else:
            post = (_account(home, native/'billing-after') if deployment is None
                    else _account(home, native/'billing-after', client_version=version))
        receipt['account_postflight'] = post['projection'] if recovery else post
        if recovery: receipt['account_postflight_attempts_sha256'] = _sha(_read(native/'billing-after/attempts.json'))
        _require(receipt['account_preflight']['account_binding'] == receipt['account_postflight']['account_binding'],
            'account identity changed')
        stage = 'post_response_source_guard'; _sources(frozen_files)
    except Exception:
        if recovery:
            for phase, field in (('billing-before','account_preflight_attempts_sha256'), ('billing-after','account_postflight_attempts_sha256')):
                attempts = native/phase/'attempts.json'
                if attempts.exists(): receipt[field] = _sha(_read(attempts))
        receipt['faults'].append(stage + '_failed')
    receipt['accepted'] = not receipt['faults'] and response is not None
    _write(native/'observer-receipt.json', receipt)
    # Return the persisted canonical bytes, so the producer and independent reader
    # share one receipt object even for the recovery branch.
    persisted = _strict_json(_read(native/'observer-receipt.json'))
    return HeadlessResult(FrozenRecord.from_dict(persisted), response if persisted['accepted'] else None)


def _reread_process(directory, expected_command, bound, timeout):
    process = _strict_json(_read(directory/'process.json'))
    raw = _read(directory/'stdout.private.jsonl'); error = _read(directory/'stderr.private.txt')
    _require(process['command'] == expected_command and process['environment'] == bound['environment']
        and process['cwd'] == bound['context']['cwd'] and process['timeout_seconds'] == timeout
        and process['stdout_sha256'] == _sha(raw) and process['stderr_sha256'] == _sha(error),
        'native process binding')
    _require(_instant(bound['reserved_at']) <= _instant(process['started_at']) <= _instant(process['finished_at']),
        'native process chronology')
    return raw, process


def _reread_account(folder, *, client_version=None):
    saved = _strict_json(_read(folder/'observation.json'))
    rows = _strict_json(_read(folder/'requests.json'))
    rebuilt = _project_account({key: _read(folder/(key+'.private.json')) for key, _ in ACCOUNT_ROUTES},
        rows, saved['observed_at'], client_version=client_version)
    _require(rebuilt == saved, 'account projection binding')
    return rebuilt


def _reread_recovered_account(folder, recovery, *, client_version=None):
    manifest = _strict_json(_read(folder/'attempts.json')); recovery = _recovery(recovery)
    _require(manifest.get('schema') == ACCOUNT_RECOVERY_SCHEMA and manifest.get('recovery') == recovery,
             'account recovery manifest binding')
    attempts=manifest.get('attempts'); winner=manifest.get('winning_attempt')
    _require(isinstance(attempts,list) and 1 <= len(attempts) <= recovery['max_attempts']
             and [a.get('index') for a in attempts] == list(range(len(attempts))), 'account recovery order')
    accepted=[]; previous_time=None
    for row in attempts:
        path=folder/f"attempt-{row['index']:03d}"
        if row.get('status') == 'accepted':
            _require(row.get('requests_sha256') == _sha(_read(path/'requests.json')), 'account recovery requests binding')
            projection=_reread_account(path, client_version=client_version); _require(row.get('projection_sha256') == _sha(_read(path/'observation.json')), 'account recovery projection')
            _require(previous_time is None or previous_time <= _instant(projection['oldest_observed_at']),
                     'account recovery chronology')
            accepted.append((row['index'],projection))
        else:
            _require(row.get('requests_sha256') == _sha(_read(path/'requests.json')), 'account recovery requests binding')
            failure=_strict_json(_read(path/'failure.json')); rows=_strict_json(_read(path/'requests.json'))
            _require(row.get('status') in {'transient_failed','terminal_failed'} and row.get('failure_sha256') == _sha(_read(path/'failure.json'))
                     and ((row.get('status') == 'transient_failed' and failure.get('route') in {n for n,_ in ACCOUNT_ROUTES} and failure.get('error_class') in {'HTTPError','URLError','TimeoutError'})
                          or (row.get('status') == 'terminal_failed' and failure.get('route') in {n for n,_ in ACCOUNT_ROUTES} and failure.get('error_class') == 'ContractError')), 'account recovery failure binding')
            _require(isinstance(rows,list) and rows and [r.get('name') for r in rows] == [n for n,_ in ACCOUNT_ROUTES[:len(rows)]]
                     and all(r.get('method') == 'GET' and r.get('url') == PROXY + ACCOUNT_ROUTES[i][1]
                             and r.get('status') in {'received','failed'} and isinstance(r.get('started_at'),str)
                             and (client_version is None or r.get('client_version') == client_version)
                             for i,r in enumerate(rows)), 'account recovery partial order')
            last=rows[-1]
            _require((row.get('status') == 'transient_failed' and last.get('status') == 'failed'
                      and failure.get('route') == last.get('name') and failure.get('error_class') == last.get('error_class')
                      and failure.get('http_status') == last.get('http_status')
                      and (failure.get('error_class') != 'HTTPError' or failure.get('http_status') in (429,502,503,504))), 'account recovery terminal row binding')
            for request in rows:
                if request.get('status') == 'received':
                    raw=_read(path/(request['name']+'.private.json'))
                    _require(request.get('sha256') == _sha(raw) and request.get('bytes') == len(raw), 'account recovery raw binding')
                started, received = _instant(request.get('started_at')), _instant(request.get('received_at'))
                _require(started <= received and (previous_time is None or previous_time <= started),
                         'account recovery chronology')
                previous_time = received
            failed_at = _instant(failure.get('failed_at'))
            _require(previous_time <= failed_at, 'account recovery chronology')
            previous_time = failed_at
    _require(len(accepted) == 1 and winner == accepted[0][0] and winner == len(attempts)-1
             and all(a.get('status') == 'transient_failed' for a in attempts[:winner])
             and manifest.get('projection') == accepted[0][1], 'account recovery winner binding')
    return accepted[0][1]


def verify_headless_request_binding(result, entry, directory, spec, frozen_files, *, deployment=None) -> FrozenRecord:
    try:
        return _verify_headless_request_binding(result, entry, directory, spec, frozen_files, deployment=deployment)
    except ContractError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ContractError('malformed headless binding artifact') from exc


def _verify_headless_request_binding(result, entry, directory, spec, frozen_files, *, deployment=None) -> FrozenRecord:
    """Reread trusted request, reservation, runtime, streams and all six account GETs."""
    deployment = None if deployment is None else checked_headless_train_deployment(deployment)
    _require(type(result) is HeadlessResult and type(result.receipt) is FrozenRecord, 'headless result required')
    native = _plain(directory)/'native'; persisted = _strict_json(_read(native/'observer-receipt.json'))
    _require(FrozenRecord.from_dict(persisted) == result.receipt, 'headless observer binding')
    receipt = persisted
    if deployment is not None:
        _require(all(frozen_files.get(path) == digest for path, digest in deployment.source_pins().items()),
                 'headless deployment source manifest')
    _sources(frozen_files)
    bound_raw = _read(Path(directory)/'native-reservation.json'); bound = _strict_json(bound_raw)
    recovery = spec.get('account_read_recovery')
    _require(_sha(bound_raw) == receipt['reservation_sha256'] and bound['schema'] == (RECOVERY_RESERVATION_SCHEMA if recovery else 'grok-headless-reservation-v1')
        and bound['retries'] == 0 and bound['frozen_files'] == frozen_files == receipt['frozen_files'],
        'headless reservation binding')
    _require((recovery is None and 'account_read_recovery' not in bound and receipt['schema'] == RECEIPT_SCHEMA)
             or (recovery is not None and _recovery(recovery) == bound.get('account_read_recovery') == receipt.get('account_read_recovery')
                 and receipt['schema'] == RECOVERY_RECEIPT_SCHEMA), 'account recovery contract binding')
    expected_effort = spec.get('reasoning_effort')
    context = bound['context']
    _require(context.get('reasoning_effort') == expected_effort
        and spec['native_context'].get('reasoning_effort') == expected_effort
        and bound.get('reasoning_effort') == expected_effort
        and receipt.get('requested_reasoning_effort') == expected_effort
        and (expected_effort is None or expected_effort in ALLOWED_REASONING_EFFORTS),
        'native reasoning effort binding')
    _require(context == spec['native_context'] == receipt['context'], 'native deployment binding')
    if deployment is None:
        _require('native_deployment' not in context, 'legacy native deployment binding')
    else:
        _require(context.get('native_deployment') == deployment.record.data(), 'versioned native deployment binding')
    for key in ('executable', 'cwd', 'private_home', 'private_profile'): _plain(context[key])
    expected_sha = EXECUTABLE_SHA256 if deployment is None else deployment.record.data()['executable_sha256']
    _require(_sha(_read(Path(context['executable']))) == expected_sha, 'headless executable pin')
    config_path = str(Path(context['private_home'])/'config.toml')
    _require(frozen_files.get(context['executable']) == expected_sha
        and frozen_files.get(config_path) == _sha(diagnostic_config(spec['main_output_cap']).encode()),
        'native configuration binding')
    for key in ('main_output_cap', 'observed_main_token_cap', 'timeout_seconds'):
        _require(bound[key] == spec[key], 'native bounds binding')
    _require(bound['input_byte_cap'] == spec['max_input_bytes'], 'native input cap binding')
    descriptor = entry['private_request']
    private_raw = _read(_plain(descriptor['path']))
    _require(set(descriptor) == {'path', 'sha256'} and _sha(private_raw) == descriptor['sha256']
        and frozen_files.get(descriptor['path']) == descriptor['sha256'], 'private request descriptor binding')
    private = _strict_json(private_raw)
    _require(set(private) == {'prompt', 'output_schema'}, 'private request shape')
    prompt, schema = private['prompt'], private['output_schema']
    request = {'prompt_sha256': _sha(prompt.encode()), 'schema_digest': _sha(_canon(schema)),
        'input_bytes': len(prompt.encode())}
    for key, value in request.items():
        _require(value == bound[key] == receipt[key] == entry[key], 'private request binding')
    _require(request['input_bytes'] <= spec['max_input_bytes']
        and _read(native/'prompt.private.txt') == prompt.encode()
        and _read(native/'schema.private.json') == _canon(schema), 'native request bytes binding')
    _require(bound['command'] == _command(context, native, bound['session_id'], schema, expected_effort)
        == _strict_json(_read(native/'command.json')) and bound['inspect_command'] == _inspect_command(context)
        and bound['inspect_timeout_seconds'] == 10, 'native command contract')
    # Rebuild environment from the recorded non-secret OS values; ambient caller
    # variables are not an authority for historical replay.
    fixed = {'GROK_HOME': context['private_home'], 'USERPROFILE': context['private_profile'],
        'HOME': context['private_profile'], 'GROK_DISABLE_API_KEY_AUTH': '1', 'GROK_DISABLE_AUTOUPDATER': '1',
        'GROK_TITLE_REFRESH': 'false', 'GROK_TURN_SUMMARY': 'false', 'GROK_MEMORY': 'false',
        'GROK_WORKFLOWS': 'false', 'GROK_SUBAGENTS': 'false'}
    profile_path = Path(context['private_profile'])
    fixed.update(APPDATA=str(profile_path/'AppData'/'Roaming'), LOCALAPPDATA=str(profile_path/'AppData'/'Local'),
        TEMP=str(profile_path/'temp'), TMP=str(profile_path/'temp'), HOMEDRIVE=profile_path.drive,
        HOMEPATH=str(profile_path)[len(profile_path.drive):])
    allowed_os = {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'PATH',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS'}
    _require(all(bound['environment'].get(k) == v for k, v in fixed.items())
        and all(k in fixed or k.upper() in allowed_os for k in bound['environment']), 'native environment binding')
    raw, inspect_process = _reread_process(native/'inspect', bound['inspect_command'], bound, 10)
    _require(inspect_process == receipt['inspect_process'] and _process_ok(inspect_process), 'native inspect rejected')
    _inspect(raw, deployment)
    raw, process = _reread_process(native, bound['command'], bound, spec['timeout_seconds'])
    _require(process == receipt['native_process'] and receipt['prompt_process_launched'] == process['launched'],
        'native process receipt binding')
    inspected = inspect_grok_stream(raw, schema=schema, session_id=bound['session_id'],
        max_output_tokens=spec['main_output_cap'], max_total_tokens=spec['observed_main_token_cap'],
        process_exit_code=process['process_exit_code'] if type(process['process_exit_code']) is int else -1)
    _require(inspected.receipt.data() == receipt['stream_inspection'], 'native stream inspection binding')
    if receipt['accepted']:
        _require(inspected.response is not None and result.response == inspected.response
            and receipt['response_sha256'] == _sha(_read(native/'response.private.json'))
            and _strict_json(_read(native/'response.private.json')) == inspected.response.data(), 'native response binding')
    else:
        _require(result.response is None, 'rejected native response exposed')
    version = None if deployment is None else deployment.account_client_version
    reread = _reread_recovered_account if recovery else _reread_account
    if recovery:
        _require(receipt.get('account_preflight_attempts_sha256') == _sha(_read(native/'billing-before/attempts.json'))
                 and receipt.get('account_postflight_attempts_sha256') == _sha(_read(native/'billing-after/attempts.json')), 'account attempts receipt binding')
    pre = reread(native/'billing-before', recovery, client_version=version) if recovery else reread(native/'billing-before', client_version=version)
    post = reread(native/'billing-after', recovery, client_version=version) if recovery else reread(native/'billing-after', client_version=version)
    _require(pre == receipt['account_preflight'] and post == receipt['account_postflight']
        and pre['account_binding'] == post['account_binding'], 'native account binding')
    _require(_instant(inspect_process['finished_at']) <= _instant(pre['oldest_observed_at'])
        <= _instant(pre['observed_at']) <= _instant(process['started_at'])
        <= _instant(process['finished_at']) <= _instant(post['oldest_observed_at']), 'native account chronology')
    _require(type(bound.get('account_prelaunch_max_age_seconds')) is int
        and bound['account_prelaunch_max_age_seconds'] == ACCOUNT_PRELAUNCH_MAX_AGE_SECONDS
        and 0 <= (_instant(process['started_at'])-_instant(pre['oldest_observed_at'])).total_seconds()
        <= bound['account_prelaunch_max_age_seconds'], 'oldest account observation stale')
    events = [_strict_json(line) for line in raw.splitlines() if line.strip()]
    ends = [row for row in events if row.get('type') == 'end']
    request_id = ends[0].get('requestId') if len(ends) == 1 else None
    accepted = (receipt['accepted'] is True and receipt['faults'] == []
        and inspected.receipt.data()['accepted'] is True and _process_ok(process))
    observed = inspected.receipt.data()
    return FrozenRecord.from_dict({'schema': 'grok-headless-request-binding-v1', 'accepted': accepted,
        'opportunity_id': entry['opportunity_id'], 'request': request, 'context': context,
        'identity': {'requested_model': MODEL, 'requested_reasoning_effort': expected_effort,
            'accounting_model': observed['accounting_model'],
            'session_id': bound['session_id'], 'request_id': request_id},
        'usage': {'main': observed['usage'], 'main_model_calls': observed['reported_main_model_calls'],
            'num_turns': ends[0].get('num_turns') if len(ends) == 1 else None,
            'initial_title': None, 'all_opportunities': None},
        'account': {'preflight': pre, 'postflight': post, 'oldest_observed_at': pre['oldest_observed_at']},
        'faults': receipt['faults']})
