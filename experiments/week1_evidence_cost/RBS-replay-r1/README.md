# Native R/B/S replay of three saved TRAIN workflows

180 fresh-process runs (20 repeats x 3 schemes x 3 tasks), globally shuffled with seed 20260921. The three tasks belong to two source families. All 360 exact context and native ledger-state comparisons passed. No new model calls, tool executions, scoring or VAL access occurred.

Each actual sequence contains six recorded native ledger mutations and two different queries. S observes all six mutations and has two misses, zero actual hits, and one invalidated entry. Its ten subsequent identical-query probes are separate diagnostics, not observed domain reuse.

| Task | Scheme | Cold bind us | Six updates incl. journal us | Two actual queries us | Full expansion us | Separate warm query us | Max child working-set bytes |
|---|---|---:|---:|---:|---:|---:|---:|
| week1-domain-2-r2 | R | 503.8 | 194176.55 | 3357.1 | 285.15 | 1648.6 | 26234880 |
| week1-domain-2-r2 | B | 498.55 | 204101.55 | 3710.9 | 284.3 | 1854.15 | 26263552 |
| week1-domain-2-r2 | S | 525.7 | 205058.55 | 3364.7 | 290.15 | 5.8 | 26222592 |
| week1-domain-3-r2 | R | 484.55 | 211035.2 | 2812.75 | 236.65 | 1483.35 | 26259456 |
| week1-domain-3-r2 | B | 502.95 | 211924.05 | 3139.05 | 238.75 | 1662.55 | 26263552 |
| week1-domain-3-r2 | S | 494.75 | 207518.2 | 2788.85 | 236.4 | 5.3 | 26288128 |
| week1-domain-1-r3 | R | 495.1 | 207872.7 | 2874.05 | 242.85 | 1490.85 | 26320896 |
| week1-domain-1-r3 | B | 503.3 | 204605.7 | 3178.4 | 237.7 | 1672.15 | 26329088 |
| week1-domain-1-r3 | S | 503.55 | 204739.5 | 2802.5 | 244.0 | 5.4 | 26238976 |

Timing limitations: tracemalloc was enabled during measured operations. Absolute timings must not be compared directly with the earlier uninstrumented pilot. Each table column is a separate median; their sum is not the median total. Actual-sequence wall time also includes correctness checks. Whole-child wall time includes imports, checks and the separate warm probes. The raw field named whole_child_peak_working_set_bytes was actually sampled after the actual sequence, before the warm probes; it includes startup/imports and actual-sequence checks, but does not establish the peak during the later warm probes. Raw values are retained. Richer replay producers record both phase and later child peaks explicitly. Native persistent journals are replayed; the complete RunSession artifact catalogue, client and container execution are not replayed.

The observed query costs are small and real reuse is absent in these short workflows. These data do not establish meaningful task-level speedup, subscription savings, token savings, capability gains or a reason to develop C. The native AND-support expressiveness gap remains explicitly unpassed. Workload representativeness remains open.

Provenance: manifest.json binds code, native source hashes, input artifact catalogues and extracted chronological schedules. measurement/order.json records execution order; measurement/raw.jsonl contains every child result; summary.json and result.json retain denominators. Per-run native persistent journal files are stored in the declared WORK/RBS-replay-r1 directory.

Commands: python -B experiments/week1_evidence_cost/compare_native_replay.py freeze --run RBS-replay-r1; python -B experiments/week1_evidence_cost/compare_native_replay.py run --run RBS-replay-r1. See --help and frozen producer for exact arguments if this source changes.
