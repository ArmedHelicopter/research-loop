"""Publish the unchanged C5 deadline stage and a separately attributed usage observation."""
from pathlib import Path
import hashlib
import json
import shutil

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
STAGE = WORK / 'c5-common-digest-r1-archive-stage-r1'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/c5-common-digest-r1'
def sha(raw): return hashlib.sha256(raw).hexdigest()
assert sha((STAGE / 'manifest.json').read_bytes()) == '6e91b3d044af766a6f72856aa1fc186461b63be10820c1b8559798c49a9aabf2'
usage = WORK / 'c5-common-digest-r1-observed-usage.json'
assert sha(usage.read_bytes()) == 'f7eeb795920d92bdaf9583be70dfac088020c1007a30b8532e5c6012d058fc35'
assert not DEST.exists()
shutil.copytree(STAGE, DEST / 'original-stage')
for path in STAGE.iterdir():
    assert path.is_file() and path.read_bytes() == (DEST / 'original-stage' / path.name).read_bytes()
for name in ('c5-common-digest-r1-observed-usage.json', 'verify_c5_common_digest_r1_archive.py', Path(__file__).name):
    shutil.copyfile(WORK / name, DEST / name)
(DEST / '.gitattributes').write_bytes(b'* -text\n')
(DEST / 'README.md').write_text('''# C5 common digest r1：未完成批次的完整原件保留

冻结源码 `105dfcd321faa3245b9a1605515e1eb147d04c5f` 的工程检查在原截止
2026-09-15 08:56:20.622818+08 后，由既有 watchdog 终止已观察的进程树。
最终 checkpoint 是 46 个 history 构建成功、57 个 target 成功状态、61 个
target 未执行；没有正常 JUnit 或 closed 回执，不能记为完整 C5 检查通过。

[原始闭合记录](original-stage/closure.json)及其整个暂存包逐字节保留。
[后补只读用量观察](c5-common-digest-r1-observed-usage.json)独立绑定原件，
没有改写闭合记录中的未知值：common provider 账本有 572 次合成调用和
6,864 个已知合成 tokens；fixture 的 2 次准备调用另列。所检查根目录没有
评分器 journal，因此评分调用及用量仍为未知，不能由 target 状态推导评分数。

私有保留副本包含 13,516 个运行文件、758,690,037 字节，分为 32 个 ZIP。
成员内容、摘要、原件摘要和 mtime 均独立核对；原始链接没有跟随复制。
其位置及摘要见[私有副本索引](original-stage/runtime-private-inventory.json)。
测试私钥夹具保留在私有副本，不进入公开包。公开源码 ZIP 包含当次 706 份
源码与文档原始字节；这些证据不代表真实模型效果、正式校准或 VAL 验收。

`original-stage/manifest.json` 描述当时暂存目录；本目录的 `manifest.json`
另绑定发布文件。核验脚本保留原始暂存及私有副本的位置，不修改原件。
''', encoding='utf-8', newline='\n')
rows = []
for path in sorted(DEST.rglob('*')):
    if path.is_file():
        rows.append({'path': path.relative_to(DEST).as_posix(), 'bytes': path.stat().st_size,
                     'sha256': sha(path.read_bytes())})
with (DEST / 'manifest.json').open('x', encoding='utf-8') as stream:
    json.dump({'schema': 'c5-deadline-published-archive-v1', 'manifest_self_excluded': True,
               'original_stage_manifest_sha256': sha((STAGE / 'manifest.json').read_bytes()),
               'files': rows}, stream, indent=2)
print(json.dumps({'target': str(DEST), 'files': len(rows) + 1, 'original_stage_unchanged': True}))
