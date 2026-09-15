# C5 r4 artifact view

This is a read-only, redacted index of original `ArtifactCatalogue` descriptors from the closed C5 r4 probe. It does not construct a runtime, replay provenance, query a provider, read label data, or establish a scientific effect. Payload text, labels, and credentials are deliberately absent.

- Nodes: 212 descriptor records
- Actual catalogue-parent edges: 311
- Explicit outer stage bindings: 1
- Stages: history build `950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e` and target `e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1`

`graph.json` retains each descriptor digest, journal path and line, module/kind/status/coverage, actual parent digest list, source/config/check/payload *summaries* only, and explicit outer stage bindings. Cross-directory relation is included only because the target outer-stage record names the same `build_id` as the history outer-stage record; no chronology inference is used.

Module counts:

| module | nodes | status summary | stage counts |
|---|---:|---|---|
| M1 | 2 | produced:2 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:1, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:1 |
| M2 | 28 | produced:26, withdrawn:2 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:14, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:14 |
| M3 | 13 | produced:13 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:6, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:7 |
| M4 | 4 | produced:4 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:2, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:2 |
| M5 | 14 | produced:14 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:7, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:7 |
| M6 | 28 | produced:28 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:14, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:14 |
| M7 | 16 | produced:16 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:8, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:8 |
| M8 | 27 | not_applied:13, produced:14 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:13, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:14 |
| M9 | 8 | produced:8 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:8 |
| P0 | 2 | produced:2 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:1, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:1 |
| uncovered | 70 | produced:70 | 950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e:34, e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1:36 |

Input bytes and mtimes were stamped before and after indexing in `input-manifest.json`. The r4 probe is exploratory engineering evidence; its source was checked only after completion, so this view does not claim an all-run pre/post source freeze or a completed real benchmark.
