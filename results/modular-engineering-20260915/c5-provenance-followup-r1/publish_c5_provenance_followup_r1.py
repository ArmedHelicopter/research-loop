"""Verify and retain the closed probe cross-index without changing its graph."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
ROOT = BASE / 'artifact-evidence-provenance'
ORIGINAL = ROOT / 'results/modular-engineering-20260915/c5-headless-runtime-probe-r1'
DEST = ROOT / 'results/modular-engineering-20260915/c5-provenance-followup-r1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def main():
    assert not DEST.exists()
    graph_path = ORIGINAL / 'artifact-view/graph.json'
    graph_raw = graph_path.read_bytes()
    graph = json.loads(graph_raw)
    audit = read(WORK / 'c5-probe-uncovered-trace-audit-r2.json')
    fields = read(WORK / 'c5-builder-trace-field-crosscheck-r1.json')
    source_root = Path(graph['source_root'])
    assert audit['graph'] == {'sha256': sha(graph_raw), 'bytes': len(graph_raw)}
    assert Path(audit['source_root']) == Path(fields['source_root']) == source_root
    assert audit['original_journals_before'] == audit['original_journals_after']
    assert fields['inputs_before'] == fields['inputs_after']
    expected = {r['path']: r for r in [*audit['original_journals_before'], *fields['inputs_before']]}
    for name, row in expected.items():
        assert {'path': name, **stamp(source_root / name)} == row
    nodes = {n['descriptor_digest']: n for n in graph['nodes']}
    assert len(nodes) == 212
    uncovered = {key: n for key, n in nodes.items() if n['coverage'] == 'uncovered'}
    assert len(uncovered) == 70 and len(audit['items']) == 70
    assert {r['descriptor_digest'] for r in audit['items']} == set(uncovered)
    journals = {name: [json.loads(line) for line in (source_root / name).read_bytes().splitlines()]
                for name in {n['journal_path'] for n in uncovered.values()}}
    for item in audit['items']:
        node = uncovered[item['descriptor_digest']]
        assert all(item[k] == node[k] for k in ('journal_path', 'journal_line', 'stage_id'))
        row = journals[node['journal_path']][node['journal_line'] - 1]
        assert row['descriptor_digest'] == item['descriptor_digest']
        assert row['descriptor']['payload']['canonical']['stage'] == item['trace_stage']
        actual = sorted((n['descriptor_digest'], n['module'], n['kind'], n['status'])
                        for n in nodes.values() if node['descriptor_digest'] in n['parents'] and n['module'] not in (None, 'P0'))
        declared = sorted((n['descriptor_digest'], n['module'], n['kind'], n['status'])
                          for n in item['direct_specialized_descriptor_links'])
        assert actual == declared
    counts = dict(Counter(r['classification'] for r in audit['items']))
    assert counts == {'has_direct_catalogue_reference': 52, 'generic_scheduler_or_model_io_further_review': 16,
                      'no_direct_catalogue_reference_further_review': 2}

    history_journal = next(name for name in journals if name == fields['inputs_before'][0]['path'])
    rows = journals[history_journal]
    descriptors = {}
    for key, item in fields['descriptor_records'].items():
        row = rows[item['journal_line'] - 1]
        assert row['descriptor_digest'] == item['descriptor_digest']
        descriptors[key] = row['descriptor']['payload']['canonical']
    history = (source_root / history_journal).parent.parent
    request = descriptors['c4_builder_request']['data']
    selection = descriptors['m9_builder_selection']
    subjects = descriptors['m9_builder_subjects']
    candidate = read(history / 'candidate.json')
    terminal_raw = (history / 'm9-build-terminal.json').read_bytes()
    terminal = json.loads(terminal_raw)
    candidate_digest = sha(canonical(candidate))
    assert request['builder'] == selection['builder']
    assert request['parent'] == subjects['parent_digest'] == sha(canonical(subjects['parent']))
    assert request['search_cost'] == subjects['search_cost'] == 1
    assert descriptors['c4_build_terminal']['data']['candidate_digest'] == candidate_digest
    assert descriptors['m9_candidate']['canonical'] == candidate
    assert read(history / 'receipt.json')['candidate_digest'] == candidate_digest
    assert descriptors['m9_build_terminal']['file'] == 'm9-build-terminal.json'
    assert descriptors['m9_build_terminal']['sha256'] == sha(terminal_raw)
    assert descriptors['m9_build_terminal']['canonical']['status'] == terminal['status'] == 'succeeded'
    assert len(fields['field_crosschecks']) == 9 and all(r['equal'] is True for r in fields['field_crosschecks'])

    with zipfile.ZipFile(ORIGINAL / 'producer-source-afterrun.zip') as archive:
        member = fields['reconstruction_source']['archived_probe_copy']['path']
        archived_source = archive.read(member)
    current_source = (ROOT / 'research_loop/modular/full_loo_driver.py').read_bytes()
    assert sha(archived_source) == fields['reconstruction_source']['archived_probe_copy']['sha256']
    assert sha(current_source) == fields['reconstruction_source']['current_root_source']['sha256']
    assert archived_source != current_source
    assert archived_source.replace(b'\r\n', b'\n') == current_source.replace(b'\r\n', b'\n')
    copies = [WORK / (stem + suffix) for stem in ('c5-probe-uncovered-trace-audit-r1',
        'c5-probe-uncovered-trace-audit-r2', 'c5-builder-trace-field-crosscheck-r1') for suffix in ('.json', '.md')]
    before = {str(p): stamp(p) for p in [graph_path, *copies]}
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for path in [*copies, Path(__file__)]:
        shutil.copyfile(path, DEST / path.name)
        assert path.read_bytes() == (DEST / path.name).read_bytes()
    receipt = {'schema': 'c5-provenance-followup-root-verification-v1', 'graph_sha256': sha(graph_raw),
        'nodes': 212, 'uncovered_trace_nodes': 70, 'classification_counts': counts,
        'recomputed_reported_field_equalities': 9, 'parent_record_digest_also_checked': True,
        'source_raw_bytes_identical': False, 'source_diff_only_crlf_lf': True,
        'source_old_sha256': sha(archived_source), 'source_current_sha256': sha(current_source),
        'historical_graph_changed': False, 'new_semantic_parent_edges_claimed': False,
        'scientific_effectiveness_proven': False, 'model_calls': 0, 'validation_access': False,
        'input_files': list(expected.values()), 'originals_bytes_and_mtimes_unchanged': True}
    (DEST / 'root-verification.json').write_bytes(json.dumps(receipt, indent=2).encode() + b'\n')
    (DEST / 'README.md').write_text('''# C5 产物追溯实例的逐项核对

本记录补充[原 212 节点实例](../c5-headless-runtime-probe-r1/README.md)。原图和原目录保持不变。

70 条通用 trace 已逐项回读：52 条有模块描述符直接引用，16 条是待进一步核对的通用运行/模型 IO，另外 2 条是构建请求与终态。直接引用可能来自默认的“附着到最近事件”，因此这些分组不提升模块覆盖、语义消费或因果关系。r2 修正 r1 的过强归类名称，两个版本均保留。

[M9 字段交叉索引](c5-builder-trace-field-crosscheck-r1.md) 将两条构建 trace 的 builder、父候选、搜索成本和候选摘要定位到已有 M9 选择、主体、候选、终态与阶段回执。根审查重新计算了报告的九项相等关系，并检查父候选原文摘要；这不创建历史上不存在的目录边，也不代替完整阶段验收。

根审查另外确认，当前 driver 与归档源码的差异仅为 CRLF/LF。各自原始字节和摘要仍分开保留，不用归一化内容冒充原冻结源码。原图、两份日志及交叉索引用到的五份原件在回查前后字节和修改时间一致。

这里没有新模型、API、Docker 或 VAL 调用。完整 C5、真实模块效果和独立验收各有自己的终态要求。
''', encoding='utf-8')
    assert before == {str(p): stamp(p) for p in [graph_path, *copies]}
    for name, row in expected.items():
        assert {'path': name, **stamp(source_root / name)} == row
    manifest = {'schema': 'published-files-v1', 'files': [
        {'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]}
    (DEST / 'published-manifest.json').write_bytes(json.dumps(manifest, indent=2).encode() + b'\n')
    for row in read(DEST / 'published-manifest.json')['files']:
        raw = (DEST / row['path']).read_bytes()
        assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    print(json.dumps({'destination': str(DEST), 'manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes()),
                      'root_verification': receipt}), flush=True)


if __name__ == '__main__':
    main()
