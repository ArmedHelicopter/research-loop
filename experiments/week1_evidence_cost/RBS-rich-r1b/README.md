# Native R/B/S replay: RBS-rich-r1b

This is CPU replay of an already recorded TRAIN workflow. No new model invocation, scientific task, scoring or VAL access occurred. All 60 shuffled fresh children completed and 180 exact context/state comparisons matched. The source is one previously counted NLS SES task, not a new independent task.

| Scheme | Cold bind us | Native updates + journal us | Three actual queries us | Evidence expansion us | Extra warm query us | Max child peak bytes |
|---|---:|---:|---:|---:|---:|---:|
| R | 532.05 | 1100041.4 | 17327.75 | 1560.85 | 7570.1 | 26611712 |
| B | 520.95 | 1024111.85 | 19243.05 | 1542.5 | 8473.8 | 26542080 |
| S | 528.4 | 1079859.4 | 17408.15 | 1566.25 | 7.3 | 26402816 |

| Scheme | Median component sum ms | Q25 ms | Q75 ms |
|---|---:|---:|---:|
| R | 1119.2518 | 996.290925 | 1275.472925 |
| B | 1045.3658 | 989.0395500000001 | 1209.39705 |
| S | 1099.44265 | 979.648275 | 1268.8225 |

The second table sums measured nonoverlapping components within each child before aggregation; it is not a sum of separate medians. Quartiles describe timing variation, not cross-task inference or confidence intervals.

S has zero hits in every actual sequence. The ten extra identical-query warm probes are separate; they cannot establish a realized domain-workflow cache benefit. Persistent native journal costs dominate this replay, and their variation is visible. Native replay excludes the full RunSession artifact-catalogue persistence, so it cannot explain away the original registration cost.

Tracemalloc was enabled during timed operations. Actual-sequence wall time includes correctness checks; whole-child wall includes import/validation and warm probes. Raw results separately record actual_sequence_peak_working_set_bytes before warm probes and whole_child_peak_working_set_bytes afterward. Do not compare these instrumented query times directly with the original uninstrumented live timings.

All native semantics remain unchanged. AND grouping is unsupported by the native reference, not a passed capability or an S improvement. No candidate C, end-to-end optimized rerun, token savings or capability gain is demonstrated. Source/operation hashes and fixed resource/timeout bounds are in manifest.json.

Prior attempt RBS-rich-r1 remains incomplete at 46/60 under its 180-second parent cap. RBS-rich-r1b is a fresh complete comparison with a 600-second cap and unchanged scheme semantics/operations/repeats. This report never substitutes partial rows for missing runs.

Source workflow limitation: domain-rich-r1 recorded eight primary statistics but its qualification produced no facts due to the retained mounted-file mistake. This complete CPU replay does not turn that failure into a successful scientific check.
