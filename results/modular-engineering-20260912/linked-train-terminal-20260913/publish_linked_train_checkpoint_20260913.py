"""Publish the preserved terminal attempt without changing earlier raw evidence."""
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'integration'
ARCHIVE = ROOT / 'results/modular-engineering-20260912'
STAGE = BASE / 'work/linked-train-checkpoint-stage-20260913-01'
DEST = ARCHIVE / 'linked-train-terminal-20260913'
old = json.loads((ARCHIVE / 'SHA256.json').read_text(encoding='utf-8'))
assert len(old) == 448 and not DEST.exists()
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip().startswith('7aa349d')
for name, expected in old.items():
    assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == expected, name
assert sum(p.is_file() for p in STAGE.rglob('*')) == 400
origins = json.loads((STAGE / 'origins.json').read_text(encoding='utf-8'))
for name, record in origins.items():
    assert hashlib.sha256((STAGE / name).read_bytes()).hexdigest() == record['sha256'], name
shutil.copytree(STAGE, DEST)
reports = {}
for relative, commit, target in (
    ('work/audit-controller-root-20260913-r1.xml', 'b59bb3e', 'audit-controller-root-b59bb3e.xml'),
    ('work/linked-public-root-20260913-r1.xml', '7aa349d', 'linked-public-root-7aa349d.xml'),
):
    source = ROOT / relative
    raw = source.read_bytes()
    (DEST / target).write_bytes(raw)
    suite = ET.fromstring(raw).find('testsuite')
    stats = {key: suite.attrib[key] for key in ('tests', 'failures', 'errors', 'skipped', 'time')}
    assert all(stats[key] == '0' for key in ('failures', 'errors', 'skipped'))
    reports[target] = {'source': str(source), 'source_commit': subprocess.check_output(
        ['git', 'rev-parse', commit], cwd=ROOT, text=True).strip(), 'sha256': hashlib.sha256(raw).hexdigest(), **stats}
(DEST / 'additional-verification.json').write_text(json.dumps(reports, indent=2) + '\n', encoding='utf-8')
(DEST / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
index = {p.relative_to(ARCHIVE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name != 'SHA256.json'}
assert all(index[name] == expected for name, expected in old.items())
(ARCHIVE / 'SHA256.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
doc = (BASE / 'work/staged-MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md').read_text(encoding='utf-8')
doc = doc.replace('这条接缝还有单独的集成回归。', '源码 `7aa349d` 的公开投影、linked 控制器、评分、选择、求解及标签隔离接缝通过 70 项回归，293.215 秒。')
doc = doc.replace('将归档于', '已归档于')
doc += f'\n归档合计 {len(index)} 个文件：原有 448 个文件逐字节保留，新增 {len(index)-448} 个文件。磁盘与 Git 暂存区的哈希由独立脚本复核。\n'
(ROOT / 'docs/MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md').write_text(doc, encoding='utf-8')
status = ROOT / 'docs/MODULAR-IMPLEMENTATION-STATUS.md'
text = status.read_text(encoding='utf-8')
header = '''## Current terminal training checkpoint (2026-09-13)

The frozen `c3a4b21` linked train attempt is closed: 12 cells, 10 successful
restricted-Docker executions with independent adapted scores, and 2 retained
execution failures. There were 58 provider calls and 935,043 tokens. Selection
is `inconclusive`; dynamic controller metadata affected all 12 cells, so this
attempt is engineering wiring evidence and does not qualify a clean module
effect. No combination pruning, validation acceptance or deployment occurred.
The full 928-test result belongs only to `c3a4b21`. Subsequent focused suites
passed 26 (`a111e1c`), 61 (`718fc84`), 83 (`b59bb3e`) and 70 (`7aa349d`) tests.

Production drivers cover Q1.1–Q1.7, Q2.1/Q2.3/Q2.4, Q3.1 and Q4.1–Q4.5.
All 48 obligations, combinations and the separate Q6.3 phase remain required.
See [MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md](MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md)
for the terminal attempt, failure denominator, public-context repairs and
source-specific evidence. The archive now contains COUNT hash-indexed files.

'''.replace('COUNT', str(len(index)))
text = text.replace('## Current checkpoint (2026-09-13)', header + '## Previous scorer checkpoint (2026-09-13)', 1)
status.write_text(text, encoding='utf-8')
running = ROOT / 'docs/MODULAR-RUNNING.md'
text = running.read_text(encoding='utf-8')
text = text.replace('`panel_runner.run_train_cell()` supports Q1.1–Q1.5, Q2.1, Q3.1 and Q4.1–Q4.5.', '`panel_runner.run_train_cell()` supports Q1.1–Q1.7, Q2.1/Q2.3/Q2.4, Q3.1 and Q4.1–Q4.5.')
text = text.replace('Q1.1–Q1.4 require typed caller material', 'Q1.1–Q1.4 and Q1.6/Q1.7 require typed caller material')
text = text.replace('Typed runtime and optional scorer receipts pass to `PanelReceiptVerifier`.', '''Q2.3/Q2.4 require `audit_receipt_port` and `shadow_execution_port`, with actual
program/input hashes matching the frozen shadow contract. Fixed host checks
remain common to both arms; only M1-on admits the evidence.
Typed runtime and optional scorer receipts pass to `PanelReceiptVerifier`.''')
text += '''
## Terminal linked training attempt and new runs

The first scored linked attempt is preserved, closed and inconclusive; see
[MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md](MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md).
Do not resume or overwrite its directories. Its clean base context did not
prevent dynamic request metadata leakage. A subsequent attempt needs a new
frozen source/configuration, directory, reviewed dynamic public projections
and explicit training-only scoring allocation. Full controller provenance is
retained for verification; the solver receives only the typed public projection.
'''
running.write_text(text, encoding='utf-8')
attributes = ROOT / '.gitattributes'
text = attributes.read_text(encoding='utf-8')
text += '/results/modular-engineering-20260912/linked-train-terminal-20260913/** -whitespace\n'
attributes.write_text(text, encoding='utf-8')
print(json.dumps({'previous_unchanged': len(old), 'new_files': len(index)-len(old), 'total': len(index), 'reports': reports}))
