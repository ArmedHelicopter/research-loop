"""Publish retained probe metadata without rewriting the original attempts."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
STAGE = BASE / 'work/c5-headless-runtime-probe-archive-r1'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/c5-headless-runtime-probe-r1'
PRIVATE = BASE / 'retained-private-evidence/c5-headless-runtime-probe-r1'


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def require(value, message):
    if not value: raise RuntimeError(message)


def main():
    require(not DEST.exists(), 'fresh delivery directory required')
    public, supplement = read(STAGE / 'public-manifest.json'), read(STAGE / 'supplement-manifest.json')
    require(sha((STAGE / 'public-manifest.json').read_bytes()) == supplement['base_public_manifest_sha256'], 'base manifest changed')
    for entries in (public['files'], supplement['files']):
        for name, row in entries.items():
            raw = (STAGE / name).read_bytes()
            require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'public staging member differs')
    retention = read(STAGE / 'retention-manifest.json')
    require((PRIVATE / 'retention-manifest.json').read_bytes() == (STAGE / 'retention-manifest.json').read_bytes()
            and retention['originals_before'] == retention['originals_after'], 'retention readback differs')
    stamps = {r['path']: r for r in retention['originals_before']}
    archive_path = PRIVATE / 'originals-without-credentials.zip'
    require(sha(archive_path.read_bytes()) == retention['archive_sha256'] == public['private_archive_sha256'], 'private archive digest differs')
    members = retention['original_members']
    require(len(members) == 2304, 'retained member count differs')
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None and archive.namelist() == [r['path'] for r in members], 'private member inventory differs')
        for row in members:
            original = Path(row['origin'])
            raw = archive.read(row['path'])
            require(sha(raw) == row['sha256'] and len(raw) == row['bytes'] and original.read_bytes() == raw
                    and original.stat().st_mtime_ns == stamps[row['path']]['mtime_ns'], 'private member or original differs')
    graph = read(STAGE / 'artifact-view/graph.json')
    nodes = {n['descriptor_digest']: n for n in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) == 212 and len(graph['edges']) == 311 and len(graph['stage_bindings']) == 1,
            'artifact view denominator differs')
    expected = {(n['descriptor_digest'], parent, 'catalogue_parent') for n in nodes.values() for parent in n['parents']}
    require(expected == {(e['from'], e['to'], e['kind']) for e in graph['edges']}
            and all(parent in nodes and nodes[child]['stage_id'] == nodes[parent]['stage_id'] for child, parent, _ in expected),
            'graph parent index differs from actual descriptor parents')
    producer = read(STAGE / 'producer-source-afterrun-manifest.json')
    require(producer['source_view_graph_sha256'] == sha((STAGE / 'artifact-view/graph.json').read_bytes()), 'producer view binding differs')
    with zipfile.ZipFile(STAGE / 'producer-source-afterrun.zip') as archive:
        require(archive.testzip() is None and set(archive.namelist()) == {r['zip_path'] for r in producer['sources']}, 'producer source members differ')
        require(len(producer['sources']) == 9, 'producer source count differs')
        bound = set()
        for row in producer['sources']:
            raw = archive.read(row['zip_path'])
            require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'producer source bytes differ')
            for digest in row['descriptor_digests']:
                source = nodes[digest]['producer_source']
                require(source == {'path': row['source_path'], 'sha256': row['sha256'], 'bytes': row['bytes']}, 'descriptor producer differs')
                bound.add(digest)
        require(bound == set(nodes), 'producer snapshot does not cover the indexed descriptors')
    staging_files = [p for p in sorted(STAGE.rglob('*')) if p.is_file()]
    staged = {p.relative_to(STAGE).as_posix(): p.read_bytes() for p in staging_files}
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for name, raw in staged.items():
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        require(target.read_bytes() == raw and (STAGE / name).read_bytes() == raw, 'published copy differs')
    shutil.copyfile(__file__, DEST / 'publish_c5_probe_archive_r1.py')
    (DEST / 'README.md').write_text('''# 一次完整模块链的产物追溯实例

这次工程探针执行了一个 history 构建和一个 target，覆盖 M1–M9 的相应阶段。
它使用 11 次合成 solver 调用与实际 Docker，没有运行 evaluator。冻结计划含
46 个构建和 118 个目标；这次探针没有执行完整 C5 网格，也没有真实效果结论。

从 [逐产物索引](artifact-view/graph.json) 可以定位到每个描述符的原始文件和
行号、输入父引用、源码、配置和输出摘要。索引含 212 个节点、311 条目录父引用
及一条明确的 history→target 构建绑定；父引用不自动等于科学支持关系。

| 模块 | history 节点 | target 节点 | 保留的状态 |
| --- | ---: | ---: | --- |
| P0 | 1 | 1 | 冻结运行入口 |
| M1 | 1 | 1 | 产生 |
| M2 | 14 | 14 | 每阶段包含一条撤回记录 |
| M3 | 6 | 7 | 产生 |
| M4 | 2 | 2 | 产生 |
| M5 | 7 | 7 | 产生 |
| M6 | 14 | 14 | 产生 |
| M7 | 8 | 8 | 产生 |
| M8 | 13 | 14 | history 未启用；target 产生 |
| M9 | 8 | 0 | 只在 history 构建阶段运行 |
| 未归属模块的 trace | 34 | 36 | 保留 uncovered 标记 |

[原件保留清单](retention-manifest.json) 对应私有 ZIP 的 2,304 个成员，保存来源、
摘要、大小和修改时间；凭据及 reparse 路径单独排除。私有档案位于
`E:/_ryanDev/AI/research-loop-modular/retained-private-evidence/c5-headless-runtime-probe-r1/originals-without-credentials.zip`。
九份 [生产源码副本](producer-source-afterrun-manifest.json) 与这 212 个描述符的
源码摘要吻合。公开副本和私有成员已读回比对，原始字节和修改时间保持不变。

旧失败报告与成功报告分别保留。首次收集失败没有现存 basetemp；早期各次
源码快照缺失，现有源码副本只证明运行后内容吻合，不证明全程冻结。
[原始运行说明](c5-headless-runtime-probe-r1-receipt.md)、[暂存清单](public-manifest.json)
和 [补充清单](supplement-manifest.json) 均保持原样。该实例没有打开 VAL；
所有优化仍仅能使用 TRAIN，独立验收及全部问题、组合实验另有完整分母。
''', encoding='utf-8')
    files = [{'path': p.relative_to(DEST).as_posix(), 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
             for p in sorted(DEST.rglob('*')) if p.is_file()]
    delivery = {'schema': 'c5-probe-delivery-v1', 'files': files, 'private_archive': str(archive_path),
        'private_archive_sha256': public['private_archive_sha256'], 'private_members_verified': 2304,
        'original_bytes_and_mtimes_unchanged': True, 'producer_sources_bound': 9,
        'view_nodes': 212, 'catalogue_parent_edges': 311, 'outer_stage_bindings': 1,
        'source_scope': 'after-run matching snapshot only', 'scientific_effectiveness_proven': False}
    (DEST / 'delivery-manifest.json').write_bytes((json.dumps(delivery, indent=2) + '\n').encode())
    require(read(DEST / 'delivery-manifest.json') == delivery, 'delivery manifest readback differs')
    print(json.dumps({'destination': str(DEST), 'files': len(files), 'private_members': 2304,
                     'delivery_manifest_sha256': sha((DEST / 'delivery-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__': main()
