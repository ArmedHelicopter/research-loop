"""Archive the closed, source-frozen C5 evaluator seam checkpoint."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile
sys.dont_write_bytecode=True

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
WORK=BASE/'work'
PREFIX=WORK/'headless-c5-evaluator-root-r1'
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/headless-c5-evaluator-root-r1'
PRIVATE=BASE/'retained-private-evidence/headless-c5-evaluator-root-r1'
spec=importlib.util.spec_from_file_location('archive_helpers',WORK/'prepare_headless_lineage_full4_archive_r1.py')
helpers=importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def stamp(path):
    raw=path.read_bytes()
    return {'sha256':sha(raw),'bytes':len(raw),'mtime_ns':path.stat().st_mtime_ns}


def main():
    closed=json.loads(Path(str(PREFIX)+'-closed.json').read_text(encoding='utf-8'))
    frozen=json.loads(Path(str(PREFIX)+'-before.json').read_text(encoding='utf-8'))
    source=json.loads(Path(str(PREFIX)+'-source-members.json').read_text(encoding='utf-8'))
    if (closed['exit_code']!=0 or closed['source_unchanged'] is not True
            or closed['junit']!={'tests':38,'failures':0,'errors':0,'skipped':0}
            or source['commit']!=frozen['commit'] or frozen['commit']!=closed['commit']
            or frozen['source_before']!=closed['source_after']):
        raise RuntimeError('checkpoint is not a closed exact 38-check run')
    source_zip=Path(str(PREFIX)+'-sources.zip')
    if sha(source_zip.read_bytes())!=source['archive_sha256']:
        raise RuntimeError('source archive hash differs')
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip() is not None or archive.namelist()!=[row['path'] for row in source['members']]:
            raise RuntimeError('source archive membership differs')
        for row in source['members']:
            raw=archive.read(row['path'])
            if sha(raw)!=row['sha256'] or len(raw)!=row['bytes'] or frozen['source_before'][row['path']]!=row['sha256']:
                raise RuntimeError('source member differs from pre-run inputs')
    resume=sys.argv[1:]==['--resume-private']
    if sys.argv[1:] and not resume: raise ValueError('unknown archive arguments')
    if DEST.exists() or (PRIVATE.exists() and not resume): raise FileExistsError('new archive paths required')
    if resume and (not PRIVATE.is_dir() or sorted(p.name for p in PRIVATE.iterdir())!=['test-originals-without-credentials.zip']):
        raise RuntimeError('resume is limited to the single retained private archive')
    files=list(helpers.regular_files(PREFIX))
    before={str(path):stamp(path) for path in files}
    PRIVATE.mkdir(parents=True,exist_ok=resume)
    rows=[(path.relative_to(PREFIX).as_posix(),path.read_bytes(),str(path)) for path in files]
    members=([{'path':name,'sha256':sha(raw),'byte_count':len(raw),'origin':origin} for name,raw,origin in rows]
        if resume else helpers.add_zip(PRIVATE/'test-originals-without-credentials.zip',rows))
    with zipfile.ZipFile(PRIVATE/'test-originals-without-credentials.zip') as archive:
        if archive.testzip() is not None or archive.namelist()!=[row['path'] for row in members]:
            raise RuntimeError('private archive membership differs')
        for row in members:
            raw=archive.read(row['path'])
            if sha(raw)!=row['sha256'] or len(raw)!=row['byte_count']:
                raise RuntimeError('retained member differs')
    after={str(path):stamp(path) for path in files}
    if before!=after: raise RuntimeError('original bytes or mtimes changed during preservation')
    roots=[path for path in PREFIX.iterdir() if path.is_dir() and not path.is_symlink()
           and path.name.startswith('test_c5_headless_stdio_binds_d') and not path.name.endswith('current')]
    if len(roots)!=1: raise RuntimeError('one original C5 stdio test root required')
    worker=roots[0]/'worker.jsonl'
    journal=[json.loads(line) for line in worker.read_text(encoding='utf-8').splitlines()]
    counts={state:sum(row['status']==state for row in journal) for state in ('reserved','succeeded','unknown')}
    if counts!={'reserved':177,'succeeded':177,'unknown':0}:
        raise RuntimeError('scorer denominator differs from 59 recipes by three synthetic targets')
    server=json.loads((roots[0]/'scorer-server.json').read_text(encoding='utf-8'))
    evaluator_root=Path(server['evaluator']['work_root']).resolve()
    if not evaluator_root.is_relative_to(roots[0].resolve()):
        raise RuntimeError('evaluator ledger is outside the original test root')
    ledger=json.loads((evaluator_root/'ledger.json').read_text(encoding='utf-8'))
    if len(ledger['calls'])!=177 or ledger['known_main_tokens']!=1770 or ledger['usage_incomplete'] is not False:
        raise RuntimeError('native synthetic evaluator ledger is incomplete')
    retention={'schema':'c5-evaluator-retention-v1','private_archive':str(PRIVATE/'test-originals-without-credentials.zip'),
        'private_archive_sha256':sha((PRIVATE/'test-originals-without-credentials.zip').read_bytes()),
        'members':members,'original_files_before':before,'original_files_after':after,
        'excluded_credentials':helpers.EXCLUSIONS,'pruned_reparse_paths':sorted(helpers.PRUNED_LINKS)}
    (PRIVATE/'retention-manifest.json').write_text(json.dumps(retention,indent=2)+'\n',encoding='utf-8')
    DEST.mkdir(parents=True)
    (DEST/'.gitattributes').write_bytes(b'* -text\n')
    for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml'):
        shutil.copyfile(Path(str(PREFIX)+suffix),DEST/('checkpoint'+suffix))
    shutil.copyfile(PRIVATE/'retention-manifest.json',DEST/'retention-manifest.json')
    shutil.copyfile(Path(__file__),DEST/Path(__file__).name)
    prior_helper=WORK/'archive_c5_evaluator_root_r1_failed_ledger_path.py'
    if prior_helper.is_file(): shutil.copyfile(prior_helper,DEST/prior_helper.name)
    prior=WORK/'c5-stdio-seam-r1-pytest/junit.xml'
    if prior.is_file(): shutil.copyfile(prior,DEST/'exploratory-success.xml')
    summary={'schema':'c5-evaluator-checkpoint-v1','source_commit':closed['commit'],
        'junit':closed['junit'],'source_files':closed['source_count'],'source_bytes_unchanged':True,
        'wall_seconds':closed['wall_seconds'],'native_stdio_scorer_cells':177,
        'worker_journal_counts':counts,'known_synthetic_main_tokens':ledger['known_main_tokens'],
        'real_model_calls':0,'paid_api_calls':0,'full_history_target_controller_executed':False,
        'validation_read':False,'scientific_effectiveness_proven':False,
        'retained_noncredential_files':len(members),'original_bytes_and_mtimes_unchanged':True,
        'archive_recovery':'Initial helper assumed an incorrect ledger location after retaining the private ZIP. The corrected helper resolves the original server config and independently verifies/reuses that ZIP without overwriting originals.',
        'exploratory_retention_limit':'Early exploratory failures reused basetemp and JUnit and were overwritten; not reconstructed. The earlier successful 177-cell JUnit is retained separately; current frozen source/run is authoritative.'}
    (DEST/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    readme=f'''# C5 evaluator configuration and closure checkpoint

Source `{closed['commit']}` passed 38 focused checks with {closed['source_count']}
Python/Markdown source files unchanged from the exact pre-run snapshot.

The native stdio test scores the canonical 59 recipes across three synthetic
targets: 177 reservations and 177 successful signed scores. It exercises the
real C5 client, production evaluator factory and worker, controller finalizer,
signed envelope and independent consumer. A forged startup descriptor and
tampered MAC are rejected. Known synthetic MAIN tokens are 1,770; this does
not measure real model usage, title usage or settlement.

Other checks cover exact legacy/opt-in schemas, usage/config equality, complete
and partial signed closures, retained partial token counts, controller attempt
serialization, and label isolation. The finalizer retains the signed envelope
rather than replacing it with its verified body. The outer controller writes
the closure with its last captured solver-accounting snapshot before subsequent
journal, close or fresh provider reads; its entire history/target execution is
not exercised by this scorer-only seam.

The original source snapshot, test report, source-before/after maps and retained
file inventory are attached. Private test originals are archived separately;
credential-shaped files and reparse paths are excluded and listed. Archive CRC,
member bytes and unchanged original bytes/mtime were checked.

An exploratory agent run also passed the 177-cell seam. Earlier exploratory
failures incorrectly reused its basetemp/JUnit and were overwritten. That gap
is retained explicitly; missing original failures have not been reconstructed.
The exploratory success is supplemental, not the frozen source checkpoint.

No real Grok, paid API or VAL data was used. This does not execute 46 actual
history builds and 118 runtime targets, demonstrate module effects, complete
C5 selection, or establish independent acceptance. All 48 questions and the
planned single-module and combination experiment denominators remain intact.
'''
    (DEST/'README.md').write_text(readme,encoding='utf-8')
    inventory=[{'path':p.name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(DEST.iterdir()) if p.is_file()]
    (DEST/'published-manifest.json').write_text(json.dumps({'schema':'published-files-v1','files':inventory},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'destination':str(DEST),'summary':summary,
        'published_manifest_sha256':sha((DEST/'published-manifest.json').read_bytes())}),flush=True)


if __name__=='__main__': main()
