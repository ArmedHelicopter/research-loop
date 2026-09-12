"""Static contracts for benchmark sources that may enter modular review.

This catalog is deliberately separate from the public task adapters.  A source
listed here has no loader, evaluator, or split permission: it remains
quarantined until custody review and an adapter-specific integration are added.
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
    ),
    "blade": BenchmarkSource(
        "blade",
        "https://github.com/behavioral-data/BLADE",
        "behavioral-data analysis and data-science workflow evaluation",
        "official dataset family",
    ),
    "scienceagentbench": BenchmarkSource(
        "scienceagentbench",
        "https://github.com/OSU-NLP-Group/ScienceAgentBench",
        "data-driven scientific-discovery program-generation workflows",
        "official benchmark instance",
    ),
    "scicode": BenchmarkSource(
        "scicode",
        "https://github.com/scicode-bench/SciCode",
        "scientific research code-generation and computation workflows",
        "official main problem",
    ),
    "corebench": BenchmarkSource(
        "corebench",
        "https://github.com/siegelz/core-bench",
        "computational reproduction of published scientific papers",
        "official paper-derived task",
    ),
    "airsbench": BenchmarkSource(
        "airsbench",
        "https://github.com/facebookresearch/airs-bench",
        "end-to-end machine-learning research-agent workflows",
        "official research task",
    ),
}

BENCHMARK_SOURCES: Final[Mapping[str, BenchmarkSource]] = MappingProxyType(_SOURCES)


def source_contract(canonical_id: str) -> BenchmarkSource:
    """Return a static source contract or reject an unregistered identifier."""

    return BENCHMARK_SOURCES[canonical_id]

