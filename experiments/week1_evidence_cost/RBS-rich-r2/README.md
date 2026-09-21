# Native R/B/S replay: RBS-rich-r2

This is CPU replay of an already recorded TRAIN workflow. No new model invocation, scientific task, scoring or VAL access occurred. All 60 shuffled fresh children completed and 180 exact context/state comparisons matched. The source is one previously counted NLS SES task, not a new independent task.

| Scheme | Cold bind us | Native updates + journal us | Three actual queries us | Evidence expansion us | Extra warm query us | Max child peak bytes |
|---|---:|---:|---:|---:|---:|---:|
| R | 518.8 | 1825284.45 | 21620.35 | 1958.5 | 11662.5 | 27688960 |
| B | 524.3 | 1724372.4 | 24077.2 | 1951.35 | 13138.85 | 27353088 |
| S | 530.2 | 1746849.05 | 21932.05 | 1956.5 | 6.95 | 26996736 |

| Scheme | Median component sum ms | Q25 ms | Q75 ms |
|---|---:|---:|---:|
| R | 1849.4347 | 1490.5587 | 1953.07185 |
| B | 1751.3004 | 1497.857475 | 1962.1555250000001 |
| S | 1771.1506 | 1528.4416250000002 | 1944.039425 |

The second table sums measured nonoverlapping components within each child before aggregation; it is not a sum of separate medians. Quartiles describe timing variation, not cross-task inference or confidence intervals.

S has zero hits in every actual sequence. The ten extra identical-query warm probes are separate; they cannot establish a realized domain-workflow cache benefit. Persistent native journal costs dominate this replay, and their variation is visible. Native replay excludes the full RunSession artifact-catalogue persistence, so it cannot explain away the original registration cost.

Tracemalloc was enabled during timed operations. Actual-sequence wall time includes correctness checks; whole-child wall includes import/validation and warm probes. Raw results separately record actual_sequence_peak_working_set_bytes before warm probes and whole_child_peak_working_set_bytes afterward. Do not compare these instrumented query times directly with the original uninstrumented live timings.

All native semantics remain unchanged. AND grouping is unsupported by the native reference, not a passed capability or an S improvement. No candidate C, end-to-end optimized rerun, token savings or capability gain is demonstrated. Source/operation hashes and fixed resource/timeout bounds are in manifest.json.

Prior attempt RBS-rich-r1 remains incomplete at 46/60 under its 180-second parent cap. RBS-rich-r1b is a fresh complete comparison with a 600-second cap and unchanged scheme semantics/operations/repeats. This report never substitutes partial rows for missing runs.
