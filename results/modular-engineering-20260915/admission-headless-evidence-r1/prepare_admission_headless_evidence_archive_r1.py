"""Archive only natively joined frozen checks; retain failed attempts unchanged."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/admission-headless-evidence-r1'
PRIVATE = BASE / 'retained-private-evidence/admission-headless-evidence-r1'
RUNS = [
    ('observation-r1', 'scorer-finalization-evidence-check-r1', '2b13a3588b557f66f8ad6f96cbdf366167c90e94', 53562),
    ('observation-r2', 'scorer-finalization-evidence-check-r2', '9917d13263f116c52b20ae49954bebedef7b876f', 6690),
    ('combined-r1', 'admission-headless-evidence-integration-r1', '6467c3d5617f674877338b391db1a19a527bd4ae', 95917),
    ('combined-followup-r1', 'admission-headless-evidence-followup-r1', 'c2aa74d444473d37576f00aed8b1231c2dd32768', 2311),
    ('m2-projection-r1', 'm2-typed-projection-check-r1', 'fff899a4f52aab68b73d464857f5ae2980a4cb48', 7796),
    ('root-integration-r1', 'module-provenance-root-integration-r1', 'a0ec428d725a54f4d202e322958f13b5bb03d9a1', 94226),
]


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def stamp(path): return {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns}
def write(path, body):
    with path.open('xb') as output:
        output.write((json.dumps(body, indent=2, ensure_ascii=True) + '\n').encode())


def main():
    assert not DEST.exists() and not PRIVATE.exists()
    helper = WORK / 'prepare_headless_lineage_full4_archive_r1.py'
    spec = importlib.util.spec_from_file_location('retention', helper)
    retention = importlib.util.module_from_spec(spec); spec.loader.exec_module(retention)
    copies = []
    private_rows = []
    summaries = []
    for label, name, commit, session_id in RUNS:
        prefix = WORK / name
        before = read(WORK / (name + '-before.json'))
        closed = read(WORK / (name + '-closed.json'))
        members = read(WORK / (name + '-source-members.json'))
        joined = read(WORK / (name + '-native-join.json'))
        started = read(WORK / (name + '-native-start.json'))
        assert started.get('result', started)['session_id'] == session_id
        assert joined['schema'] == 'native-session-join-v1' and joined['native_session_id'] == session_id
        assert joined['source_commit'] == commit and 'session_id' not in joined['result']
        assert type(joined['result']['exit_code']) is int and joined['result']['exit_code'] == closed['exit_code']
        assert before['commit'] == closed['commit'] == members['commit'] == commit
        assert before['source_before'] == closed['source_after'] and closed['source_unchanged'] is True
        assert closed['source_count'] == len(before['source_before']) and closed['new_paid_calls'] == 0
        report = WORK / (name + '.xml')
        assert sha(report.read_bytes()) == closed['report_sha256']
        suites = list(ET.parse(report).getroot().iter('testsuite'))
        assert closed['junit'] == {k: sum(int(s.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
        archive = WORK / (name + '-sources.zip')
        assert sha(archive.read_bytes()) == members['archive_sha256']
        assert before['source_before'] == {r['path']: r['sha256'] for r in members['members']}
        with zipfile.ZipFile(archive) as source:
            assert source.testzip() is None and source.namelist() == [r['path'] for r in members['members']]
            for row in members['members']:
                raw = source.read(row['path'])
                assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
        copies.extend(WORK / (name + suffix) for suffix in
            ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml', '.log', '-native-start.json', '-native-join.json'))
        files = sorted(retention.regular_files(prefix))
        private_rows.extend((label + '/' + p.relative_to(prefix).as_posix(), p) for p in files)
        summaries.append({'label': label, 'prefix': str(prefix), 'source_commit': commit,
            'native_session_id': session_id, 'native_exit_code': joined['result']['exit_code'],
            'junit': closed['junit'], 'source_count': closed['source_count'], 'source_unchanged': True,
            'report_sha256': closed['report_sha256'], 'wall_seconds': closed['wall_seconds'],
            'retained_noncredential_files': len(files)})
    reports = [WORK / name for name in ('current-headless-scenario-integration-gap-r1.md',
        'current-provenance-semantic-boundary-r1.md', 'typed-artifact-relations-next-step-r1.md',
        'typed-artifact-relations-next-step-r2.md',
        'grok-next-discriminating-diagnostic-r1.md')]
    copies.extend(reports)
    all_inputs = sorted({*copies, helper, Path(__file__), *(p for _, p in private_rows)})
    initial = {str(p): stamp(p) for p in all_inputs}
    PRIVATE.mkdir(parents=True)
    private_zip = PRIVATE / 'originals-without-credentials.zip'
    rows = retention.add_zip(private_zip, ((name, p.read_bytes(), str(p)) for name, p in private_rows))
    with zipfile.ZipFile(private_zip) as archive:
        assert archive.testzip() is None and archive.namelist() == [r['path'] for r in rows]
        for row in rows:
            raw = archive.read(row['path'])
            assert sha(raw) == row['sha256'] == initial[row['origin']]['sha256'] and len(raw) == row['byte_count']
    assert initial == {str(p): stamp(p) for p in all_inputs}
    write(PRIVATE / 'retention-manifest.json', {'schema': 'admission-headless-evidence-retention-v1',
        'archive': str(private_zip), 'archive_sha256': sha(private_zip.read_bytes()), 'members': rows,
        'inputs_before': initial, 'inputs_after': initial,
        'excluded_credentials': retention.EXCLUSIONS, 'pruned_reparse_paths': sorted(retention.PRUNED_LINKS)})
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    copies.extend([Path(__file__), PRIVATE / 'retention-manifest.json'])
    assert len({p.name for p in copies}) == len(copies)
    for path in copies:
        shutil.copyfile(path, DEST / path.name)
        assert (DEST / path.name).read_bytes() == path.read_bytes()
    shutil.copyfile(helper, DEST / 'retention-helper-source.py')
    summary = {'schema': 'admission-headless-evidence-checkpoint-v1', 'runs': summaries,
        'originals_bytes_and_mtimes_unchanged': True, 'retained_noncredential_files': len(rows),
        'real_model_calls': 0, 'paid_api_calls': 0, 'validation_access': False,
        'scientific_effectiveness_proven': False,
        'read_only_design_reports_are_not_implementation': True,
        'observation_text_is_not_wire_bytes': True,
        'whole_history_rewrite_without_external_anchor_detected': False}
    write(DEST / 'summary.json', summary)
    (DEST / 'README.md').write_text('''# 模块组合评分封存与消费端观察

本归档保存逐次冻结检查及其 native 工具终态。这些检查的输入与模型/账户响应均为合成
材料，未调用真实模型、付费 API 或 VAL。实际 stdio 和 Docker 的执行证据只证明相应工程入口。

首次观察接口检查为 29 项通过。第二次追加检查为 12 项中 1 项失败：测试的有限模拟
ID 序列在第二次被拒绝的读取前耗尽，报 StopIteration。原失败、源码和原件保持原状；
后续改成不重复的充足模拟 ID。合并检查退出 1：46 项中 44 项通过、2 项测试接线失败。
其中实际 stdio/Docker 的完整 16 格控制器检查通过：48 次合成 solver 和 16 次合成
evaluator 调用、签名封存及有序回执均被检查。两项失败分别为漏传冻结 scorer 配置、
以及测试没有真正构造它声称要拒绝的错误配置签名封存，原始失败保持可查。
仅修复这两处测试后，45 项非网格检查全部通过；没有重复执行完整 16 格网格。
M2 关系读取与已有语义重放的 15 项检查另行通过。合入后的独立标签隔离和接线
检查数量及源码绑定见 summary.json，各批执行不能合并成独立科学样本数。

消费端在解析和验签前记录实际文本层返回，日志链和当前客户端锚点检测篡改与尾删。
文本包装器的换行转换意味着这些不是管道原始字节。拒绝记录写失败时，上层仍保留原
核验异常；签名评分与完整 panel 的门槛没有因记录失败而放宽。

admission-prediction-exploration 的显式 native v4 单独声明 evaluator。所有评分后保留
签名封存，再用冻结 scorer 配置和 authority/provider/有序回执独立核验；部分封存保留
可确认的 MAIN 用量下界，但不能作为完整组合比较。已知 MAIN 不等于未知标题用量或
所有机会的结算总额。

附带的只读盘点和关系设计是其各自源码基线上的报告，不能代替实现或验证。通用目录
父引用仍不等于已认证语义边；新消费观察也尚未全部注册为模块目录节点。全部 48 个
问题、既定单模块及组合实验、完整 C5 和独立 VAL 验收各自保留原成功要求。
盘点 current-headless-scenario-integration-gap-r1.md 将旧 NATIVE_SCHEMAS 的数量写为
11；对应源码实际为 13。此处补充纠正，历史报告字节保留。关系设计 r1 的新 sidecar
建议已由 r2 的纯读取方案取代：实现重用现有 M2 语义边，要求封存和原语义重放，
检测读取期间的目录变化，结果保留旧语义读取器与新投影读取器的源码摘要。
撤回查询只列明明确的撤回对象和观察记录；下游整体范围仍未知，不推导传递因果。

源 ZIP、JUnit、工具开始与终态、逐文件哈希和私有非凭据原件清单一并保存。
日志或 JUnit 中的格式、失败信息及时间戳没有为了展示而重写。
''', encoding='utf-8')
    manifest = {'schema': 'published-files-v1', 'files': [
        {'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]}
    write(DEST / 'published-manifest.json', manifest)
    saved = read(DEST / 'published-manifest.json')
    assert saved == manifest
    assert {r['path'] for r in saved['files']} == {p.name for p in DEST.iterdir() if p.name != 'published-manifest.json'}
    for row in saved['files']:
        raw = (DEST / row['path']).read_bytes()
        assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    assert initial == {str(p): stamp(p) for p in all_inputs}
    print(json.dumps({'destination': str(DEST), 'summary': summary,
        'published_manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__': main()
