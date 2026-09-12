# Extended benchmark-source catalog

`discoverybench` and `blade` remain the required benchmarks.  The four
additional sources below are source contracts only.  They do not add a public
task adapter, allocate a split, expose a task, or qualify any data for a run.
Every listed source remains `quarantine_until_review`.

| Canonical ID | Official repository | Intended coverage | Grouping unit | Runtime status |
| --- | --- | --- | --- | --- |
| `discoverybench` | <https://github.com/allenai/discoverybench> | Data-driven discovery hypotheses and analyses | Official task group | Existing adapter is governed separately |
| `blade` | <https://github.com/behavioral-data/BLADE> | Behavioral-data analysis workflows | Official dataset family | Existing adapter is governed separately |
| `scienceagentbench` | <https://github.com/OSU-NLP-Group/ScienceAgentBench> | Scientific program-generation workflows | Shared source dataset, paper or artifact family | Catalog only; no runtime adapter |
| `scicode` | <https://github.com/scicode-bench/SciCode> | Scientific computation and code-generation workflows | Official main problem | Catalog only; no runtime adapter |
| `corebench` | <https://github.com/siegelz/core-bench> | Computational reproduction of scientific papers | Source paper and shared artifact family | Catalog only; no runtime adapter |
| `airsbench` | <https://github.com/facebookresearch/airs-bench> | End-to-end ML research-agent workflows | Shared source dataset and task lineage | Catalog only; no runtime adapter |

The pinned metadata for the four additional sources is stored in
[`data-source-metadata`](data-source-metadata).  It records official-repository
commit identifiers and non-content file names.  File sizes and blob hashes were
not collected because this survey intentionally avoided retrieving repository
file contents.  The commit SHA identifies the whole Git tree; it is not an
attestation that a local copy is complete, independent, unexposed, licensed for
a particular use, or ready for execution.

Before any source can be used, an owner must separately establish acquisition
provenance and license terms, inventory the received material, reconcile it
against exposure records, assign independent groups, obtain the required
custody attestation, and implement and integration-test a restricted public
adapter.  None of those actions occurred for this catalog.
