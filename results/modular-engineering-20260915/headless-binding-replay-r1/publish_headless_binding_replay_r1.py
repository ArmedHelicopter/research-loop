"""Retain frozen binding regressions, including the original failed test wiring."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
ROOT = BASE / 'artifact-evidence-provenance'
DEST = ROOT / 'results/modular-engineering-20260915/headless-binding-replay-r1'
PRIVATE = BASE / 'retained-private-evidence/headless-binding-replay-r1'
RUNS = [
    ('agent-r1', 'headless-binding-replay-r1-check', 'aa2f2c787a3479553a0e794f994d2ecf0d45b3ca', 30, 0),
    ('agent-r2', 'headless-binding-replay-r1-check-r2', '371f3738c8c8ce161a338b70cc3258520d06f915', 30, 0),
    ('agent-r3', 'headless-binding-replay-r1-check-r3', 'bc2783c9512b19e51871b61ed1aea7a9d75b90af', 32, 2),
    ('agent-r4', 'headless-binding-replay-r1-check-r4', 'ece291c7632609a36e727997cdf16b25db228354', 33, 0),
    ('root', 'headless-binding-replay-root-r1', '62ea4788b0fda4c3fb506c1e2b5a9e504e7a08dd', 102, 0),
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('xb') as out:
        out.write(json.dumps(value, indent=2).encode() + b'\n')


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def main():
    assert not DEST.exists() and not PRIVATE.exists()
    join_path = WORK / 'headless-binding-replay-root-r1-native-join.json'
    joined = read(join_path)
    assert joined['schema'] == 'native-session-join-v1' and joined['native_session_id'] == 55494
    assert joined['prefix'] == (WORK / RUNS[-1][1]).as_posix() and joined['source_commit'] == RUNS[-1][2]
    assert joined['result']['exit_code'] == 0 and 'session_id' not in joined['result']
    helper_path = WORK / 'prepare_headless_lineage_full4_archive_r1.py'
    spec = importlib.util.spec_from_file_location('retention', helper_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    source_files = []
    private_rows = []
    summaries = []
    for label, name, commit, test_count, failures in RUNS:
        prefix = WORK / name
        before = read(WORK / (name + '-before.json'))
        closed = read(WORK / (name + '-closed.json'))
        members = read(WORK / (name + '-source-members.json'))
        junit = WORK / (name + '.xml')
        assert before['commit'] == closed['commit'] == members['commit'] == commit
        assert before['source_before'] == closed['source_after'] and closed['source_unchanged'] is True
        assert closed['source_count'] == 785 and closed['new_paid_calls'] == 0
        assert closed['junit'] == {'tests': test_count, 'failures': failures, 'errors': 0, 'skipped': 0}
        assert closed['exit_code'] == (1 if failures else 0)
        assert sha(junit.read_bytes()) == closed['report_sha256']
        cases = list(ET.parse(junit).getroot().iter('testcase'))
        assert len(cases) == test_count and len({(c.get('classname'), c.get('name')) for c in cases}) == test_count
        if failures:
            failed = [c.find('failure').get('message') for c in cases if c.find('failure') is not None]
            assert failed == ["AttributeError: 'FrozenTrainProviderLedgerV2' object has no attribute 'original'"] * 2
        archive_path = WORK / (name + '-sources.zip')
        assert sha(archive_path.read_bytes()) == members['archive_sha256']
        assert {r['path']: r['sha256'] for r in members['members']} == before['source_before']
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None and archive.namelist() == [r['path'] for r in members['members']]
            for row in members['members']:
                raw = archive.read(row['path'])
                assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
        external = [WORK / (name + suffix) for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml')]
        if (WORK / (name + '.log')).exists():
            external.append(WORK / (name + '.log'))
        source_files.extend(external)
        files = sorted(helpers.regular_files(prefix))
        private_rows.extend((label + '/' + p.relative_to(prefix).as_posix(), p) for p in files)
        summaries.append({'label': label, 'source_commit': commit, 'junit': closed['junit'],
            'source_count': closed['source_count'], 'source_unchanged': True, 'wrapper_recorded_exit_code': closed['exit_code'],
            'wall_seconds': closed['wall_seconds'], 'retained_noncredential_files': len(files),
            'original_native_tool_join': 'retained_exit_0' if label == 'root' else 'not_retained_unproven'})
    extra = [join_path, WORK / 'headless-binding-replay-r1-execution-join-r1.json',
             WORK / 'headless-binding-replay-r1-execution-join-correction-r2.json',
             WORK / 'headless-binding-replay-child-process-observation-r1.json']
    source_files.extend(extra)
    all_inputs = sorted({*source_files, *(p for _, p in private_rows)})
    before_all = {str(p): stamp(p) for p in all_inputs}
    PRIVATE.mkdir(parents=True)
    archive_path = PRIVATE / 'originals-without-credentials.zip'
    retained = helpers.add_zip(archive_path, ((name, p.read_bytes(), str(p)) for name, p in private_rows))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None and archive.namelist() == [r['path'] for r in retained]
        for row in retained:
            raw = archive.read(row['path'])
            assert sha(raw) == row['sha256'] == before_all[row['origin']]['sha256'] and len(raw) == row['byte_count']
    assert before_all == {str(p): stamp(p) for p in all_inputs}
    retention = {'schema': 'headless-binding-replay-retention-v1', 'archive': str(archive_path),
        'archive_sha256': sha(archive_path.read_bytes()), 'members': retained,
        'inputs_before': before_all, 'inputs_after': before_all,
        'excluded_credentials': helpers.EXCLUSIONS, 'pruned_reparse_paths': sorted(helpers.PRUNED_LINKS)}
    write(PRIVATE / 'retention-manifest.json', retention)
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    copies = [*source_files, Path(__file__), PRIVATE / 'retention-manifest.json']
    assert len({p.name for p in copies}) == len(copies)
    for p in copies:
        shutil.copyfile(p, DEST / p.name)
        assert p.read_bytes() == (DEST / p.name).read_bytes()
    shutil.copyfile(helper_path, DEST / 'retention-helper-source.py')
    assert (DEST / 'retention-helper-source.py').read_bytes() == helper_path.read_bytes()
    summary = {'schema': 'headless-binding-replay-checkpoint-v1', 'authoritative_source_commit': RUNS[-1][2],
        'authoritative_native_session_joined': 55494, 'authoritative_junit': summaries[-1]['junit'], 'runs': summaries,
        'full_original_audits_per_phase_binding_before': 3, 'full_original_audits_per_phase_binding_after': 2,
        'fresh_original_reads_per_consumer_retained': True, 'cross_consumer_cache_added': False,
        'wall_clock_speedup_measured': False, 'retained_noncredential_files': len(private_rows),
        'originals_bytes_and_mtimes_unchanged': True, 'model_calls': 0, 'paid_api_calls': 0,
        'validation_access': False, 'scientific_effectiveness_proven': False}
    write(DEST / 'summary.json', summary)
    (DEST / 'README.md').write_text('''# TRAIN provider 原件重复读取修复

同次 phase 消费中的完整原件审计由三遍减为两遍。每次独立消费仍重新读取当前原件，公共原件入口也独立复核；没有跨消费缓存。错误参数、原件篡改和不完整用量继续拒绝有效消费并保留失败/未知状态。这里测的是读取遍数，没有测出整场 C5 的加速比例。

主工作树冻结提交 `62ea4788b0fda4c3fb506c1e2b5a9e504e7a08dd` 通过 102 项检查，覆盖新 headless seam、旧 Grok/Codex provider、调用前检查、失败用量与标签隔离。785 份源码/文档前后字节一致。原 native session 55494 已直接 join，退出码 0。模型与账户响应均为合成输入，没有真实模型、付费 API 或 VAL 调用。

## 原检查记录的解释

四轮子代理工件依次是 30/30、30/30、30/32、33/33；各自冻结源码和原始 JUnit 均保留。第三轮的两项失败都是同一个测试接线错误：对 FrozenTrainProviderLedgerV2 使用不存在的 `.original`。phase 错误布尔值绕开 poison 的问题另由代码审查发现，不是第二条 JUnit 失败的原因。

子代理最初的 execution-join-r1 把 closed/JUnit 当成工具 join 证据，这一解释无效；correction-r2 保留了更正。四轮原 native 工具终态没有保留下来，因此 join 仍未获证实。也不能从捕获结果缺失推断工具从未返回 session ID。原件中能确认的是 wrapper 自己记录的结束状态和 JUnit，不据此补造工具回执。当前未发现相应 Python 进程，仅是时点观察。主工作树这轮保留了真实 native join，是最终集成检查依据。

全部五轮非凭据原件按独立目录保留，源 ZIP、JUnit、失败、排除清单及实际字节和时间戳核验见 manifest。旧 C5 长运行继续使用它原来的冻结源码，本次不重启、不改写或追认其结果。工程通过不等于模块 benchmark 效果、完整研究实验或独立验收完成。
''', encoding='utf-8')
    assert before_all == {str(p): stamp(p) for p in all_inputs}
    manifest = {'schema': 'published-files-v1', 'files': [
        {'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(DEST.iterdir())]}
    write(DEST / 'published-manifest.json', manifest)
    for row in read(DEST / 'published-manifest.json')['files']:
        raw = (DEST / row['path']).read_bytes()
        assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    print(json.dumps({'destination': str(DEST), 'summary': summary,
        'published_manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}), flush=True)


if __name__ == '__main__':
    main()
