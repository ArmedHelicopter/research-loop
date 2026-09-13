import pytest

from research_loop.modular.full_loo_composition import (
    FrozenFullLooPlan, candidate_build_key, compose_common_solve_inputs, freeze_full_loo,
)
from research_loop.ontology import ContractError


def plan():
    return freeze_full_loo(baseline_digest="a" * 64, train_task_digests=("b" * 64, "c" * 64),
                           issue_contract_ids=tuple("Q%02d" % n for n in range(1, 49)))


def test_c4_freezes_full_loo_controls_boundaries_and_actual_recipe_budget():
    body = plan().data()
    cells = {row["id"]: row for row in body["cells"]}
    assert len(cells) == 12
    assert cells["without-M2"]["status"] == "structurally_unavailable"
    assert len([row for row in cells.values() if row["status"] == "executable"]) == 11
    assert body["allocation"] == {"target_count": 2, "executable_arm_procedures": 11,
        "structural_arm_procedures": 1, "unique_canonical_builds": 9, "builder_proposals": 9,
        "builder_executions": 9, "history_model_calls": 45, "target_cells": 22, "target_model_calls": 124, "model_calls": 169,
        "independent_source_qualification_calls": 62, "corpus_qualification_calls": 58, "retrieval_requests": 87,
        "history_auxiliary_docker_attempts": 18, "target_auxiliary_docker_attempts": 40,
        "auxiliary_docker_attempts": 58, "solver_docker_attempts": 22, "docker_attempts": 80,
        "scorer_calls": 22, "paid_calls": 0}
    assert cells["without-M9"]["history_build_levels"]["M9"] == 0
    assert cells["without-M9"]["target_levels"]["M9"] == 0
    assert cells["ordinary-control"]["operations"] != cells["B0"]["operations"]
    assert candidate_build_key(cells["B0"]) == candidate_build_key(cells["ordinary-control"])
    assert candidate_build_key(cells["full"]) == candidate_build_key(cells["without-M8"])


def test_c4_rejects_mutation_and_module_smuggling():
    record = plan().record
    changed = record.data(); changed["cells"][0]["history_build_levels"]["M1"] = 0
    with pytest.raises(ContractError):
        FrozenFullLooPlan(type(record).from_dict(changed))
    control = next(row for row in plan().data()["cells"] if row["id"] == "ordinary-control")
    with pytest.raises(ContractError):
        compose_common_solve_inputs(control, {"provenance_retrieval": {}})
    result = compose_common_solve_inputs(control, {name: {} for name in control["operations"]})
    assert result.data()["procedure"] == "ordinary_matched_control"


def test_v2_declares_sequential_ordinary_critique_and_canonical_dependencies():
    body=plan().data();cells={r['id']:r for r in body['cells']}
    assert body['schema']=='c4-full-loo-composition-v2'
    assert cells['without-M2']['reason']=='M3 requires M2; M9 requires M2'
    for name in ('B0','ordinary-control','without-M5'):
        rows=cells[name]['history_operation_bindings']
        assert rows[4]['output_consumer']=='ordinary_critique_b'
        assert rows[5]['purpose']=='ordinary_sequential_critique_with_first_response'
    assert cells['full']['history_operation_bindings'][5]['purpose']=='sealed_independent_review'


def test_v2_roundtrip_is_independent_of_process_hash_seed(tmp_path):
    import os
    import subprocess
    import sys
    record=plan().record;path=tmp_path/'composition.json';path.write_text(record.encoded,encoding='utf-8')
    code=('import sys; from pathlib import Path; from research_loop.modular.contracts import FrozenRecord; '
        'from research_loop.modular.full_loo_composition import FrozenFullLooPlan; '
        'print(FrozenFullLooPlan(FrozenRecord(Path(sys.argv[1]).read_text())).digest)')
    for seed in ('1','2','17','99'):
        result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,env={**os.environ,'PYTHONHASHSEED':seed})
        assert result.returncode==0,result.stderr
        assert result.stdout.strip()==record.content_hash
