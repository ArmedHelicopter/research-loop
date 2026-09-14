# Ready batch dispatch after durable reservation

The root C4 integration check on source `29f4b738519c355befec12f10a81cb2390f70c92`
completed all 22 target cells but failed one of 21 tests. Nine of the 16 target
phases with M8 recorded zero worker overlap. The original event journals show
the first worker finishing during the second independent lease's persistence;
the second worker then started after the first had already finished. Both
leases were eventually charged, so peak leased capacity alone did not establish
concurrent work. The original failing check and phase receipts remain retained.

The auxiliary phase now obtains the currently ready leases before submitting
that batch to the worker pool. FIFO, resource exclusions, dependency checks,
the two-worker bound, per-attempt costs and the completion barrier still use
the existing durable scheduler. A dependency or resource conflict admits one
worker, then the next scheduling round follows its completion. Timing values
continue to come from original events; no minimum overlap is fabricated.

A regression check pauses the second lease's persistence seam and verifies
that productive work has not yet started. It then executes both real restricted
Docker jobs and replays their actual phase records. The integration check also
retains dependency, resource-conflict, timeout-cleanup and completion-order
cases. These checks concern engineering behavior; scientific effect and
hardware throughput must still be measured in the frozen TRAIN experiments.
