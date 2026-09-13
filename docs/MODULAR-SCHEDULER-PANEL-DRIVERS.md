# Q3 M8 scheduler panel drivers

`scheduler_panel_drivers` provides formal train-only drivers for Q3.3, Q3.4, and Q3.5. A caller must freeze a typed public bundle containing the task identity, a shared evidence/rules/package snapshot, two ordered work items, public resource locks, fixed per-item costs, completion order, and withdrawal subjects for every registered variant.

Each arm receives the same selected bundle and total cost. The driver uses the real SQLite `FifoScheduler`: Q3.3 observes one versus two workers issuing FIFO runnable work; Q3.4 retains the merge barrier while completing the two items in each declared order; Q3.5 retains write-lock deferral, withdrawal invalidation, expiry/crash-to-unknown with explicit termination before recovery, and duplicate receipt rejection. It uses deterministic lease timestamps and does not sleep.

The only model call carries the public task, opaque panel-cell binding, a label-free scheduler observation, and the frozen objective digest. It does not receive arm, enabled modules, variant, controller bundle, full package, score, or private benchmark material. These drivers establish scheduler wiring only; they neither score a benchmark nor establish a scientific effect.
