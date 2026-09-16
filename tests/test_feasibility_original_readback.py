"""Draft for a separately frozen reader; consumes original closed r2, zero dispatch."""
import json
import hashlib
import os
from pathlib import Path
from copy import deepcopy

import pytest

from evaluation.modular.scorer_process import parse_frozen_panel
from research_loop.modular.benchmark_cell import restore_completed_benchmark_cell
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.feasibility_panel_drivers import freeze_feasibility_panel_bundle
from research_loop.modular.linked_feasibility_projection import derive_feasibility_replay
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import RuntimeReceipt
from research_loop.ontology import ContractError
from test_modular_feasibility_panel_drivers import _Authority, _item, _branches

R=FrozenRecord.from_dict


def test_closed_original_m4_only_control_rejects_mask_tamper_without_dispatch():
    if not os.environ.get('FEASIBILITY_LINKED_ORIGINAL'): pytest.skip('requires retained original feasibility native run')
    root=Path(os.environ['FEASIBILITY_LINKED_ORIGINAL']).resolve()
    prefix=root.parent
    raw_closed=Path(str(prefix)+'-closed.json').read_bytes()
    assert hashlib.sha256(raw_closed).hexdigest()=='e841522f414613939eed83ec46d50efd75e495c701c12bece16d6149d465db5c'
    closed=json.loads(raw_closed)
    joined=json.loads(Path(str(prefix)+'-native-join.json').read_bytes())
    assert closed['source_unchanged'] and joined['native_session_id']==83008
    assert joined['result']['exit_code']==closed['exit_code']
    evidence=json.loads((root/'independent-readback.json').read_bytes())
    assert evidence['cells']==36 and evidence['producer_calls']==180 and len(evidence['scores'])==36
    attempt=json.loads((root/'run/controller-attempt.json').read_bytes())
    panel=parse_frozen_panel(json.loads((root/'server.json').read_bytes())['panel'])
    cell=next(c for c in panel.cells if c.coverage_id=='Q5.2' and c.variant=='negative_control'
              and 'M4' in c.runtime_arm.data()['enabled'] and 'M7' not in c.runtime_arm.data()['enabled'])
    packet=next(p for p in (root/'export').glob('*/*/public.json')
                if json.loads(p.read_bytes())['task']['identity']==cell.identity.data())
    body=json.loads(packet.read_bytes())['task'];task=PublicTask(DataIdentity.parse(body['identity']),R(body['payload']))
    csv=packet.with_name('data.csv');authority=_Authority()
    bundle=freeze_feasibility_panel_bundle(task,
        q51={name:_item(task,csv,authority,level=i) for i,name in enumerate(
            ('subjective','data','minimal_run','measurement','independent'))},
        q52={'zero_exit_same_prediction':_item(task,csv,authority,branches=_branches(False)),
             'negative_control':_item(task,csv,authority,branches=_branches(True))})
    material=scenario(registry().get(cell.coverage_id),cell.variant,
        inputs=ControllerInputs(R(task.data()),bundle,R(attempt['compiled_manifest']['budget'])))
    assert material.content_hash==cell.scenario_digest
    package=CandidatePackage(R(attempt['compiled_manifest']['package_bundle']['packages'][cell.runtime_arm.content_hash]))
    folder=root/'run/cells'/R(cell.data()).content_hash
    raw=next(r for r in attempt['runtime_receipts'] if r['cell_key']==list(cell.key))
    runtime=RuntimeReceipt(cell.key,raw['status'],folder/'mechanism/trace.jsonl',raw['trace_digest'],
                           raw['output_digest'],raw['failure_reason'])
    linked=R(next(r for r in attempt['linked_receipts'] if r['cell_key']==list(cell.key)))
    restored=restore_completed_benchmark_cell(cell=cell,task=task,scenario=material,package=package,
        runtime=runtime,linked_receipt=linked,solver_sidecar=folder/'solver',public_inputs={'public_csv':csv})
    assert restored.status=='linked_succeeded'
    events=[json.loads(line) for line in runtime.trace_path.read_text().splitlines()]
    replay=derive_feasibility_replay(cell=cell,task=task,scenario=material,package=package,events=events)
    assert all(v is None for v in replay.data()['public_material']['observation']['stages'].values())
    altered=deepcopy(events)
    stage=next(e for e in altered if e['stage']=='modular_workflow' and e['data'].get('stage')=='operation_m7_control')
    stage['data']['public_observation']['prediction']['identifiable']=None
    with pytest.raises(ContractError):
        derive_feasibility_replay(cell=cell,task=task,scenario=material,package=package,events=altered)
    assert not authority.calls


def test_original_failed_panel_keeps_all_cells_and_unknown_usage_without_empty_score_closure():
    if not os.environ.get('FEASIBILITY_LINKED_ORIGINAL'): pytest.skip('requires retained original feasibility native run')
    root=Path(os.environ['FEASIBILITY_LINKED_ORIGINAL']).resolve().parent/'test_failed_producer_retains_c0'
    attempt=json.loads((root/'run/controller-attempt.json').read_bytes())
    ledger=json.loads((root/'p/ledger/ledger.json').read_bytes())
    assert attempt['expected_cells']==len(attempt['cell_plan'])==len(attempt['cells'])==36
    assert {r['status'] for r in attempt['cells']}=={'failed','blocked'}
    assert all(r['solver_status'] is None and r['execution'] is None for r in attempt['linked_receipts'])
    assert len(ledger['calls'])==1 and ledger['calls'][0]['status']=='unknown_or_failed'
    assert ledger['usage_incomplete'] is True
    assert attempt['actual_model_usage']['unknown_main_opportunities']==1
    assert attempt['actual_model_usage']['all_opportunity_tokens'] is None
    assert not (root/'worker.jsonl').exists()
    # The pure argument guard must reject before touching any process/client
    # state. Never invent a successful scientific closure for zero scores.
    from evaluation.modular.scorer_process import LinkedScorerProcessClient
    reader=object.__new__(LinkedScorerProcessClient)
    reader.evaluator_provider={'kind':'grok-headless-frozen-evaluator-v1'}
    with pytest.raises(ContractError,match='ordered scorer receipts'):
        reader.finalize_headless_evaluator(receipts=[])
