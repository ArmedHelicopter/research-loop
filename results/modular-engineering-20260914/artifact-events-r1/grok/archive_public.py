"""Validate and atomically prepare the safe public evidence subset."""
import hashlib
import json
import os
import shutil
from pathlib import Path

SRC = Path(__file__).parent.resolve()
DST = SRC.parent / "grok130-initialize-stdin-ab-public-r1"
STAGE = SRC.parent / "grok130-initialize-stdin-ab-public-r1.staging"

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def write(path, data): Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if DST.exists() or STAGE.exists():
    raise RuntimeError("public destination or staging directory already exists")
envelope = read(SRC / "envelope.json")
closure = read(SRC / "closure.json")
if closure["envelope_sha256"] != digest(SRC / "envelope.json"):
    raise RuntimeError("aggregate closure does not bind its envelope")
for filename, expected in envelope["frozen_files"].items():
    if digest(filename) != expected:
        raise RuntimeError("frozen source drift: " + filename)

variant_checks = {}
for name in ("A", "B"):
    private = SRC / name / "private"
    reservation = read(private / "reservation.json")
    public = read(private / "public-closure.json")
    safe = read(SRC / name / "safe-summary.json")
    aggregate = next(item for item in closure["variants"] if item["variant"] == name)
    if reservation["timeout_seconds"] != 60 or reservation["initialize_writes_max"] != 1:
        raise RuntimeError(name + " reservation limits differ")
    if reservation["source_manifest_sha256"] != hashlib.sha256(json.dumps(envelope["frozen_files"], sort_keys=True).encode()).hexdigest():
        raise RuntimeError(name + " reservation source manifest differs")
    for key in ("accepted_initialize", "faults", "initialize_writes_completed", "outbound_method_counts", "stdout_frames_parsed", "response", "native_exit_code_after_shutdown", "process_tree_closed", "stdout_bytes", "stderr_bytes", "known_model_usage", "settled_additional_charge_usd"):
        if not (public[key] == safe[key] == aggregate[key]):
            raise RuntimeError(name + " receipt mismatch: " + key)
    raw_stats = {leaf:(private / leaf).stat().st_size for leaf in ("stdout.private.bin", "stderr.private.bin")}
    if raw_stats["stdout.private.bin"] != public["stdout_bytes"] or raw_stats["stderr.private.bin"] != public["stderr_bytes"]:
        raise RuntimeError(name + " private stream stat mismatch")
    variant_checks[name] = {"private_stream_stats_only": raw_stats, "reservation_wire_sha256": reservation["wire_sha256"], "public_closure_sha256": digest(private / "public-closure.json"), "reservation_sha256": digest(private / "reservation.json")}

def normalized_config(name):
    base = str((SRC / name).resolve()).replace("\\", "/")
    text = (SRC / name / "home" / "config.toml").read_text(encoding="utf-8").replace("\\", "/")
    # Factory output quotes Windows paths with each separator doubled.
    return text.replace(base.replace("/", "//"), "<VARIANT>").replace(base, "<VARIANT>").replace("\r\n", "\n")
if normalized_config("A") != normalized_config("B"):
    raise RuntimeError("isolated configs differ beyond their own base paths")

items = [
    "driver.py", "init_engine.py", "eof_peer.py", "summarize_logs.py", "archive_public.py",
    "envelope.json", "closure.json", "synthetic-helper.json", "allowlisted-log-summary.json", "RESULT.md",
    "A/safe-summary.json", "B/safe-summary.json", "A/private/reservation.json", "B/private/reservation.json",
    "A/private/public-closure.json", "B/private/public-closure.json",
]
for relative in items:
    if not (SRC / relative).is_file(): raise RuntimeError("required evidence missing: " + relative)

STAGE.mkdir()
for relative in items:
    source, target = SRC / relative, STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
scope = """# Scope\n\nThis directory is a public, byte-checked subset of the closed stdin-held versus EOF initialize-only diagnostic. It excludes every home/profile directory, auth file, private stdout/stderr/request streams, model material, and credentials. The two copied `public-closure.json` and `reservation.json` files are safe protocol receipts, not streams.\n\nThe driver had three pre-native repair events: an initial import-path error before the synthetic control; then `isolated_config(profile=...)` raised a signature error after the successful synthetic control and before entry to the native launch loop; then recreation of that empty A directory raised `FileExistsError`, also before the loop. The driver was repaired to add the integration import path, use `user=`, and tolerate that known-empty directory. Those terminal exceptions were not persisted as files at the time, so this statement preserves their known history but cannot independently reproduce their transcript. The completed aggregate closure is the evidence that exactly two subsequent native launches occurred.\n\nIntegrity limits: frozen digests prove the listed local code/config/exe bytes at native launch boundaries. They do not establish a root cause, service-side behavior, authentication validity, usage settlement, or scientific/model validity. Settlement remains unknown.\n"""
(STAGE / "SCOPE.md").write_text(scope, encoding="utf-8")
manifest = {"schema":"grok130-initialize-stdin-ab-public-manifest-v1", "source_closure_sha256":digest(SRC / "closure.json"), "envelope_sha256":digest(SRC / "envelope.json"), "frozen_files_verified":len(envelope["frozen_files"]), "normalized_configs_equal_except_variant_base":True, "variant_checks":variant_checks, "items":[]}
for path in sorted(STAGE.rglob("*")):
    if path.is_file(): manifest["items"].append({"path":str(path.relative_to(STAGE)).replace("\\", "/"), "bytes":path.stat().st_size, "sha256":digest(path)})
write(STAGE / "manifest.json", manifest)
for item in manifest["items"]:
    if digest(STAGE / item["path"]) != item["sha256"]: raise RuntimeError("archive copy digest mismatch")
os.replace(STAGE, DST)
print(json.dumps({"destination":str(DST), "files":len(manifest["items"]), "manifest_sha256":digest(DST / "manifest.json")}, sort_keys=True))
