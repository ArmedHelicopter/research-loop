# Linked benchmark cell wiring

`research_loop.modular.benchmark_cell.run_benchmark_cell` composes one actual
train-only Q3.1 or Q4.3 `run_train_cell` journal with the shared
`run_benchmark_solve` journal. It is an independent adapter; it is not wired
into `train_controller`, a scorer, or formal acceptance.

The mechanism receipt is first replayed by `PanelReceiptVerifier` and the
common protocol validator. The wrapper then derives
`verified-mechanism-provenance-v1` from the trace's executed mechanism stages
and response/request pairs. Its cell, task, scenario, package, and arm bindings
are passed to both solver model requests as `panel_cell` and
`mechanism_provenance`. Arbitrary predecessor hashes are not an alternate
input to this adapter.

`verify_linked_benchmark_cell` replays both journals and checks the shared
binding, exact provenance in every solver request, all recorded model calls,
and the execution receipt. It derives solver status, analysis, answer, final
decision, and execution material from the solver journal rather than trusting
mutable result fields, and requires its lock to match the mechanism task,
package, arm, and objective. A failed or blocked mechanism produces a linked
denominator row without a solver. A solver model or execution failure remains
a row with its terminal solver trace. Docker exit status is execution evidence
only; the linked receipt always records `scientific_effect: not_measured`.

For cold-start finalization, the solver supplies the exact analysis response
(including program and analysis text), its immutable response digest, the
executed-program SHA-256, and execution feedback to the final model request.
The program digest is checked against the broker execution artifact and journal
before that request is made.

The synthetic integration suite is
`tests/test_modular_benchmark_cell.py`. It uses both supported public task
adapters, Q3.1 and Q4.3, the pinned local image, synthetic CSV input, and a
model callback that asserts real mechanism content reaches both solver calls
and Docker stdout reaches the final answer.

`FrozenTrainControllerConfig.execution_mode` may be
`linked_benchmark_solve` for the closed Q1.5/Q3.1/Q4.3 scope. Its frozen
schemas include `analysis_program` and `final_answer`, and preflight budgets
two additional model calls per cell. The controller takes only custody-exported
packet CSV files, uses the pinned Docker image, and records each linked receipt
in its attempt journal. Mechanism and solver failures remain denominator rows.
