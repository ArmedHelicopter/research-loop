# Extended benchmark-source catalog

`discoverybench` and `blade` remain the required benchmarks.  The four
additional sources below have separate source contracts. Catalog inclusion does
not allocate a split, expose a task, or qualify any data for a run. SciCode and
ScienceAgentBench now have restricted public-projection adapters tested with
synthetic public records; source acquisition and scientific scoring are pending.
Every listed source remains `quarantine_until_review`.

| Canonical ID | Official repository | Intended coverage | Grouping unit | Runtime status |
| --- | --- | --- | --- | --- |
| `discoverybench` | <https://github.com/allenai/discoverybench> | Data-driven discovery hypotheses and analyses | Official task group | Existing adapter is governed separately |
| `blade` | <https://github.com/behavioral-data/BLADE> | Behavioral-data analysis workflows | Official dataset family | Existing adapter is governed separately |
| `scienceagentbench` | <https://github.com/OSU-NLP-Group/ScienceAgentBench> | Scientific program-generation workflows | Shared source dataset, paper or artifact family | Restricted public projection; data/scorer pending |
| `scicode` | <https://github.com/scicode-bench/SciCode> | Scientific computation and code-generation workflows | Official main problem | Restricted public projection; data/scorer pending |
| `corebench` | <https://github.com/siegelz/core-bench> | Computational reproduction of scientific papers | Source paper and shared artifact family | Catalog only; no runtime adapter |
| `airsbench` | <https://github.com/facebookresearch/airs-bench> | End-to-end ML research-agent workflows | Shared source dataset and task lineage | Catalog only; no runtime adapter |

The pinned metadata for the four additional sources is stored in
[`data-source-metadata`](data-source-metadata).  Each record now names its saved
official recursive Git-tree response and repository-license artifact.  The
records include the exact pinned commit, entry count, `truncated: false`, a
SHA-256 for each saved artifact, and type, size, and Git blob SHA-1 for the
listed repository files.  A Git blob SHA-1 identifies a Git object and is not a
SHA-256 checksum.  The raw tree JSON and repository license text were collected
as metadata only. During that collection, no repository blob besides `LICENSE`
was read. A subsequent adapter-schema review read official README/loader/evaluator
source code, documented in [MODULAR-EXTENDED-INGESTION.md](MODULAR-EXTENDED-INGESTION.md).
Neither phase read a benchmark task, answer, reference, annotation, or dataset payload.

The prior direct-connection errors remain under
`data-source-metadata/rawtree` as historical collection evidence.  A pinned
commit and a complete tree response do not attest that a local copy is complete,
independent, unexposed, licensed for a particular use, or ready for execution.
The recorded repository-code license also does not establish a dataset license;
that requires separate review.

Before any source can be used, an owner must separately establish acquisition
provenance and license terms, inventory the received material, reconcile it
against exposure records, assign independent groups, obtain the required
custody attestation, and implement and integration-test a restricted public
adapter. The two new adapters only establish their projection and runtime-request
boundary with synthetic fixtures; acquisition and independent data qualification
remain unfinished.
