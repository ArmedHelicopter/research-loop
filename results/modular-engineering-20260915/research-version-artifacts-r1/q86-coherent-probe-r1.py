from pathlib import Path
import json, shutil, sys, traceback
root = Path('E:/_ryanDev/AI/research-loop-modular/research-version-provenance-repair')
sys.path[:0] = [str(root), str(root/'tests')]
from q86_coherent_copy import rewrite
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.research_versions import verify_research_version_artifacts
from research_loop.ontology import ContractError
source = Path('E:/_ryanDev/AI/research-loop-modular/work/q86-repair-dev-r2-temp/pytest/q86-consumer-mutations0/run')
destination = Path('E:/_ryanDev/AI/research-loop-modular/work/q86-coherent-probe-r1')
destination.mkdir(exist_ok=False)
cases = {}
for p in source.rglob('research-version-inputs.json'):
    value = json.loads(p.read_bytes()); cell = value['cell']
    if {'M1','M6'} <= set(cell['runtime_arm']['enabled']): cases.setdefault(cell['variant'], (p.parent,value))
rows = []
for fault in ['child_schema','child_state','transition_from','transition_reason','source_bundle','visible_sources','receipt_scientific','producer_source','run_id']:
    variant = 'conflict' if fault.startswith('transition') else 'malicious_override' if fault=='run_id' else 'pause_new_version'
    original, inputs = cases[variant]; p=destination/fault; shutil.copytree(original,p)
    c=dict(inputs['cell']); c['identity']=DataIdentity.parse(c['identity']); c['runtime_arm']=FrozenRecord.from_dict(c['runtime_arm']); cell=PanelCell(**c)
    kwargs=dict(cell=cell,scenario=FrozenRecord.from_dict(inputs['scenario']), identity=cell.identity,task_digest=cell.task_digest,lock=inputs['lock'],expected_run_id=inputs['run_id'])
    def consume():
        events=tuple(FrozenRecord(line).data() for line in (p/'trace.jsonl').read_text(encoding='utf-8').splitlines())
        return verify_research_version_artifacts(p,events=events,**kwargs)
    try:
        consume(); rewrite(p,fault=fault,identity=cell.identity)
        try: consume()
        except ContractError as exc: rows.append(dict(fault=fault,mechanical_valid=True,rejected=True,reason=str(exc)))
        else: rows.append(dict(fault=fault,mechanical_valid=True,rejected=False))
    except Exception as exc:
        rows.append(dict(fault=fault,mechanical_valid=False,error=repr(exc),traceback=traceback.format_exc()))
(destination/'results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows,indent=2))
sys.exit(0 if all(r.get('mechanical_valid') and r.get('rejected') for r in rows) else 1)
