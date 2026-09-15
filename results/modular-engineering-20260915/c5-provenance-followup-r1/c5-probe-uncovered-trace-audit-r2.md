# C5 probe uncovered trace audit r2 — correction

This additive r2 supersedes the **interpretation** of r1’s 52-item classification. R1’s input stamps and item inventory remain unchanged.

## Corrected classification

`runtime.py:332-341` documents that `record_artifact(...)` automatically appends the latest immutable trace as a parent. Therefore a direct catalogue reference is structural evidence only. It does **not** prove that the module semantically consumed that trace, covers each trace field, caused the event, or owns the event. This r2 does not alter the historical graph's `coverage` field.

| r2 grouping | count | assertion |
|---|---:|---|
| `has_direct_catalogue_reference` | 52 | A non-P0 descriptor names the trace digest as a parent. No semantic coverage conclusion. |
| `generic_scheduler_or_model_io_further_review` | 16 | Generic runtime/model-I/O trace without a direct module reference. Further-review grouping only. |
| `no_direct_catalogue_reference_further_review` | 2 | Builder-request/terminal traces without a direct module reference. Further-review grouping only. |

The companion JSON preserves all 70 line-level records, replaces the overstrong label, and records the automatic-parent limit on every direct-reference item.

## Builder trace follow-up

The two items are not established omissions.

- Production code at `full_loo_driver.py:124` records `c4_builder_request` before `begin_builder_artifacts`; line 132 records `c4_build_terminal` after the M9 training-limited candidate. Offline replay at lines 280 and 282 verifies M9 build artefacts and then recreates those C4 trace events.
- The original catalogue has M9 `m9_builder_selection` at journal line 99, digest `96401d22…`, typed schema `m9-builder-selection-v1`, and its typed subjects/file/return/receipt/candidate/terminal chain through `m9_build_terminal` at line 105, digest `5c39cef1…`, file `m9-build-terminal.json`.
- Neither typed M9 chain directly references the C4 builder-request trace at line 98, digest `e0c4866e…`, or the C4 terminal trace at line 108, digest `8eeefb73…`. No phase receipt directly references either trace. This is an absence of a direct reference, not evidence that an artefact is missing.
- `builder_artifacts.py:243-257,341-390` provides an independent reader: it reads retained M9 files, matches typed selection/terminal descriptors, checks candidate and receipt types, and replays the literal builder DSL. It does not read either C4 trace descriptor as input.

The original journals again match their r1 before/after hashes, byte counts, and mtimes. No payload text, prompt, label, or credential was emitted; no source or original evidence was changed.

