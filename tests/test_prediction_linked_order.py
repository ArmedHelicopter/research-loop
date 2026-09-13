"""Reject the preserved actual late-freeze counterexample before solver I/O."""
import json
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord,PublicTask,DataIdentity
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell,RuntimeReceipt
from research_loop.modular.panel_runner import TrainCellResult
from research_loop.modular.benchmark_cell import verified_mechanism_provenance
from research_loop.ontology import ContractError


def test_original_rehashed_late_freeze_must_be_rejected():
    root=Path(__file__).resolve().parents[1]/'results/modular-engineering-20260913/prediction-linked-order/original-finding'
    b=json.loads((root/'replay-input.json').read_text(encoding='utf-8')); c=b['cell']; r=b['runtime']
    cell=PanelCell(c['coverage_id'],DataIdentity.parse(c['identity']),c['replicate'],c['variant'],c['arm_id'],
        FrozenRecord.from_dict(c['runtime_arm']),c['task_digest'],c['scenario_digest'],c['package_digest'],c['scorer_digest'])
    task=PublicTask(DataIdentity.parse(b['task']['identity']),FrozenRecord.from_dict(b['task']['payload']))
    runtime=RuntimeReceipt(tuple(r['cell_key']),r['status'],root/'late-mechanism/trace.jsonl',r['trace_digest'],r['output_digest'],r['failure_reason'])
    with pytest.raises(ContractError,match='prediction chronology'):
        verified_mechanism_provenance(cell=cell,task=task,scenario=FrozenRecord.from_dict(b['scenario']),
            package=CandidatePackage(FrozenRecord.from_dict(b['package'])),
            mechanism=TrainCellResult(runtime,None,FrozenRecord.from_dict({'replay_only':True})))
