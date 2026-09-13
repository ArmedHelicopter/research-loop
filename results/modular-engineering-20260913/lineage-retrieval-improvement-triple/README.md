# M3 × M6 × M9 engineering handoff

The final prospective TRAIN grid executed all eight legal arms on two synthetic primary-like tasks, with M2 fixed. Two history-only candidate builds were shared across target M3/M6 levels. Every target used the actual lineage transition, bounded matched retrieval, one shared solver, real Docker, and an independent primary-scorer process after the target provider ledger was sealed.

Final source: `e5bf4cfcd3eb0011dfa202fd3ef976851f3a0aec`, including local target replay repair `0f8ff65` and the separate canonical build replay repair `e5bf4cf`. Earlier commits are implementation `5e5a879` and preserved counterexample regressions `7da51df`.

## Separate frozen closures

- `5e5a879`: 74 passed, 543 source files unchanged. This preserves the original source/model/build/retrieval/Docker/scorer failure and unused-opportunity grids. Later cost counterexamples exposed a missing replay stop rule in this source.
- `7da51df`: three expected rejection tests failed because coherent signed unknown-cost state, corpus and build receipts were accepted after generic replay. The original forged receipts, traces and issued score/build evidence remain in its ZIP.
- `e5bf4cf`: 61 passed, 543 source files unchanged. This reruns the full 16-cell grid, seven contrasts, all replay attacks including the three repaired cases, independent scorer scope and label checks. Earlier failure grids were not rerun; counts are not combined into a new-source test total.

Each successful grid used 34 synthetic model calls / 68 reported fixture tokens, 2 restricted builder executions, 68 signed qualification calls, 16 retrieval operations / 48 provider requests, 16 target Docker executions and 16 independent scores. The frozen query needs no model slot. Each fixture separately acquired its existing history with two synthetic model calls and one Docker execution; history acquisition is outside the prospective allocation and retained in its own records.

All planned failed, blocked, unknown-cost and unused rows remain in `denominators.json` and original controller receipts. Unknown source/model costs stop later opportunities. Retrieval/scorer monetary usage remains unknown. The seven normalized descriptive main/pair/triple terms are zero under the constant synthetic scorer; every benchmark has one independent group, so all 95% confidence intervals have null bounds and an insufficient-independent-groups reason.

The archive uses an explicit public-evidence allowlist and excludes scorer reference stores, keys and server configuration. `archive-members.json` binds every ZIP member; `archive-integrity.json` binds the committed archive artifacts. Synthetic engineering evidence establishes no real-model benefit, scientific validity, production readiness, throughput advantage, or validation result. No paid model calls, real private references, or validation data were accessed.
