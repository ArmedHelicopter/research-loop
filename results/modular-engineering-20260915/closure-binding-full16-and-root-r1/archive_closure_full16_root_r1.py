"""Retain exact closed checks; no inferred native completion or scientific claims."""
import hashlib, importlib.util, json, shutil, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
BASE=Path('E:/_ryanDev/AI/research-loop-modular'); WORK=BASE/'work'
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/closure-binding-full16-and-root-r1'
PRIVATE=BASE/'retained-private-evidence/closure-binding-full16-and-root-r1'
RUNS=[('closure-full16','scorer-observation-closure-binding-full16-r1','205d7540b4048a7733b8cfd18821a27a232c184b',63017),('root-p0-c5','p0-c5-root-integration-r1','4c2df56d462c1ff8eab3118a66a4b246525ad708',37025)]

def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(p): return json.loads(p.read_bytes())
def stamp(p): return {'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
def write(p,v):
    with p.open('xb') as out: out.write((json.dumps(v,indent=2)+'\n').encode())
def main():
    assert not DEST.exists() and not PRIVATE.exists()
    helper=WORK/'prepare_headless_lineage_full4_archive_r1.py'
    spec=importlib.util.spec_from_file_location('retention',helper); retention=importlib.util.module_from_spec(spec); spec.loader.exec_module(retention)
    copies=[]; retained=[]; summaries=[]
    for label,name,commit,sid in RUNS:
        before=read(WORK/(name+'-before.json')); closed=read(WORK/(name+'-closed.json'))
        members=read(WORK/(name+'-source-members.json')); started=read(WORK/(name+'-native-start.json')); joined=read(WORK/(name+'-native-join.json'))
        assert started.get('result',started)['session_id']==sid
        assert joined['schema']=='native-session-join-v1' and joined['native_session_id']==sid
        assert joined['source_commit']==commit and 'session_id' not in joined['result']
        assert joined['result']['exit_code']==closed['exit_code']==0
        assert before['commit']==closed['commit']==members['commit']==commit
        assert before['source_before']==closed['source_after'] and closed['source_unchanged']
        assert closed['source_count']==len(before['source_before']) and closed['new_paid_calls']==0
        report=WORK/(name+'.xml'); assert sha(report.read_bytes())==closed['report_sha256']
        suites=list(ET.parse(report).getroot().iter('testsuite'))
        assert closed['junit']=={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
        sourcezip=WORK/(name+'-sources.zip'); assert sha(sourcezip.read_bytes())==members['archive_sha256']
        assert before['source_before']=={r['path']:r['sha256'] for r in members['members']}
        with zipfile.ZipFile(sourcezip) as z:
            assert z.testzip() is None and z.namelist()==[r['path'] for r in members['members']]
            for row in members['members']:
                raw=z.read(row['path']); assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
        copies.extend(WORK/(name+s) for s in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','.log','-native-start.json','-native-join.json'))
        originals=sorted(retention.regular_files(WORK/name))
        retained.extend((label+'/'+p.relative_to(WORK/name).as_posix(),p) for p in originals)
        summaries.append({'label':label,'prefix':str(WORK/name),'commit':commit,'native_session_id':sid,'native_exit':0,'junit':closed['junit'],'source_count':closed['source_count'],'wall_seconds':closed['wall_seconds'],'report_sha256':closed['report_sha256'],'retained_originals':len(originals)})
    copies.extend([Path(__file__),helper])
    inputs=sorted({*copies,*(p for _,p in retained)}); before={str(p):stamp(p) for p in inputs}
    PRIVATE.mkdir(parents=True); archive=PRIVATE/'originals-without-credentials.zip'
    rows=retention.add_zip(archive,((n,p.read_bytes(),str(p)) for n,p in retained))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist()==[r['path'] for r in rows]
        for row in rows:
            raw=z.read(row['path']); assert sha(raw)==row['sha256']==before[row['origin']]['sha256'] and len(raw)==row['byte_count']
    assert before=={str(p):stamp(p) for p in inputs}
    write(PRIVATE/'retention-manifest.json',{'schema':'closed-check-retention-v1','archive':str(archive),'sha256':sha(archive.read_bytes()),'members':rows,'inputs_before':before,'inputs_after':before,'excluded_credentials':retention.EXCLUSIONS,'pruned_reparse_paths':sorted(retention.PRUNED_LINKS)})
    DEST.mkdir(parents=True); (DEST/'.gitattributes').write_bytes(b'* -text\n')
    copies.append(PRIVATE/'retention-manifest.json')
    assert len({p.name for p in copies})==len(copies)
    for p in copies:
        shutil.copyfile(p,DEST/p.name); assert (DEST/p.name).read_bytes()==p.read_bytes()
    summary={'schema':'closure-binding-full16-and-root-v1','runs':summaries,'real_model_calls':0,'paid_api_calls':0,'validation_access':False,'scientific_effectiveness_proven':False,'originals_bytes_mtimes_unchanged':True,'retained_noncredential_files':len(rows)}
    write(DEST/'summary.json',summary)
    (DEST/'README.md').write_text('''# Exact closure binding in the complete 16-cell process

Original native session 63017 joined exit 0. The complete actual Docker/stdio
integration passed at source 205d7540 in 1,162.875 seconds with 795 unchanged
source/document files. It preserves all 16 scored cells, 48 synthetic solver and
16 synthetic evaluator calls, and independently reads the sealed observation
catalogues after scorer closure. The authenticated observation digest is now
required to match the exact retained gate closure. This verifies the repaired
seam that the prior fa688a8 full run did not establish. These durations are not
a controlled performance comparison.

Separate ROOT source 4c2df56d passed 15 checks: ten label-isolation audits, three
synthetic P0 custody reader/CLI checks and two synthetic expiry-boundary checks.
Original session 37025 joined exit 0, with 797 unchanged sources. Arm worktrees
remain label-free; the separate audit checkout owns label-isolation checks.

Neither run makes real model calls, adds paid API charges or performs formal
VAL acceptance. Synthetic validation identities in P0 fixtures are not access
to held-out data. No scientific effectiveness or complete module coverage follows.
Exact frozen source archives, starts/joins, raw reports, and private noncredential
originals are retained and read back; original bytes and mtimes are unchanged.
''',encoding='utf-8')
    manifest={'schema':'published-files-v1','files':[{'path':p.name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(DEST.iterdir())]}
    write(DEST/'published-manifest.json',manifest)
    for row in manifest['files']:
        raw=(DEST/row['path']).read_bytes(); assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
    assert before=={str(p):stamp(p) for p in inputs}
    print(json.dumps({'archive':str(DEST),'public_files':len(manifest['files'])+1,'retained_originals':len(rows),'summary':summary}),flush=True)
if __name__=='__main__': main()
