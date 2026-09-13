"""Verify the committed retrieval archive and retain a closed root checkpoint."""
import hashlib, json, shutil, subprocess, zipfile
from pathlib import Path

TREE = Path('E:/_ryanDev/AI/research-loop-modular/integration')
WORK = TREE.parent / 'work'
REL = Path('results/modular-engineering-20260913/state-retrieval-prospective')
ROOT = TREE / REL
OUT = TREE / 'results/modular-engineering-20260913/state-retrieval-root'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def write(path, body): path.write_text(json.dumps(body, indent=2, ensure_ascii=True)+'\n', encoding='utf-8')

head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=TREE, text=True).strip()
closed = read(WORK/'state-retrieval-integrated-r1-closed.json')
assert closed['commit'] == head and closed['source_unchanged'] and closed['exit_code'] == 0
assert closed['junit']['tests'] > 0 and all(closed['junit'][k] == 0 for k in ('failures','errors','skipped'))
assert sha((WORK/'state-retrieval-integrated-r1.xml').read_bytes()) == closed['report_sha256']
index = read(ROOT/'archive-integrity.json')
paths = [p for p in ROOT.rglob('*') if p.is_file()]
assert {p.relative_to(ROOT).as_posix() for p in paths} == set(index)|{'archive-integrity.json'}
for path in paths:
    name = path.relative_to(ROOT).as_posix(); raw = path.read_bytes()
    if name in index:
        assert len(raw) == index[name]['bytes'] and sha(raw) == index[name]['sha256'], name
    assert raw == subprocess.check_output(['git','show','HEAD:'+(REL/name).as_posix()], cwd=TREE), name
members = read(ROOT/'archive-members.json'); member_count = 0
for prefix, entries in members.items():
    with zipfile.ZipFile(ROOT/(prefix+'.zip')) as archive:
        assert len(archive.namelist()) == len(entries)
        assert set(archive.namelist()) == {row['path'] for row in entries}
        for row in entries:
            raw = archive.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], row['path']
            member_count += 1
OUT.mkdir(parents=True, exist_ok=False)
for suffix in ('.xml','-before.json','-closed.json'):
    name = 'state-retrieval-integrated-r1'+suffix
    shutil.copyfile(WORK/name, OUT/name)
for name in ('state-retrieval-independent-review-r1.md','state-prediction-committed-archive-r1.json'):
    shutil.copyfile(WORK/name, OUT/name)
shutil.copyfile(__file__, OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json', {
    'source_commit':head, 'source_files':closed['source_count'], 'source_unchanged':True,
    'junit':closed['junit'], 'junit_sha256':closed['report_sha256'],
    'source_archive':{'total_files':len(paths),'indexed_files':len(index),'zip_members':member_count,
                      'disk_equals_git':True,'index_hashes_match':True,'zip_hashes_match':True},
    'scope':'state/retrieval controller full grid, failure and replay integration; state/prediction strict process scope and label isolation',
    'coverage':'16 of 36 pair controllers; 2 of 5 triple controllers; synthetic engineering only',
    'limitations':['scripted provider and solver; fixed synthetic rubric scores',
                   'mutation tests select BLADE arm 11; not all arms and tasks',
                   'separately bound state/corpus requests may share the same two qualified authority keys'],
    'new_paid_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p.read_bytes()) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'source_archive_files':len(paths),
                  'source_archive_indexed_files':len(index),'zip_members':member_count,'junit':closed['junit']}))
