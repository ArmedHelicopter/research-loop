from pathlib import Path
import hashlib, json, os, shutil, zipfile

BASE = Path(r'E:\_ryanDev\AI\research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'headless-descriptor-primary-root-r1'
STAGE = WORK / 'headless-descriptor-primary-archive-r1'
PRIVATE = BASE / 'retained-private-evidence' / 'headless-descriptor-primary-r1'
OUT = PRIVATE / 'selected-test-roots-without-credentials.zip'
ROOTS = (
    'test_full_v6_factorial_closes_0',
    'test_primary_scorer_factory_co0',
    'test_pure_descriptor_matches_c0', 'test_pure_descriptor_matches_c1',
    'test_pure_descriptor_rejects_n0',
    'test_headless_factory_rejects_0', 'test_headless_factory_rejects_1',
    'test_headless_factory_rejects_2', 'test_headless_factory_rejects_3',
    'test_headless_factory_rejects_4',
)

def sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def write(path, body):
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')

def linked(path):
    return path.is_symlink() or bool(getattr(path.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400)

def credential(relative):
    name = relative.name.lower()
    return name == 'auth.json' or name.endswith('.key') or 'credential' in name or 'secret' in name

def files_under(root):
    rows, excluded = [], []
    for current, dirs, names in os.walk(root, followlinks=False):
        current = Path(current)
        kept = []
        for name in dirs:
            child = current / name
            if linked(child):
                raise RuntimeError(f'linked child rejected: {child}')
            kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = current / name
            rel = path.relative_to(PREFIX)
            if linked(path): raise RuntimeError(f'linked file rejected: {path}')
            if credential(rel):
                excluded.append(rel.as_posix()); continue
            stat = path.stat()
            rows.append({'source': str(path), 'path': rel.as_posix(), 'sha256': sha_file(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
    return rows, excluded

def main():
    closed = json.loads((WORK / 'headless-descriptor-primary-root-r1-closed.json').read_bytes())
    before = json.loads((WORK / 'headless-descriptor-primary-root-r1-before.json').read_bytes())
    assert closed['commit'] == '2113371268b30411712273623371cbcf49e0ccc8'
    assert closed['exit_code'] == 0 and closed['source_unchanged'] and closed['source_count'] == 775
    assert closed['junit'] == {'tests': 20, 'failures': 0, 'errors': 0, 'skipped': 0}
    assert before['source_before'] == closed['source_after']
    assert not STAGE.exists() and not PRIVATE.exists()
    assert all((PREFIX / root).is_dir() and not linked(PREFIX / root) for root in ROOTS)
    STAGE.mkdir(); PRIVATE.mkdir(parents=True)
    copied = []
    artifacts = {
        'before.json': WORK / 'headless-descriptor-primary-root-r1-before.json',
        'closed.json': WORK / 'headless-descriptor-primary-root-r1-closed.json',
        'source-manifest.json': WORK / 'headless-descriptor-primary-root-r1-source-members.json',
        'sources.zip': WORK / 'headless-descriptor-primary-root-r1-sources.zip',
        'checks.xml': WORK / 'headless-descriptor-primary-root-r1.xml',
        'check-helper.py': WORK / 'run_frozen_checks_with_source.py',
        'archive-helper.py': Path(__file__),
    }
    for dest, source in artifacts.items():
        target = STAGE / dest; shutil.copyfile(source, target)
        assert source.read_bytes() == target.read_bytes()
        copied.append({'path': dest, 'sha256': sha_file(target), 'bytes': target.stat().st_size})
    rows, excluded = [], []
    for root in ROOTS:
        listed, removed = files_under(PREFIX / root); rows.extend(listed); excluded.extend(removed)
    rows.sort(key=lambda row: row['path']); excluded.sort()
    with zipfile.ZipFile(OUT, 'x', compression=zipfile.ZIP_DEFLATED) as saved:
        for row in rows: saved.writestr(row['path'], Path(row['source']).read_bytes())
    with zipfile.ZipFile(OUT) as saved:
        assert saved.namelist() == [row['path'] for row in rows]
        for row in rows:
            raw = saved.read(row['path']); original = Path(row['source'])
            assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
            assert sha_file(original) == row['sha256'] and original.stat().st_mtime_ns == row['mtime_ns']
    private_manifest = {'schema': 'headless-descriptor-primary-retained-private-v1', 'roots': list(ROOTS), 'files': rows,
        'excluded_credentials': excluded, 'zip': {'path': str(OUT), 'sha256': sha_file(OUT), 'bytes': OUT.stat().st_size},
        'original_bytes_and_mtime_unchanged': True, 'links_followed': False}
    write(PRIVATE / 'retained-manifest.json', private_manifest)
    assert not any(credential(Path(name)) for name in zipfile.ZipFile(OUT).namelist())
    publication = {'schema': 'headless-descriptor-primary-archive-v1', 'closed_gate': {'commit': closed['commit'], 'junit': closed['junit'], 'wall_seconds': closed['wall_seconds'], 'source_count': closed['source_count'], 'source_unchanged': closed['source_unchanged']},
        'copied_artifacts': copied, 'retained_private': {'path': str(OUT), 'sha256': sha_file(OUT), 'manifest_sha256': sha_file(PRIVATE / 'retained-manifest.json'), 'roots': list(ROOTS), 'file_count': len(rows), 'excluded_credential_count': len(excluded), 'links_followed': False},
        'limits': ['Synthetic descriptor/controller engineering gate only.', 'No model, API, Docker, VAL, or ground-truth execution in this archive step.', 'Credential files were excluded from the retained raw zip.'], 'self_excluding': True}
    write(STAGE / 'published-manifest.json', publication)
    manifest = json.loads((STAGE / 'published-manifest.json').read_bytes())
    for item in copied: assert sha_file(STAGE / item['path']) == item['sha256']
    assert sha_file(OUT) == manifest['retained_private']['sha256']
    assert sha_file(PRIVATE / 'retained-manifest.json') == manifest['retained_private']['manifest_sha256']
    assert all(Path(row['source']).stat().st_mtime_ns == row['mtime_ns'] and sha_file(Path(row['source'])) == row['sha256'] for row in rows)
    print(json.dumps({'stage': str(STAGE), 'private_zip': str(OUT), 'published_manifest_sha256': sha_file(STAGE / 'published-manifest.json'), 'retained_manifest_sha256': sha_file(PRIVATE / 'retained-manifest.json'), 'roots': len(ROOTS), 'files': len(rows), 'excluded_credentials': len(excluded)}))

if __name__ == '__main__': main()
