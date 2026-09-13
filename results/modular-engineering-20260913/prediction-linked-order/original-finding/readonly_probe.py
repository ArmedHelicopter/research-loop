"""Review probe: mutate a private copy only; no model, Docker or scorer calls."""
import sys,json,shutil,hashlib
from pathlib import Path
repo=Path('E:/_ryanDev/AI/research-loop-modular/pred-link')
sys.path[:0]=[str(repo),str(repo/'tests')]
from research_loop.modular.contracts import DataIdentity,PublicTask,FrozenRecord
from research_loop.modular.panel_receipts import PanelCell,RuntimeReceipt
from research_loop.modular.panel_runner import TrainCellResult
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.experiments import ControllerInputs,registry,scenario
from research_loop.modular.benchmark_cell import verified_mechanism_provenance
from research_loop.modular.linked_public_projection import project_linked_public_context
from test_prediction_linked_benchmark import neutral_material
root=Path('E:/_ryanDev/AI/research-loop-modular/work/pred-linked-frozen-r1/prediction-linked-grid0/run')
j=json.loads((root/'controller-attempt.json').read_text(encoding='utf-8'))
raw=next(c for c in j['cell_plan'] if c['coverage_id']=='Q5.3' and c['variant']=='opposite_prediction' and c['arm_id']=='1')
cell=PanelCell(raw['coverage_id'],DataIdentity.parse(raw['identity']),raw['replicate'],raw['variant'],raw['arm_id'],FrozenRecord.from_dict(raw['runtime_arm']),raw['task_digest'],raw['scenario_digest'],raw['package_digest'],raw['scorer_digest'])
original=root/'cells'/FrozenRecord.from_dict(raw).content_hash/'mechanism'
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir() if p.is_file()}
out=Path('E:/_ryanDev/AI/research-loop-modular/work/pred-link-readonly-order-probe')
assert not out.exists();shutil.copytree(original,out)
events=[json.loads(line) for line in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
task_body=next(e['data']['request']['task'] for e in events if e['stage']=='model_request')
task=PublicTask(DataIdentity.parse(task_body['identity']),FrozenRecord.from_dict(task_body['payload']))
material=scenario(registry()[cell.coverage_id],cell.variant,inputs=ControllerInputs(FrozenRecord.from_dict(task.data()),neutral_material(task),FrozenRecord.from_dict(j['compiled_manifest']['budget'])))
assert material.content_hash==cell.scenario_digest
package=CandidatePackage(FrozenRecord.from_dict(j['compiled_manifest']['package_bundle']['packages'][cell.runtime_arm.content_hash]))
row=next(r for r in j['runtime_receipts'] if tuple(r['cell_key'])==cell.key)
def accept(digest):
    runtime=RuntimeReceipt(cell.key,row['status'],out/'trace.jsonl',digest,row['output_digest'],row['failure_reason'])
    result=TrainCellResult(runtime,None,FrozenRecord.from_dict({'review_probe':True}))
    proof=verified_mechanism_provenance(cell=cell,task=task,scenario=material,package=package,mechanism=result)
    return project_linked_public_context(provenance=proof,cell=cell,task=task,scenario=material)
actual=accept(row['trace_digest'])
moved=[e for e in events if e['stage']=='modular_workflow' and e['data']['stage'] in ('stage_1','prediction_artifacts')]
for event in moved:events.remove(event)
final_request=next(e for e in events if e['stage']=='model_request' and e['data']['request']['slot']=='final')
final_response=next(e for e in events if e['stage']=='model_response' and e['data']['request_digest']==final_request['data']['request_digest'])
at=events.index(final_response)+1
events[at:at]=moved
prev=None;lines=[]
for i,event in enumerate(events):
    event['sequence']=i;event['previous']=prev;f=FrozenRecord.from_dict(event);lines.append(f.encoded);prev=f.content_hash
(out/'trace.jsonl').write_text('\n'.join(lines)+'\n',encoding='utf-8')
forged=accept(prev)
assert actual.data()['mechanism_material']==forged.data()['mechanism_material']
assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in original.iterdir() if p.is_file()}
print(json.dumps({'source_commit':'8e235510756c7098051f38e59ff2d41c0b989d91','cell_key':list(cell.key),
    'original_untouched':True,'both_provenance_and_projection_accepted_late_artifacts':True,
    'final_response_sequence':events.index(final_response),'late_artifact_sequences':[events.index(e) for e in moved],
    'copied_trace_sha256':hashlib.sha256((out/'trace.jsonl').read_bytes()).hexdigest(),'copy':str(out)},indent=2))
