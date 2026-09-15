"""Read back preserved bytes and publish the incomplete full4 evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
WORK=BASE/'work'
STAGE=WORK/'headless-lineage-controller-full4-incomplete-archive-r1'
PRIVATE=BASE/'retained-private-evidence/headless-lineage-controller-full4-incomplete-r1'
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/headless-lineage-controller-full4-incomplete-r1'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def main():
    manifest=json.loads((STAGE/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='incomplete_no_terminal_receipt' or DEST.exists():
        raise RuntimeError('expected an unpublished incomplete archive')
    verified=[]
    for path, group in ((STAGE/'source-exact.zip','source_members'),
                        (STAGE/'public-metadata.zip','public_members'),
                        (PRIVATE/'retained-private.zip','retained_private_members')):
        if sha(path.read_bytes()) != manifest['archives'][str(path)]['sha256']:
            raise RuntimeError('archive digest mismatch')
        with zipfile.ZipFile(path) as archive:
            expected=manifest[group]
            if archive.namelist()!=[row['path'] for row in expected] or archive.testzip() is not None:
                raise RuntimeError('archive membership or CRC mismatch')
            for row in expected:
                raw=archive.read(row['path'])
                if len(raw)!=row['byte_count'] or sha(raw)!=row['sha256']:
                    raise RuntimeError('archive member mismatch')
        verified.append({'path':str(path),'sha256':sha(path.read_bytes()),'members':len(expected)})
    for origin, expected in manifest['original_files_before'].items():
        path=Path(origin); raw=path.read_bytes()
        if {'sha256':sha(raw),'byte_count':len(raw),'mtime_ns':path.stat().st_mtime_ns} != expected:
            raise RuntimeError('original bytes or mtime no longer match preservation')
    correction=WORK/'headless-lineage-controller-full4-interruption-audit-r2.json'
    if not correction.is_file(): raise RuntimeError('additive scope correction required')
    DEST.mkdir(parents=True)
    for name in ('source-exact.zip','public-metadata.zip','manifest.json'):
        shutil.copyfile(STAGE/name,DEST/name)
    for path in (WORK/'headless-lineage-controller-full4-interruption-audit-r1.json',correction,
                 WORK/'archive_lineage_full4_incomplete_r1.py',Path(__file__)):
        shutil.copyfile(path,DEST/path.name)
    readme='''# Four-panel lineage run: incomplete evidence

The original synthetic integration invocation used source `051b6a82a2f0b61d17b88a419a190652a71b424a`.
Its last persisted controller state contains all 34 planned cells: 32 succeeded,
one running, and one not started, with 32 scorer calls. No final evaluator gate,
JUnit, or original-process exit receipt was produced. This is not a passing full-grid test.

PID 54260 was observed live at 11:16 on 2026-09-15 (+08), then absent at the next
inspection; the native observer session was also unavailable. The reason and exit
code are unknown. The first observer's timeout and code 259 mean the process was
still active at that earlier observation. They do not describe the test's exit.
No run was restarted or terminated for this archival step.

`public-metadata.zip` preserves the original controller prefix, available earlier
failure reports, observer scripts and original observation receipt. The initial
interruption audit scoped its file count incorrectly; the additive `audit-r2`
file records the existing empty top-level log and the earlier observer timeout.
Both audits are retained without rewriting the original evidence.

`source-exact.zip` contains 776 tracked Python/Markdown files as read after the
interruption. There is no pre-run source manifest; unchanged source throughout
the original run is not claimed. The manifest identifies the source version,
every archive member and original path, and before/after byte and mtime checks.

The private archive retains 6,188 non-credential files at
`E:/_ryanDev/AI/research-loop-modular/retained-private-evidence/headless-lineage-controller-full4-incomplete-r1/retained-private.zip`.
Credential-shaped files and reparse paths are excluded and listed. Published
read-back checks verify archive membership, CRC, per-member bytes, and unchanged
original bytes/mtime. This is preservation evidence, not a semantic replay of
the unfinished controller or proof of scientific validity.

The separately closed 20-check lineage gate suite remains valid within its
reported scope. Full four-panel completion, real benchmark effects, and VAL
acceptance remain unestablished by this invocation. The planned module,
single-module and combination coverage is unchanged.
'''
    (DEST/'README.md').write_text(readme,encoding='utf-8')
    verification={'schema':'lineage-full4-incomplete-delivery-v1','status':'preserved_incomplete',
        'verified_archives':verified,'original_files_checked':len(manifest['original_files_before']),
        'original_bytes_and_mtimes_unchanged':True,'semantic_controller_replay':False,
        'original_process_exit_known':False,'scientific_effectiveness_proven':False}
    (DEST/'readback-verification.json').write_text(json.dumps(verification,indent=2)+'\n',encoding='utf-8')
    files=[{'path':p.name,'sha256':sha(p.read_bytes()),'byte_count':p.stat().st_size} for p in sorted(DEST.iterdir()) if p.is_file()]
    (DEST/'published-manifest.json').write_text(json.dumps({'schema':'published-files-v1','files':files},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'destination':str(DEST),'files':len(files)+1,'verification':verification,
        'published_manifest_sha256':sha((DEST/'published-manifest.json').read_bytes())}),flush=True)


if __name__=='__main__': main()
