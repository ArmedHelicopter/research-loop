"""Retain exact closed checks; no inferred native completion or scientific claims."""
import hashlib, importlib.util, json, shutil, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
BASE=Path('E:/_ryanDev/AI/research-loop-modular'); WORK=BASE/'work'
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/closure-binding-and-expiry-checks-r1'
PRIVATE=BASE/'retained-private-evidence/closure-binding-and-expiry-checks-r1'
RUNS=[('closure-binding','scorer-observation-closure-binding-check-r1','205d7540b4048a7733b8cfd18821a27a232c184b',8602),
 ('synthetic-expiry','c5-synthetic-expiry-check-r1','83aefb74f15a72d421dd5e34002e36483b6ce6d0',None)]

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
        members=read(WORK/(name+'-source-members.json')); started=read(WORK/(name+'-native-start.json')); joined=read(WORK/(name+('-native-join.json' if sid is not None else '-native-completion.json')))
        if sid is None:
            assert 'session_id' not in started and started['exit_code']==0
            assert joined['schema']=='native-command-completion-v1' and joined['result']==started
        else:
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
        copies.extend(WORK/(name+s) for s in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','.log','-native-start.json',('-native-join.json' if sid is not None else '-native-completion.json')))
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
    summary={'schema':'closure-binding-and-expiry-checks-v1','runs':summaries,'real_model_calls':0,'paid_api_calls':0,'validation_access':False,'scientific_effectiveness_proven':False,'originals_bytes_mtimes_unchanged':True,'retained_noncredential_files':len(rows)}
    write(DEST/'summary.json',summary)
    (DEST/'README.md').write_text('''# Exact closure association and synthetic fixture expiry

Source 205d7540 passed 35 focused checks. The observation catalogue now binds the
exact authenticated terminal closure digest to the retained evaluator gate.
Independent readback rejects a swapped gate with original journal, catalogue and
receipt unchanged. Successful, partial and rejected observations retain distinct
eligibility. These checks do not replace the separate complete 16-cell run.

Source 83aefb74 passed two synthetic fixture boundary checks. Synthetic login
lifetime is seven days; it remains locally valid at a 24-hour exercise point,
while the production 120-second near-expiry rejection remains intact. The tests
hard-disable account networking. This fixture repair does not estimate the C5
runtime duration and does not itself establish a complete C5 result.

The expiry check completed in its original exec call without yielding a native
session id; its exact native start/completion receipt preserves this distinction.
The closure check retains original native session 8602 and its terminal join.
Both preserve frozen sources, raw reports and noncredential originals. There
were no real model, added paid API or VAL calls. Engineering evidence is not
scientific effectiveness or all-module coverage.
''',encoding='utf-8')
    manifest={'schema':'published-files-v1','files':[{'path':p.name,'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(DEST.iterdir())]}
    write(DEST/'published-manifest.json',manifest)
    for row in manifest['files']:
        raw=(DEST/row['path']).read_bytes(); assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
    assert before=={str(p):stamp(p) for p in inputs}
    print(json.dumps({'archive':str(DEST),'public_files':len(manifest['files'])+1,'retained_originals':len(rows),'summary':summary}),flush=True)
if __name__=='__main__': main()
