"""Archive only the closed synthetic C5 repair runs and their original versions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

tree = Path('E:/_ryanDev/AI/research-loop-modular/c5-frozen-handoff')
work = tree.parent / 'work'
out = tree / 'results/modular-engineering-20260914/c5-handoff-repair'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
def write(path, value):
    path.write_bytes((json.dumps(value, indent=2)+'\n').encode('utf-8'))
def git(*args):
    return subprocess.check_output(['git', *args], cwd=tree)

assert not git('status', '--porcelain').strip()
head = git('rev-parse', 'HEAD').decode().strip()
closed = json.loads((work/'c5-handoff-repair-check03-closed.json').read_bytes())
assert closed['commit'] == head == '9e44503d501929d3b10b77a220d1c165462f890c'
assert closed['source_unchanged'] and closed['source_count'] == 591 and closed['exit_code'] == 0
assert closed['junit'] == {'tests':58, 'failures':0, 'errors':0, 'skipped':0}
out.mkdir(parents=True, exist_ok=False)
(out/'.gitattributes').write_bytes(b'* -text\n')
for number in (1, 2, 3):
    prefix = f'c5-handoff-repair-check{number:02d}'
    for suffix in ('-before.json', '-closed.json', '.xml', '.stdout.txt'):
        shutil.copyfile(work/(prefix+suffix), out/(prefix+suffix))

historical = out/'historical'; historical.mkdir()
for name in ('c5-frozen-handoff-initial-failure.txt', 'c5-frozen-handoff-source-pin.json',
             'c5-frozen-handoff-wave1-source.zip', 'c5-frozen-handoff-r2-source-pin.json',
             'c5-frozen-handoff-r2-source.zip'):
    shutil.copyfile(work/name, historical/name)
selected = ('research_loop/modular/c5_frozen_handoff.py', 'tests/test_c5_frozen_handoff.py', 'docs/c5-frozen-handoff.md')
for revision in ('3c18e16', 'c94286d', '2eeb02a', '6ab7632', '9e44503'):
    for name in selected:
        target = out/'source-versions'/revision/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('show', revision+':'+name))

exclusions = []
with zipfile.ZipFile(out/'original-synthetic-evidence.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for number in (1, 2, 3):
        prefix = f'c5-handoff-repair-check{number:02d}'
        base = work/prefix
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(base)
            linked = any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p.is_relative_to(base))
            if linked or path.suffix not in {'.json', '.jsonl', '.txt'}:
                exclusions.append(prefix+'/'+relative.as_posix())
                continue
            archive.writestr(prefix+'/'+relative.as_posix(), path.read_bytes())

# Put the actual successful output records next to the report for inspection.
base = work/'c5-handoff-repair-check03'
for name in ('prepared-handoff.json', 'original-journals.json', 'c5-validation-preparation.json'):
    matches = [p for p in base.rglob(name) if p.is_file() and not p.is_symlink() and not p.is_junction()]
    assert len(matches) == 1, (name, matches)
    shutil.copyfile(matches[0], out/name)

write(out/'exclusions.json', exclusions)
write(out/'checks.json', {k:v for k,v in closed.items() if k != 'source_after'})
shutil.copyfile(__file__, out/'archive_evidence.py')
(out/'README.md').write_bytes(b'''# C5 structural preparation repair

Final source 9e44503d501929d3b10b77a220d1c165462f890c passed 58 checks,
with 591 tracked source/document hashes unchanged. Check 01 passed 56 tests;
checks 02 and 03 passed 58. All original reports, stdout and source manifests
are retained. Older unverified versions and their import-collection failure
remain in historical/ and source-versions/; no earlier result was overwritten.

The actual typed success path executes the public binding-only M4/M5 runner
using eight in-process synthetic responses and replays its original TRAIN
journals. It produces the committed prepared-handoff.json and a 32-cell
c5-validation-preparation.json with two synthetic held-out groups per benchmark,
two replicates and four arms. original-journals.json contains the exact source
snapshot. The synthetic-evidence ZIP also retains every exercised negative
journal, including deliberate source corruption and coherent package-context
substitution. These intentional negative artifacts are not candidate successes.

The adapter is exactly m4-m5-combination-binding-only-v1. Component fields are
whole-arm package projections, not independently versioned module builds. No
actual model/API call, real validation input, calibration, scientific scoring,
joint TRAIN selection, custody lease, acceptance or deployment occurred.
Criteria in the example are synthetic proposals, not approved research values.
All 48 question studies, 36 pairs, five triples, C4 and separate Q6.3 remain
separate obligations; this archive does not claim their research completion.

The archive verifies byte preservation through its complete hash index and ZIP
member index. Runtime trace paths inside original records retain their original
locations for provenance; extracting an archive does not rewrite those bindings.
''')
members = {}
for path in out.rglob('*.zip'):
    with zipfile.ZipFile(path) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        members[path.stem] = [{'path':name, 'sha256':sha(archive.read(name)), 'bytes':len(archive.read(name))}
                              for name in archive.namelist()]
write(out/'archive-members.json', members)
write(out/'archive-integrity.json', {p.relative_to(out).as_posix(): {'sha256':sha(p.read_bytes()), 'bytes':p.stat().st_size}
                                    for p in out.rglob('*') if p.is_file()})
print(json.dumps({'source':head, 'archive':str(out), 'files':len([p for p in out.rglob('*') if p.is_file()]),
                  'zip_members':sum(len(v) for v in members.values()), 'exclusions':len(exclusions)}))
