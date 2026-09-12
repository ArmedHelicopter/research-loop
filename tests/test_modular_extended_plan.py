import pytest

from research_loop.modular.__main__ import programme_plan
from research_loop.ontology import ContractError


def test_added_benchmarks_are_frozen_into_every_obligation_without_claiming_execution():
    required = ("discoverybench", "blade", "scienceagentbench", "scicode", "corebench", "airsbench")
    record = programme_plan("fixture-baseline", benchmarks=required)
    plan = record.data()
    assert len(plan["scenarios"]) == 48
    assert all(row["required_benchmarks"] == list(required) for row in plan["scenarios"])
    assert len(plan["C2"]) == 36 and len(plan["C3"]) == 5
    assert plan["scientific_status"] == "not_measured"
    assert set(plan["additional_benchmark_qualification"]) == set(required[2:])
    assert record.content_hash != programme_plan("fixture-baseline").content_hash


@pytest.mark.parametrize("benchmarks", [("scicode",), ("blade", "discoverybench", "unregistered"), ("discoverybench", "blade", "blade")])
def test_expansion_cannot_omit_original_obligations_or_add_unregistered_or_duplicate_source(benchmarks):
    with pytest.raises(ContractError, match="both original benchmark obligations"):
        programme_plan("fixture", benchmarks=benchmarks)
