# Ready batch dispatch after durable reservation

The root C4 integration check on source `29f4b738519c355befec12f10a81cb2390f70c92`
completed all 22 target cells but failed one of 21 tests. Eight of the 16 target
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

A regression check observes the pool submission boundary and requires both
independent leases to be durable before either worker is submitted. It then
executes both real restricted Docker jobs and replays their actual phase records.
The integration check also
retains dependency, resource-conflict, timeout-cleanup and completion-order
cases. These checks concern engineering behavior; scientific effect and
hardware throughput must still be measured in the frozen TRAIN experiments.

Source `3e750beacc21b2e717711eb4410dc1e4398062a7` passed the 26-test root rerun,
including all 22 C4 targets, without changing its 600 source/document hashes.
Independent review subsequently removed a timing assumption from the regression
test and corrected the C4 test's universal positive-overlap assertion. A two-job
batch does not guarantee a positive observed interval under every host schedule.
The C4 check now verifies dispatch capacity, charged attempts, interval bounds
and serial behavior when M8 is absent, matching the existing pair protocol.
The original failure remains evidence; no scientific threshold was changed.

The merged 143-test check on source `ea0d9d7` passed 142 tests, including C4,
and exposed a separate Docker naming collision in the concurrent timeout case.
Both equal task/program invocations received `research-loop-56045e7f3333529ce7d3`.
One timed out and cleaned up; the other received Docker exit 125 because that
name was already in use. The old name used only task, program hash and clock
time, which cannot uniquely identify concurrent identical jobs.

Container names now include a fresh per-invocation UUID nonce while retaining
the existing digest format and subject bindings in the execution receipt. A
32-invocation regression fixes the clock and checks distinct names and exact cleanup
ownership. The real concurrent timeout case also fixes the clock and requires
both jobs to time out and clean up individually. The original collision remains
archived; existing one-second Docker timeouts and resource limits are unchanged.
