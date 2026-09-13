"""Verify committed state/prediction evidence and retain root integration closure."""
import hashlib,json,shutil,subprocess
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
REL=Path('results/state-prediction-prospective-20260913');ROOT=TREE/REL
OUT=TREE/'results/modular-engineering-20260913/state-prediction-root'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'state-prediction-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']=={'tests':32,'failures':0,'errors':0,'skipped':0}
index=read(ROOT/'archive-integrity.json')['files']; paths=[p for p in ROOT.rglob('*') if p.is_file()]
assert {p.relative_to(ROOT).as_posix() for p in paths}==set(index)|{'archive-integrity.json'}
for p in paths:
    name=p.relative_to(ROOT).as_posix();raw=p.read_bytes()
    if name in index:
        assert len(raw)==index[name]['bytes'] and sha(p)==index[name]['sha256'],name
    assert raw==subprocess.check_output(['git','show','HEAD:'+(REL/name).as_posix()],cwd=TREE),name
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('.xml','-before.json','-closed.json'):
    shutil.copyfile(WORK/('state-prediction-integrated-r1'+suffix),OUT/('state-prediction-integrated-r1'+suffix))
review=TREE.parent/'state-prediction-combos/work/state-prediction-independent-review-r1.md'
shutil.copyfile(review,OUT/review.name)
for name in ('lineage-parity-committed-archive-r1.json','lineage-useful-committed-archive-r2.json'):
    shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
    'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
    'state_prediction_archive':{'total_files':len(paths),'indexed_files':len(index),'disk_equals_git':True},
    'scope':'new 24-cell primary TRAIN integration, shared v3 qualification drift and legacy admission process regression',
    'coverage':'13 of 36 pair controllers; 2 of 5 triples; synthetic engineering only',
    'limitations':['mutation tests select BLADE arms 00/01','scripted solver and fixed synthetic scorer',
        'later controller model/Docker failures not specifically exercised by this family'],
    'index_count_correction':'lineage-useful archive contains18 total files,17 SHA256-indexed entries; earlier independent audit called18 indexed',
    'new_paid_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'source_archive_files':len(paths),'source_archive_indexed_files':len(index)}))
