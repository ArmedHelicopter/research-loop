"""Read-only verification for the closed c5-common-digest-r1 archive."""
from __future__ import annotations
import hashlib, json, subprocess, zipfile
from pathlib import Path
BASE=Path(r'E:/_ryanDev/AI/research-loop-modular'); WORK=BASE/'work'
PREFIX=WORK/'c5-common-digest-r1'; STAGE=WORK/'c5-common-digest-r1-archive-stage-r1'
PRIVATE=BASE/'retained-private-evidence/c5-common-digest-r1-runtime-r1'; SOURCE=BASE/'immutable-record-runtime'
def sha_path(p):
    with p.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
members=load(PRIVATE/'runtime-members.json'); pm=load(PRIVATE/'private-manifest.json'); sm=load(STAGE/'manifest.json')
by={}
for row in members: by.setdefault(row['archive'],[]).append(row)
if len(members)!=13516 or len(by)!=32: raise SystemExit('private member/archive count mismatch')
for name, rows in by.items():
    path=PRIVATE/name
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None or set(z.namelist())!={r['path'] for r in rows}:raise SystemExit('zip listing mismatch '+name)
        for r in rows:
            raw=z.read(r['path']); original=PREFIX/r['path']; stat=original.stat()
            if sha(raw)!=r['sha256'] or len(raw)!=r['bytes'] or sha_path(original)!=r['sha256'] or stat.st_mtime_ns!=r['mtime_ns']:
                raise SystemExit('original mismatch '+r['path'])
expected_private={p.name:{'bytes':p.stat().st_size,'sha256':sha_path(p)} for p in PRIVATE.iterdir() if p.is_file() and p.name!='private-manifest.json'}
if pm!=expected_private:raise SystemExit('private manifest mismatch')
expected_stage={p.name for p in STAGE.iterdir() if p.is_file()}
if set(sm['public_file_names'])!=expected_stage or not sm['manifest_self_excluded_from_hashes']:raise SystemExit('stage name set mismatch')
for row in sm['files']:
    p=STAGE/row['path']
    if not p.exists() or p.stat().st_size!=row['bytes'] or sha_path(p)!=row['sha256']:raise SystemExit('stage manifest mismatch '+row['path'])
if subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE).strip():raise SystemExit('source worktree no longer clean')
if subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()!='105dfcd321faa3245b9a1605515e1eb147d04c5f':raise SystemExit('source commit drift')
print(json.dumps({'verified':True,'runtime_members':len(members),'runtime_archives':len(by),'runtime_bytes':sum(r['bytes'] for r in members),'stage_manifest_sha256':sha_path(STAGE/'manifest.json'),'private_manifest_sha256':sha_path(PRIVATE/'private-manifest.json'),'source_clean':True},sort_keys=True))
