"""Read back the retained profile ZIP and publish its noncredential summaries."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
STAGE = WORK / 'headless-verification-profile-archive-r1'
PRIVATE = BASE / 'retained-private-evidence/headless-verification-profile-r1'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/headless-verification-profile-r1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def main():
    assert not DEST.exists()
    manifest = read(STAGE / 'staging-manifest.json')
    for row in manifest['files']:
        assert {'path': row['path'], **stamp(STAGE / row['path'])} == row
    before = read(STAGE / 'source-files-before.json')['files']
    after = read(STAGE / 'source-files-after.json')['files']
    assert before == after
    for row in before:
        assert {'path': row['path'], **stamp(WORK / row['path'])} == row
    retained = read(PRIVATE / 'retained-private-manifest.json')
    assert retained['source_before'] == retained['source_after'] == before
    archive_path = Path(retained['zip']['path'])
    assert sha(archive_path.read_bytes()) == retained['zip']['sha256']
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None and archive.namelist() == [r['path'] for r in retained['members']]
        for row in retained['members']:
            raw = archive.read(row['path'])
            assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
            assert raw == (WORK / row['path']).read_bytes()
        originals = [archive.read(name) for name in archive.namelist() if name.endswith(('.input-before.json', '.input-after.json'))]
        assert len(originals) == 3 and originals[0] == originals[1] == originals[2]
        inventory = json.loads(originals[0])
        assert inventory['file_count'] == len(inventory['files']) == 6655
    assert not any(p.name.endswith(('.input-before.json', '.input-after.json')) for p in STAGE.iterdir())
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for p in [*STAGE.iterdir(), Path(__file__)]:
        assert p.is_file()
        shutil.copyfile(p, DEST / p.name)
        assert p.read_bytes() == (DEST / p.name).read_bytes()
    receipt = {'schema': 'headless-profile-root-readback-v1', 'private_zip_sha256': retained['zip']['sha256'],
        'private_members_readback': len(retained['members']), 'original_inventory_rows': 6655,
        'three_inventory_files_byte_identical': True, 'credential_summary_inventories_public': False,
        'staging_and_source_bytes_mtimes_unchanged': True, 'new_profile_or_model_calls': 0}
    (DEST / 'root-readback.json').write_bytes(json.dumps(receipt, indent=2).encode() + b'\n')
    (DEST / 'INTEGRATION.md').write_text('''# 后续实现与范围

这里保留的是关闭的 full5 原件读取 profile，以及当时的重复调用审查。136 条调用的 1.619 秒不能作为完整 C5 的时长或加速比例。根独立读回私有 ZIP 的十个成员，并确认三份 6,655 项清单字节完全相同；包含凭据路径摘要的清单只放私有归档。

对应的一处重复读取随后已[修复并通过 102 项集成检查](../headless-binding-replay-r1/README.md)。原 profile、失败 setup、更正和审查报告保持其当时版本，不把后来修复写回旧证据。
''', encoding='utf-8')
    for row in before:
        assert {'path': row['path'], **stamp(WORK / row['path'])} == row
    for row in manifest['files']:
        assert {'path': row['path'], **stamp(STAGE / row['path'])} == row
    publication = {'schema': 'published-files-v1', 'files': [
        {'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]}
    (DEST / 'published-manifest.json').write_bytes(json.dumps(publication, indent=2).encode() + b'\n')
    for row in publication['files']:
        raw = (DEST / row['path']).read_bytes()
        assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    print(json.dumps({'destination': str(DEST), 'root_readback': receipt,
                      'manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__':
    main()
