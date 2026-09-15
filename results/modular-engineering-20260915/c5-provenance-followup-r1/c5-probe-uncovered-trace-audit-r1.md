# C5 probe uncovered trace audit r1

## Scope

This read-only audit classifies the 70 graph nodes marked `coverage: "uncovered"` in the closed C5 r4 probe. They are 70 generic `trace_event` descriptors, not evidence that 70 files or 70 module artefacts are absent. No source, graph, journal, module assignment, or historical record was changed; no model/API/Docker call was made.

The source graph is indexed at results commit `0a5739e463e3c4a294141ff5bdfd1aec53a75835`. The retained probe source commit is `fad4ed4b2d8d3782f7e0b9366af8b9967ef282c1`. Runtime trace producer pin: `research_loop/modular/runtime.py`, SHA-256 `b1a3cf6ee411ade75db955d77e8d6e0791dd71afff5fdadc9102d15baf96cbd4`, 35,816 bytes.

## Method

For every graph node marked uncovered, this audit read exactly the node's `journal_path` and `journal_line` from the original `source_root`, including the nested `descriptor.payload.canonical` object. It omitted payload values such as requests/prompts. It then used actual catalogue parent references: a trace is classified as having existing specialized coverage only when a non-P0 module descriptor directly names that trace digest as a parent. Sequentially adjacent records were not treated as related.

| Classification | Count | Meaning |
|---|---:|---|
| `existing_specialized_coverage` | 52 | A module descriptor directly names the trace digest as a catalogue parent. The JSON lists module, kind, digest, and status. |
| `generic_scheduler_or_model_io` | 16 | Generic runtime request/response, execution, or final-decision trace without a direct module child. It remains generic; this audit does not relabel it covered. |
| `unknown_actual_gap` | 2 | `c4_builder_request` and `c4_build_terminal` in the history stage have no direct specialized descriptor child. They are review targets, not demonstrated missing artefacts. |

Direct edges establish provenance dependency only. They do not convert the graph's original `coverage` field, and they do not make an independent claim that every field of a generic trace is represented by the child descriptor.

Examples of direct evidence include M4 `c4_prediction_frozen`, M5 sealed/reveal descriptors, M6 retrieval descriptors, M7 choice/phase receipts, M8 phase receipts, M3 contexts, M1/M2 lineage transitions, and M9's training-limited candidate. The full 70-item, per-line classification is machine-readable in the companion JSON.

## Original journal integrity

Both original journals match their before/after hash, size, and mtime stamps:

| Journal | SHA-256 | bytes | mtime-ns |
|---|---|---:|---:|
| history stage `950f42…` | `c04d1d3ac397dedbfdc78aedab0134e8647a36780264d246c99579fdbe30a0d9` | 541,237 | 1789445383989998600 |
| target stage `e1c518…` | `9636bf6f601f328edabe4967423025a5b97d5e20d68c3260966d4614dc278169` | 586,247 | 1789445420538049800 |

Graph pin: SHA-256 `d01ee5c27d84beb517d6f2bd9ac5987faa93c8afb0bb24930e4666df8a7fae0b`, 395,310 bytes. The companion JSON records the exact source root, before/after stamps, every descriptor digest, stage, journal line, classification, and direct module links.

