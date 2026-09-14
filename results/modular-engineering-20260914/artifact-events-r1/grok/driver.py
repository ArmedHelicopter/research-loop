"""Bounded stdin-held versus EOF initialize-only diagnostic."""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
INTEGRATION = ROOT.parent.parent / "integration"
EXE = ROOT.parent / "grok-cli-1.0.30" / "grok.exe"
AUTH = Path("C:/Users/Administrator/.grok/auth.json")
PIN = "ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266"
sys.path.insert(0, str(INTEGRATION))

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def metadata(path):
    stat = Path(path).stat()
    return {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def private_env(home, profile):
    keep = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"}
    result = {k:v for k,v in os.environ.items() if k.upper() in keep}
    result.update({"GROK_HOME":str(home), "USERPROFILE":str(profile), "HOME":str(profile), "HOMEDRIVE":profile.drive, "HOMEPATH":str(profile)[len(profile.drive):], "APPDATA":str(profile/"AppData/Roaming"), "LOCALAPPDATA":str(profile/"AppData/Local"), "TEMP":str(profile/"temp"), "TMP":str(profile/"temp"), "GROK_DISABLE_AUTOUPDATER":"1", "GROK_TITLE_REFRESH":"false", "GROK_TURN_SUMMARY":"false", "GROK_MEMORY":"false", "GROK_WORKFLOWS":"false", "GROK_SUBAGENTS":"false"})
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP"): Path(result[key]).mkdir(parents=True, exist_ok=True)
    return result

permitted = {"driver.py", "init_engine.py", "eof_peer.py", "__pycache__", "synthetic", "synthetic-helper.json", "A"}
unexpected = {p.name for p in ROOT.iterdir()} - permitted
if unexpected: raise RuntimeError("diagnostic directory was not fresh: " + ", ".join(sorted(unexpected)))
spec = importlib.util.spec_from_file_location("init_engine", ROOT / "init_engine.py")
engine = importlib.util.module_from_spec(spec); spec.loader.exec_module(engine)
if sha(EXE) != PIN: raise RuntimeError("pinned executable digest mismatch")

# Prove helper behavior before either of its two allowed native launches.
synthetic = ROOT / "synthetic"
helper_receipt = ROOT / "synthetic-helper.json"
if helper_receipt.exists():
    # A prior pre-native run reached this checkpoint before a local driver
    # signature error.  Reuse only the public receipt; no native process ran.
    prior = json.loads(helper_receipt.read_text(encoding="utf-8"))
    if prior != {"schema":"eof-dependent-peer-v1", "held_stdin":{"accepted_initialize":False, "faults":["timeout"], "process_tree_closed":True}, "closed_stdin":{"accepted_initialize":True, "faults":[], "process_tree_closed":True}}:
        raise RuntimeError("prior synthetic receipt is not the expected control")
else:
    for leaf in ("cwd", "profile", "home"): (synthetic / leaf).mkdir(parents=True)
    synthetic_frozen = {str((ROOT / "init_engine.py").resolve()):sha(ROOT / "init_engine.py"), str((ROOT / "eof_peer.py").resolve()):sha(ROOT / "eof_peer.py")}
    synthetic_a = engine.run_once([sys.executable, str(ROOT / "eof_peer.py")], cwd=synthetic / "cwd", env=private_env(synthetic / "home", synthetic / "profile"), directory=synthetic / "A-private", frozen_files=synthetic_frozen, timeout=1, close_stdin=False)
    synthetic_b = engine.run_once([sys.executable, str(ROOT / "eof_peer.py")], cwd=synthetic / "cwd", env=private_env(synthetic / "home", synthetic / "profile"), directory=synthetic / "B-private", frozen_files=synthetic_frozen, timeout=1, close_stdin=True)
    if synthetic_a["accepted_initialize"] or not synthetic_b["accepted_initialize"] or not synthetic_a["process_tree_closed"] or not synthetic_b["process_tree_closed"]: raise RuntimeError("synthetic EOF control did not prove helper behavior")
    write_json(helper_receipt, {"schema":"eof-dependent-peer-v1", "held_stdin":{"accepted_initialize":synthetic_a["accepted_initialize"], "faults":synthetic_a["faults"], "process_tree_closed":synthetic_a["process_tree_closed"]}, "closed_stdin":{"accepted_initialize":synthetic_b["accepted_initialize"], "faults":synthetic_b["faults"], "process_tree_closed":synthetic_b["process_tree_closed"]}})

# Same isolated factory config and opaque authentication copy for both variants.
from research_loop.modular.grok_skill_isolation import isolated_config
native = {}
for name in ("A", "B"):
    base = ROOT / name; home, profile, cwd = base / "home", base / "profile", base / "cwd"
    for path in (home, profile, cwd): path.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(isolated_config(cwd=cwd, home=home, user=profile), encoding="utf-8")
    shutil.copyfile(AUTH, home / "auth.json")
    native[name] = {"base":base, "home":home, "profile":profile, "cwd":cwd}

transport = INTEGRATION / "research_loop/modular/grok_acp_transport.py"
isolation = INTEGRATION / "research_loop/modular/grok_skill_isolation.py"
frozen_paths = [ROOT / "driver.py", ROOT / "init_engine.py", ROOT / "eof_peer.py", transport, isolation, EXE] + [native[n]["home"] / "config.toml" for n in ("A", "B")]
frozen = {str(path.resolve()):sha(path) for path in frozen_paths}
envelope = {"schema":"grok130-initialize-stdin-ab-envelope-v1", "executable_sha256":PIN, "frozen_files":frozen, "global_auth_contents_read_or_hashed":False, "native_launches_exactly":2, "native_launch_order":["A-held-stdin", "B-close-stdin-after-write"], "per_launch_wall_timeout_seconds":60, "outbound_method_limits":{"initialize":1, "session/new":0, "prompt":0, "authenticate":0, "billing":0}, "retry_count":0, "only_intended_difference":"stdin_closed_immediately_after_the_single_initialize_write"}
write_json(ROOT / "envelope.json", envelope); envelope_digest = sha(ROOT / "envelope.json")

global_auth_before = metadata(AUTH); safe_variants = []
for name, close_stdin in (("A", False), ("B", True)):
    item = native[name]
    result = engine.run_once([str(EXE), "--cwd", str(item["cwd"]), "agent", "stdio"], cwd=item["cwd"], env=private_env(item["home"], item["profile"]), directory=item["base"] / "private", frozen_files=frozen, timeout=60, close_stdin=close_stdin)
    config_path = item["home"] / "config.toml"
    safe = {key:result[key] for key in ("accepted_initialize", "faults", "initialize_writes_completed", "outbound_method_counts", "stdout_frames_parsed", "response", "elapsed_seconds", "process_tree_closed", "native_exit_code_after_shutdown", "stdout_bytes", "stderr_bytes", "known_model_usage", "settled_additional_charge_usd")}
    safe.update({"variant":name, "stdin_closed_after_write":close_stdin, "config_unchanged":sha(config_path) == frozen[str(config_path.resolve())], "envelope_sha256":envelope_digest})
    write_json(item["base"] / "safe-summary.json", safe); safe_variants.append(safe)
global_auth_after = metadata(AUTH)
closure = {"schema":"grok130-initialize-stdin-ab-closure-v1", "synthetic_helper":json.loads((ROOT / "synthetic-helper.json").read_text(encoding="utf-8")), "envelope_sha256":envelope_digest, "global_auth_metadata_unchanged":global_auth_before == global_auth_after, "auth_contents_read_or_hashed":False, "variants":safe_variants, "native_launches":2, "model_calls":0, "session_new_writes":0, "prompt_writes":0, "authenticate_writes":0, "billing_writes":0, "retry_count":0, "settled_additional_charge_usd":None, "settlement_status":"unknown"}
write_json(ROOT / "closure.json", closure)
print(json.dumps({"closure":str(ROOT / "closure.json"), "variants":safe_variants}, sort_keys=True))
