# M7/M8 recovery fixture scenarios

`research_loop.modular.scenarios_recovery` supplies offline, fixture-only runners for Q3.3--Q3.5, Q5.1, and Q5.5. Each runner takes a prepared public task, matching frozen controls, and an optional callback. The callback receives the actual post-manipulation frozen payload; its response is retained, but is never treated as a scientific verdict.

Q3 uses the real SQLite `FifoScheduler`: Q3.3 compares one versus two workers on the same FIFO order and fixed budget; Q3.4 completes arms in both orders and proves the merge barrier preserves the pending arm snapshot; Q3.5 exercises resource conflict deferral, invalidation after withdrawal, expiry/crash to `unknown` followed by termination-confirmed recovery, and unique receipt rejection. Unknown work is never silently rerun and all costs equal receipt-reserved units.

Q5.1 advances only through explicit `data`, `minimal_run`, `discriminating_measurement`, and `independent_result` receipt objects. A zero-exit receipt remains engineering execution evidence and never makes a scientific claim. Q5.5 withholds one of data version, minimum method artifact, execution budget, or negative control; `ResourceClosure` rejects it before execution.

The focused tests cover every registered variant through both public task adapters. They are offline integration fixtures: no network, paid model call, real dataset, label, gold answer, validation score, or benchmark result is used. Their pass status establishes only these scheduler and qualification seams, not throughput improvement, benchmark efficacy, scientific validity, or research quality.
