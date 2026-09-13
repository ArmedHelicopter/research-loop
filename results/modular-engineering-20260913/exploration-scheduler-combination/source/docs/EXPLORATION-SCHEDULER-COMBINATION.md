# Restricted exploration and FIFO scheduling in TRAIN

The registered conditional factorial for M7 and M8 has four legal cells and no
fixed background modules. Two frozen public core benchmark tasks yield eight
cells. Negative or unqualified singleton findings do not prune this design.

Each cell reserves two auxiliary Docker jobs, the same two downstream model
slots (analysis and final answer), one downstream Docker attempt and one
independent primary score. Three caller-frozen job candidates share the same
task, exact public CSV, candidate package and unit costs. M7-off runs the two
main jobs; M7-on reserves one restricted exploration permit and runs the first
main job and one probe. Selection filters the original FIFO list; M7 cannot
prioritize or reorder it. Data availability means actual pinned public bytes,
not scientific validation. A diagnostic permit remains `not_evidence`.

M8-off uses an ordinary serial FIFO. M8-on uses the real SQLite FifoScheduler
with bounded parallel worker threads, atomic claims, resource exclusion,
dependency checks and a full-group merge barrier. Each selected job executes
its literal frozen Python program through DockerExecutionBroker. The enclosing
phase records actual claim/start/finish/completion/merge order, source and
program artifacts, receipts, reservations and residual states. It never calls
the sequential RunSession.execute concurrently. After successful job replay,
one normal RunSession consumes the public job outputs and performs the shared
benchmark analysis/Docker/final path. Conclusions bind the actual job IDs and
receipts, not their completion positions.

Every source file and serialized artifact is checked before downstream use.
Independent replay reconstructs M7 permits, selected FIFO, actual scheduler
state/receipts and event ordering, and verifies the actual Docker and solver
artifacts. Failed jobs or unknown/expired leases stop scoring without refunding
attempts or deleting cells. Failed scorer/model opportunities and unknown
costs remain explicit. No retry or scientific admission is implied by a zero
exit code or by a scheduler merge.

Synthetic integration exercises all eight cells with real Docker and an
independent primary scorer process. Additional controlled resource conflict,
dependency, duplicate-claim and timeout checks preserve their own results.
Wall time, overlap and throughput are engineering observations of this fixture;
they do not establish calibrated scientific utility, real training gain or
production isolation. Source qualification and independent mechanism scoring
remain separate obligations. No actual private reference or validation payload
is opened, and no paid model is called.

The first expanded root run retained all eight primary scores, but a test
incorrectly required positive wall-clock overlap in every concurrent arm. Two
of four concurrent cells measured zero overlap: SQLite claim overhead and short
jobs can eliminate overlap even while two leases exist. Those original traces
and the failed report remain evidence. Acceptance checks bounded concurrency,
FIFO, exclusion and replay; positive overlap or throughput gain is a measured
outcome and is not imposed by the test.
