"""Reread original headless requests, outputs and references without dispatch."""
import hashlib
import json
from pathlib import Path
import sys

work=Path(__file__).parent
name=sys.argv[1]
assert name in ('low-effort','indexed')
tree=work.parent/f'headless-authoring-{name}-runtime'
prep=work/f'headless-authoring-{name}-preparation-r1'
root=work/f'headless-authoring-{name}-run-r1'
sys.path.insert(0,str(tree))
from research_loop.modular.grok_headless_transport import HeadlessResult, verify_headless_request_binding
from research_loop.modular.contracts import FrozenRecord
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from evaluation.modular.diagnostic_material_authoring import validate_authored

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
closure=json.loads((root/'public-parent-closure.json').read_bytes())
assert closure['worker_exit']==0 and not closure['parent_timeout'] and closure['source_unchanged']
assert closure['owned_tree_closed'] and not closure['validation_access']
envelope_path=Path(closure['authoring_envelope']['path'])
assert sha(envelope_path)==closure['authoring_envelope']['sha256']
envelope=json.loads(envelope_path.read_bytes())
outcome_path=Path(closure['public_outcome']['path'])
assert sha(outcome_path)==closure['public_outcome']['sha256']
outcome=json.loads(outcome_path.read_bytes())
frozen=envelope['frozen_files']|{str(envelope_path):sha(envelope_path)}
store=envelope['reference_store']
resolver=FrozenTrainReferenceResolver(Path(store['root']),**{k:store[k] for k in
    ('manifest_sha256','inventory_digest','split_digest')})
rows=[]
for entry,state in zip(envelope['entries'],outcome['authoring_outcomes']):
    assert entry['opportunity_id']==state['opportunity_id']
    task=next(t for t in envelope['tasks'] if t['task_handle']==entry['task_handle'])
    directory=outcome_path.parent/entry['opportunity_id']
    receipt_path=directory/'native/observer-receipt.json'
    row={'opportunity_id':entry['opportunity_id'],'benchmark':task['identity']['benchmark'],
         'authoring_status':state['status'],'native_receipt_present':receipt_path.exists()}
    if receipt_path.exists():
        receipt=FrozenRecord.from_dict(json.loads(receipt_path.read_bytes()))
        response_path=directory/'native/response.private.json'
        response=FrozenRecord.from_dict(json.loads(response_path.read_bytes())) if receipt.data()['accepted'] else None
        result=HeadlessResult(receipt,response)
        context=envelope['native_deployment']['slots'][entry['opportunity_id']]|{
            'executable':envelope['native_deployment']['executable'],'reasoning_effort':envelope['limits']['reasoning_effort']}
        binding=verify_headless_request_binding(result,entry,directory,
            envelope['limits']|{'native_context':context},frozen)
        assert binding.content_hash==state['headless_request_binding_digest']
        assert json.loads((directory/'headless-request-binding.json').read_bytes())==binding.data()
        row.update(native_binding_verified=True,native_binding_accepted=binding.data()['accepted'],
                   usage=binding.data()['usage'],native_receipt_sha256=sha(receipt_path))
        if response is not None:
            reference=resolver(entry['task_handle'],task['identity']['benchmark'])
            assert reference.content_hash==entry['reference_digest']
            try:
                materials=validate_authored(response.data(),reference.data()['references'])
                row.update(material_contract_verified=True,availability={s:sum(m['status']==s for m in materials)
                    for s in ('ready','unresolved_material','not_applicable')})
            except Exception as exc:
                row.update(material_contract_verified=False,fixed_contract_reason=str(exc))
            assert row['material_contract_verified']==(state['status']=='accepted_provisional_authoring')
    else:
        assert state['native_prompt_may_have_been_dispatched'] is False
    rows.append(row)
assert not outcome['calibration_eligible'] and not outcome['validation_eligible']
report={'schema':'independent-formal-authoring-readback-v1','envelope_sha256':sha(envelope_path),
    'public_outcome_sha256':sha(outcome_path),'source_commit':closure['source_commit'],'rows':rows,
    'planned_authoring_main_opportunities':4,'material_availability':outcome['material_availability'],
    'new_model_calls':0,'validation_access':False,'old_outcomes_unchanged':True,
    'calibration_eligible':False,'validation_eligible':False}
target=root/'independent-readback.json'
with target.open('x',encoding='utf-8') as out:
    out.write(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
