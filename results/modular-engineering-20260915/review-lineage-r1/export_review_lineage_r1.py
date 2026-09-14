"""Export declared consumption edges from one independently checked fixture."""
import hashlib
import json
from pathlib import Path
import sys

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
RUNTIME = BASE / 'work/review-artifacts-root-r2/test_actual_m4_freeze_payload_0/original'
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.review_scenario_artifacts import verify_review_artifacts
from test_modular_review_scenarios import task, controls

def tree():
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in RUNTIME.iterdir() if p.is_file()}

before = tree()
public = task('blade')
verified = verify_review_artifacts(RUNTIME, task=public, controls=controls(public),
                                  experiment_id='Q4.1', variant='roles').data()
assert verified['status'] == 'succeeded' and tree() == before
input_record = FrozenRecord.from_dict(json.loads(before['review-inputs.json'][0]))
rows = [FrozenRecord(line) for line in before['review-attempts.jsonl'][0].decode().splitlines()]
nodes = [{'id': input_record.content_hash, 'event': 'frozen_inputs'}]
edges = []
for row in rows:
    data = row.data()
    nodes.append({'id': row.content_hash, 'event': data['event'], 'sequence': data['sequence']})
    assert data['parent_relation'] == 'consumes'
    edges.extend({'from': parent, 'to': row.content_hash, 'relation': 'consumes'} for parent in data['parents'])
ids = {row['id'] for row in nodes}
assert len(ids) == len(nodes) and all(edge['from'] in ids and edge['to'] in ids for edge in edges)
body = {'schema': 'review-lineage-view-v1', 'fixture_only': True, 'runtime_source': str(RUNTIME),
    'source_archive': 'review-scenario-artifacts-r1/test_actual_m4_freeze_payload_0-original.zip',
    'verification': verified, 'nodes': nodes, 'edges': edges,
    'original_files': {name: hashlib.sha256(raw).hexdigest() for name, (raw, _) in before.items()},
    'scientific_validated': False, 'scope': 'actual declared consumption edges, not temporal proximity or scientific causal support'}
out = ROOT/'results/modular-engineering-20260915/review-lineage-r1'
out.mkdir(parents=True, exist_ok=False)
(out/'.gitattributes').write_bytes(b'* -text\n')
with (out/'lineage.json').open('xb') as stream: stream.write((json.dumps(body, indent=2)+'\n').encode())
names = {row['id']: 'n'+str(index) for index, row in enumerate(nodes)}
diagram = ['flowchart TD']
for node in nodes: diagram.append(f'  {names[node["id"]]}["{node["event"]}<br/>{node["id"][:12]}"]')
for edge in edges: diagram.append(f'  {names[edge["from"]]} --> {names[edge["to"]]}')
text = '\n'.join(diagram)+'\n'
with (out/'lineage.mmd').open('x', encoding='utf-8', newline='\n') as stream: stream.write(text)
intro = '''# 一次评审运行的实际产物依赖图

这是 Q4.1 roles 合成工程用例的真实落盘记录，已从调用方独立输入只读重建。
箭头表示该次运行声明并经核验的 consumes 关系；不表示科学因果支持。
时间顺序链没有被当作消费关系画入图中。所有完整摘要与原件哈希在
[lineage.json](lineage.json)，对应原运行 ZIP 见
[原件](../review-scenario-artifacts-r1/test_actual_m4_freeze_payload_0-original.zip)。
读取和导出没有重跑模块、用户回调或模型，原目录字节与 mtime 未变化。
此示例不代表所有模块或跨目录关系已经覆盖。

```mermaid
'''
with (out/'README.md').open('x', encoding='utf-8', newline='\n') as stream: stream.write(intro+text+'```\n')
with (out/'export_review_lineage_r1.py').open('xb') as stream: stream.write(Path(__file__).read_bytes())
assert tree() == before
print(json.dumps({'path': str(out), 'nodes': len(nodes), 'consumption_edges': len(edges), 'source_read_only': True}))
