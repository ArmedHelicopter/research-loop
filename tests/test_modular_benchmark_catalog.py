from research_loop.modular.benchmarks.catalog import (
    BENCHMARK_SOURCES,
    REQUIRED_BENCHMARKS,
    SUPPORTED_BENCHMARKS,
    source_contract,
)


def test_catalog_has_exact_canonical_ids_and_preserves_required_pair() -> None:
    assert SUPPORTED_BENCHMARKS == (
        "discoverybench", "blade", "scienceagentbench", "scicode", "corebench", "airsbench",
    )
    assert REQUIRED_BENCHMARKS == ("discoverybench", "blade")
    assert tuple(BENCHMARK_SOURCES) == SUPPORTED_BENCHMARKS


def test_catalog_entries_are_quarantined_source_contracts_not_adapters() -> None:
    for benchmark in SUPPORTED_BENCHMARKS:
        entry = source_contract(benchmark)
        assert entry.official_repository_url.startswith("https://github.com/")
        assert entry.purpose_scope
        assert entry.grouping_unit
        assert entry.qualification == "quarantine_until_review"
        assert entry.runtime_adapter_status == "catalog_only_no_runtime_adapter"
