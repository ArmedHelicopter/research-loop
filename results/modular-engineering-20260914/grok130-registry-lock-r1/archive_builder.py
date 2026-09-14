"""Retain closed root checks and both complete/timeout owner observations."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
DEST = BASE / 'integration/results/modular-engineering-20260914'
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def close(out):
    (out / '.gitattributes').write_text('* -text\n', encoding='utf-8')
    shutil.copyfile(__file__, out / 'archive_builder.py')
    write(out / 'archive-integrity.json', {
        p.relative_to(out).as_posix(): {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
        for p in out.rglob('*') if p.is_file()
    })


def root_check(prefix, scope):
    original = BASE / 'work' / prefix
    closure = json.loads(Path(str(original) + '-closed.json').read_bytes())
    assert closure['source_unchanged'] and closure['exit_code'] == 0
    out = DEST / prefix
    out.mkdir(exist_ok=False)
    for suffix in ('-before.json', '-closed.json', '.xml', '-sources.zip', '-source-members.json'):
        shutil.copyfile(Path(str(original) + suffix), out / (prefix + suffix))
    source_rows = json.loads(Path(str(original) + '-source-members.json').read_bytes())['members']
    rows, excluded = [], []
    with zipfile.ZipFile(out / (prefix + '-originals.zip'), 'x', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(original.rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(original).as_posix()
            if (p.is_symlink() or not p.resolve().is_relative_to(original.resolve())
                    or p.name in {'auth.json', 'login.json'} or '__pycache__' in p.parts
                    or p.suffix in {'.key', '.pyc'}
                    or (p.suffix == '.exe' and not (p.name == 'synthetic-grok.exe' and p.stat().st_size < 1024))):
                excluded.append(rel)
                continue
            raw = p.read_bytes()
            z.writestr(rel, raw)
            rows.append({'path': rel, 'bytes': len(raw), 'sha256': sha(raw)})
    write(out / 'archive-members.json', {prefix + '-sources': source_rows, prefix + '-originals': rows})
    write(out / 'excluded-paths.json', excluded)
    write(out / 'unavailable-stdout.json', [str(original) + '-stdout.txt'])
    (out / 'SCOPE.md').write_text(scope, encoding='utf-8')
    close(out)


def owner_runs():
    out = DEST / 'native-build-owner-closed'
    out.mkdir(exist_ok=False)
    members = {}
    for stem in ('native-phase-complete-r1-closed-originals-r3',
                 'native-execution-complete-r2-closed-originals-r4'):
        source = BASE / 'work' / stem
        manifest = json.loads(source.with_suffix('.json').read_bytes())
        archive = source.with_suffix('.zip')
        assert sha(archive.read_bytes()) == manifest['archive_sha256']
        rows = manifest['files']
        with zipfile.ZipFile(archive) as z:
            assert len(z.namelist()) == len(rows)
            assert set(z.namelist()) == {row['path'] for row in rows}
            for row in rows:
                raw = z.read(row['path'])
                assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
        shutil.copyfile(archive, out / archive.name)
        shutil.copyfile(source.with_suffix('.json'), out / (stem + '.json'))
        members[stem] = rows
    write(out / 'archive-members.json', members)
    (out / 'SCOPE.md').write_text(
        '# Native build owner evidence\n\n'
        'The original 12-case batch reached its 45-minute wall without final JUnit. '
        'Partial controller scores are historical observations, not passed pytest cases. '
        'The next source f0869c4 completed one full execution-family case: 1/1, '
        '956.546 seconds, six restricted builds, 70 synthetic MAIN opportunities, '
        '96 Docker executions and 32 independent scores. This does not complete '
        'the remaining eleven cases. Authentication, keys and runtime caches are '
        'excluded; original full local directories remain intact. No real model/API '
        'calls or validation access occurred.\n', encoding='utf-8')
    close(out)


if __name__ == '__main__':
    root_check('native-build-q6-root-r1',
        '# Root native build and separate Q6 check\n\n'
        'Frozen 5619cd5 passed 12/12 with 645 source files unchanged. Checks cover '
        'PhaseProvider binding and aborts, actual restricted build accounting, '
        'the separate complete Q6.3 builder/successor fixture, and its failed-call '
        'denominator. Synthetic native model responses, actual Docker; no scientific '
        'effect evaluation or validation access.\n')
    root_check('c5-runtime-root-r1',
        '# Root common TRAIN runtime and scoring boundary\n\n'
        'Frozen 0644e32 exercises the imported common history/target kernel, '
        'original protocol and stage binding, and common scorer process. The '
        'actual runtime path remains one history and one target; the complete '
        'formal history barrier and full-grid target execution/selection are '
        'not established. Synthetic model responses, actual Docker and scorer '
        'process; no validation access or scientific efficacy claim.\n')
    owner_runs()
    print('Closed root and owner archives retained')
