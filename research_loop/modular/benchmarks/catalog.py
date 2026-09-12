"""Static contracts for benchmark sources that may enter modular review.

This catalog is deliberately separate from the public task adapters. Listing
a source grants no loader, evaluator, or split permission. Adapter availability
is tracked independently of custody qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


REQUIRED_BENCHMARKS: Final = ("discoverybench", "blade")
SUPPORTED_BENCHMARKS: Final = (
    "discoverybench",
    "blade",
    "scienceagentbench",
    "scicode",
    "corebench",
    "airsbench",
)


@dataclass(frozen=True)
class BenchmarkSource:
    """A source-level contract, not an executable benchmark adapter."""

    canonical_id: str
    official_repository_url: str
    purpose_scope: str
    grouping_unit: str
    qualification: str = "quarantine_until_review"
    runtime_adapter_status: str = "catalog_only_no_runtime_adapter"


_SOURCES = {
    "discoverybench": BenchmarkSource(
        "discoverybench",
        "https://github.com/allenai/discoverybench",
        "data-driven scientific-discovery hypothesis and analysis workflows",
        "official benchmark task group",
        runtime_adapter_status="public_adapter_implemented",
    ),
    "blade": BenchmarkSource(
        "blade",
        "https://github.com/behavioral-data/BLADE",
        "behavioral-data analysis and data-science workflow evaluation",
        "official dataset family",
        runtime_adapter_status="public_adapter_implemented",
    ),
    "scienceagentbench": BenchmarkSource(
        "scienceagentbench",
        "https://github.com/OSU-NLP-Group/ScienceAgentBench",
        "data-driven scientific-discovery program-generation workflows",
        "shared source dataset, paper, or artifact family; instances sharing roots stay together",
        runtime_adapter_status="restricted_public_projection_only",
    ),
    "scicode": BenchmarkSource(
        "scicode",
        "https://github.com/scicode-bench/SciCode",
        "scientific research code-generation and computation workflows",
        "official main problem",
        runtime_adapter_status="restricted_public_projection_only",
    ),
    "corebench": BenchmarkSource(
        "corebench",
        "https://github.com/siegelz/core-bench",
        "computational reproduction of published scientific papers",
        "source paper and shared artifact family; derived tasks stay together",
    ),
    "airsbench": BenchmarkSource(
        "airsbench",
        "https://github.com/facebookresearch/airs-bench",
        "end-to-end machine-learning research-agent workflows",
        "shared source dataset and task lineage; repeated evaluations stay together",
    ),
}

BENCHMARK_SOURCES: Final[Mapping[str, BenchmarkSource]] = MappingProxyType(_SOURCES)


def source_contract(canonical_id: str) -> BenchmarkSource:
    """Return a static source contract or reject an unregistered identifier."""

    return BENCHMARK_SOURCES[canonical_id]

