"""Preserve the two closed evidence packages and verify staged Git bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

WORK = Path(__file__).parent
ROOT = WORK.parent / 'artifact-evidence-provenance'
PRIVATE = WORK.parent / 'retained-private-evidence'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_bytes())

specs = [
    ('headless-lineage-final-gate-r1', WORK/'headless-lineage-final-gate-archive-r1',
     '79fdf500185829398ffae9ddbb370d6fd64aa205040f4982585b2dc66d006aec',
     PRIVATE/'headless-lineage-final-gate-r1', 'selected-nonlinked-test-roots-without-credentials.zip',
     'fbf1801a1876e0c02a9f395803816037ce6976b746a4ec87d9cafa5139ca499a', 328),
    ('actual-m4m5-acp-initialize-diagnostic-r1', WORK/'actual-m4m5-acp-initialize-diagnostic-archive-r1/public-staging',
     '3decd52181973a5d0a277b6da12e82bca46c70039a8f421660f72c0234b1ff70',
     PRIVATE/'actual-m4m5-acp-initialize-diagnostic-r1', 'diagnostic-private-without-credentials.zip',
     '32ade9462a8717b2c49b89e5925f8e3768213c0f251ee32f3ce4144b1af8d44f', 89),
]
verified = []
for name, stage, expected_manifest, private_root, zip_name, expected_private, count in specs:
    assert sha(stage/'published-manifest.json') == expected_manifest
    publication = read(stage/'published-manifest.json')
    listed = publication.get('copied_artifacts', publication.get('published_files'))
    for row in listed:
        path = stage/row['path']
        assert sha(path) == row['sha256'] and path.stat().st_size == row['bytes']
    private_manifest = private_root/'retained-manifest.json'
    assert sha(private_manifest) == expected_private
    retained = read(private_manifest)
    archive = private_root/zip_name
    expected_zip = publication.get('private_zip_sha256') or publication['retained_private']['sha256']
    assert sha(archive) == expected_zip
    rows = retained.get('files', retained.get('source_manifest'))
    with zipfile.ZipFile(archive) as zipped:
        assert len(zipped.namelist()) == len(set(zipped.namelist())) == count
        assert zipped.testzip() is None
        for row in rows:
            origin = Path(row['source']) if 'source' in row else WORK/'actual-m4m5-acp-initialize-diagnostic-r1'/row['path']
            assert sha(origin) == row['sha256'] and origin.stat().st_size == row['bytes']
            assert origin.stat().st_mtime_ns == row['mtime_ns']
            member = row['path'] if row['path'] in zipped.namelist() else 'diagnostic/'+row['path']
            assert hashlib.sha256(zipped.read(member)).hexdigest() == row['sha256']
    if name == 'headless-lineage-final-gate-r1':
        before, closed, source = read(stage/'before.json'), read(stage/'closed.json'), read(stage/'source-members.json')
        assert closed['junit'] == {'tests':20, 'failures':0, 'errors':0, 'skipped':0}
        assert closed['source_unchanged'] and len(before['source_before']) == 778
        with zipfile.ZipFile(stage/'sources.zip') as zipped:
            assert set(zipped.namelist()) == set(before['source_before'])
            for path, expected in before['source_before'].items():
                assert hashlib.sha256(zipped.read(path)).hexdigest() == expected
    destination = ROOT/'results/modular-engineering-20260915'/name
    assert not destination.exists()
    destination.mkdir(parents=True)
    for path in stage.iterdir():
        assert path.is_file() and not path.is_symlink() and not path.is_junction()
        shutil.copyfile(path, destination/path.name)
    shutil.copyfile(private_manifest, destination/'retained-private-manifest.json')
    shutil.copyfile(Path(__file__), destination/'publish-helper.py')
    if name == 'headless-lineage-final-gate-r1':
        (destination/'README.md').write_text('''# Independent lineage final gate

Frozen source `8abe622acb2417a5008a66466316663e2885972c` passed 20 checks
in 161.063 seconds; all 778 source/document files remained byte-identical.
The checks cover a real synthetic-native/Docker partial closure, four actual
stdio worker handshakes, signed client closure/tamper verification, root alias
rejection, lower-bound preservation after failure, and ten label-isolation cases.
Model/account responses were synthetic. This is engineering evidence only.

A signed partial closure is retained but cannot make a full panel eligible.
The controller independently checks authority/configuration/reference bindings
and preserves authenticated cumulative usage evidence after final refresh failure.
The separate 34-cell producer run at `051b6a82` is not a result of this gate.

The private archive contains 328 noncredential files from five explicit test
roots; 13 credential files were excluded. Original hashes and modification times,
ZIP contents, exact source archive and staged Git bytes were independently checked.
`delivery-manifest.json` covers all published files except itself.
''', encoding='utf-8', newline='\n')
    else:
        shutil.copyfile(WORK/'actual-m4m5-acp-initialize-diagnostic-archive-r1/prepare_archive.py', destination/'archive-helper.py')
    (destination/'.gitattributes').write_bytes(b'* -text\n')
    delivered = [{'path':p.name, 'bytes':p.stat().st_size, 'sha256':sha(p)} for p in sorted(destination.iterdir())]
    (destination/'delivery-manifest.json').write_text(json.dumps({'schema':'closed-lineage-evidence-delivery-v1',
        'self_excluding':True, 'files':delivered}, indent=2)+'\n', encoding='utf-8', newline='\n')
    subprocess.check_call(['git','add','--sparse',destination.relative_to(ROOT).as_posix()], cwd=ROOT)
    for path in destination.iterdir():
        assert subprocess.check_output(['git','show',':'+path.relative_to(ROOT).as_posix()], cwd=ROOT) == path.read_bytes()
    verified.append({'path':str(destination), 'files':len(delivered)+1, 'private_files':count,
                     'delivery_manifest_sha256':sha(destination/'delivery-manifest.json'),
                     'staged_git_bytes_equal_disk':True, 'private_original_hashes_and_mtimes_equal':True})
with (WORK/'lineage-gate-and-initialize-diagnostic-delivery-r1.json').open('x', encoding='utf-8') as output:
    json.dump({'schema':'closed-lineage-evidence-delivery-verification-v1','archives':verified},output,indent=2)
print(json.dumps(verified))
