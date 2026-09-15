"""Archive full4 only after the observer confirms the pytest process joined.

This helper never follows reparse points and excludes credential-shaped files.
It records post-run source state only: no pre-run source manifest exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import stat
import zipfile

WORK = Path(r"E:\_ryanDev\AI\research-loop-modular\work")
ROOT = WORK / "headless-lineage-controller-full4-pytest" / "test_native_v4_headless_lineag0"
REPO = Path(r"E:\_ryanDev\AI\research-loop-modular\headless-lineage-controller")
OUT = WORK / "headless-lineage-controller-full4-archive-r1"
PRIVATE_OUT = Path(r"E:\_ryanDev\AI\research-loop-modular\retained-private-evidence\headless-lineage-controller-full4-r1")
COMMIT = "051b6a82a2f0b61d17b88a419a190652a71b424a"
PID = 54260
CREATED_AT = '2026-09-15T02:00:29.990017+00:00'
EXCLUDED_PARTS = {"auth.json", "*.key", "credential/secret/authority named files"}
EXCLUSIONS = {}
PRUNED_LINKS = set()
PUBLIC_NAMES = {"controller-attempt.json", "controller-receipt.json", "final-provider-ledger.json", "report-provider-ledger.json"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def excluded(path: Path) -> bool:
    name = path.name.lower()
    # Account observations and token usage are provenance, not credentials.
    return (name == 'auth.json' or path.suffix.lower() == '.key'
            or any(word in name for word in ('credential', 'secret', 'authority')))


def regular_files(root: Path):
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        safe_dirs = []
        for name in dirs:
            candidate = current_path / name
            attrs = os.stat(candidate, follow_symlinks=False).st_file_attributes
            if not (attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
                safe_dirs.append(name)
            else:
                PRUNED_LINKS.add(str(candidate))
        dirs[:] = safe_dirs
        for name in files:
            path = current_path / name
            attrs = os.stat(path, follow_symlinks=False).st_file_attributes
            if attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                PRUNED_LINKS.add(str(path))
                continue
            if excluded(path.relative_to(root)):
                details = path.stat()
                EXCLUSIONS[str(path)] = {'bytes': details.st_size, 'mtime_ns': details.st_mtime_ns}
                continue
            yield path


def add_zip(zip_path: Path, rows):
    members = []
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, raw, origin in rows:
            archive.writestr(arcname, raw)
            members.append({"path": arcname, "sha256": sha(raw), "byte_count": len(raw), "origin": origin})
    return members


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-joined", action="store_true", help="required after the root observer confirms PID termination")
    parser.add_argument("--join-receipt", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm_joined:
        raise SystemExit("refusing archival before --confirm-joined")
    receipt = json.loads(args.join_receipt.read_text(encoding='utf-8'))
    if (receipt.get('pid') != PID or receipt.get('created_at') != CREATED_AT
            or receipt.get('process_signaled') is not True or receipt.get('observer_timeout') is not False
            or not isinstance(receipt.get('process_exit_code'), int)):
        raise SystemExit('observer receipt does not bind the joined full4 process')
    if not ROOT.is_dir():
        raise SystemExit(f"missing full4 root: {ROOT}")
    if OUT.exists() or PRIVATE_OUT.exists(): raise SystemExit('archive output already exists')
    OUT.mkdir(parents=True); PRIVATE_OUT.parent.mkdir(parents=True, exist_ok=True); os.mkdir(PRIVATE_OUT)
    source_rows = []
    tracked = subprocess.check_output(["git", "-C", str(REPO), "ls-files", "*.py", "*.md"], text=True).splitlines()
    for name in tracked:
        if name.startswith(('results/', 'data/')): continue
        path = REPO / name
        if path.is_file() and not path.is_symlink() and not (os.stat(path, follow_symlinks=False).st_file_attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            source_rows.append((f"source/{name}", path.read_bytes(), str(path)))
    source_members = add_zip(OUT / "source-exact.zip", source_rows)
    public_rows, private_rows = [], []
    originals = list(regular_files(ROOT))
    for stem in ('full', 'full2', 'full3', 'full4'):
        for suffix in ('.log', '.xml'):
            path = WORK / f'headless-lineage-controller-{stem}{suffix}'
            if path.is_file() and not path.is_symlink(): originals.append(path)
    before = {str(path): {'sha256': sha(path.read_bytes()), 'mtime_ns': path.stat().st_mtime_ns} for path in originals}
    for path in regular_files(ROOT):
        relative = path.relative_to(ROOT).as_posix(); raw = path.read_bytes()
        target = public_rows if path.name in PUBLIC_NAMES or path.suffix == '.xml' else private_rows
        target.append((f"full4/{relative}", raw, str(path)))
    # Preserve the three earlier failed invocation logs/JUnits when present.
    for stem in ("full", "full2", "full3"):
        for suffix in (".log", ".xml"):
            path = WORK / f"headless-lineage-controller-{stem}{suffix}"
            if path.is_file() and not path.is_symlink():
                (public_rows if suffix == '.xml' else private_rows).append((f"history/{path.name}", path.read_bytes(), str(path)))
    for suffix in ('.log', '.xml'):
        path = WORK / f'headless-lineage-controller-full4{suffix}'
        if path.is_file() and not path.is_symlink():
            (public_rows if suffix == '.xml' else private_rows).append((f'full4-external/{path.name}', path.read_bytes(), str(path)))
    public_rows.append(('observer/join-receipt.json', args.join_receipt.read_bytes(), str(args.join_receipt)))
    public_members = add_zip(OUT / "public-metadata.zip", public_rows)
    private_members = add_zip(PRIVATE_OUT / "retained-private.zip", private_rows)
    after = {str(path): {'sha256': sha(path.read_bytes()), 'mtime_ns': path.stat().st_mtime_ns} for path in originals}
    if before != after: raise SystemExit('original full4 bytes or mtimes changed during archival')
    status = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    manifest = {"schema": "headless-lineage-full4-archive-r1", "source_commit": COMMIT,
        "source_state": {"post_run_git_status_clean": status == "", "snapshot": "post_run_disk_bytes", "pre_run_source_manifest": "absent_not_claimed"},
        "run_root": str(ROOT), "pid_joined_before_archive": PID, "excluded": sorted(EXCLUDED_PARTS),
        "excluded_credential_files": EXCLUSIONS, "pruned_reparse_paths": sorted(PRUNED_LINKS),
        "original_files_before": before, "original_files_after": after,
        "source_members": source_members, "public_members": public_members, "retained_private_members": private_members,
        "archives": {"source-exact.zip": sha((OUT / "source-exact.zip").read_bytes()), "public-metadata.zip": sha((OUT / "public-metadata.zip").read_bytes()), "retained-private.zip": sha((PRIVATE_OUT / "retained-private.zip").read_bytes())}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archive_root": str(OUT), "manifest_sha256": sha((OUT / "manifest.json").read_bytes())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
