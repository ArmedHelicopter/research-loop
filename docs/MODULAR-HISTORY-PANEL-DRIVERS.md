# Q1.1 and Q1.2 history panel drivers

`freeze_history_bundle()` accepts caller-supplied before/current public records,
a frozen replacement transition, and complete Q1.1/Q1.2 historical records.
It verifies the task identity and variant coverage, then freezes one bundle for
all variants of that task. The production panel registry includes Q1.1 and
Q1.2. The compiler binds the complete caller bundle into the scenario; the
driver selects only its own variant and active phase for model input.
`run_train_cell` and the Python `run_train_panel` controller accept a
caller-owned `history_admission_port`. The CLI does not fabricate one.
`install_drivers` remains available for explicit local dependency injection.

The resolver must return the exact bundle whose digest is frozen in the
scenario base evidence. The transition is closed to
`replace_public_measurement` and requires a nonempty caller-supplied reason.
Q1.1 requires caller admission receipts for both records; Q1.2 requires one
when an M2 claim uses the before-record. An admission receipt includes the
exact `record_digest` it verified; the driver rejects a mismatch and carries it
with the evidence-root material. There is no default admission path.

Q1.1 schedules `history_baseline`, `history_rebuilt`, and `final` for the
selected public-history material. The first request contains the frozen
before-record; both arms then apply the replacement and send the same
current-record to the second and final requests. M3-off retains the pre-change
history context while M3 rebuilds it. Variant labels are committed by hash
rather than exposed to the model.

Each request receives a projection containing only its active public record and
the selected historical material. The full frozen bundle, including other
variants and the inactive record, remains outside the model payload.

Q1.2 schedules `upstream_before_withdrawal`,
`downstream_after_withdrawal`, and `final`. Its pre-transition projection holds
only caller-supplied pre-summary and upstream claim text. The post-transition
projection then introduces the action, withdrawal state, post-summary, and
caller-supplied downstream claim text. M2 creates revisioned claims and, for
registered/withdraw variants, an explicit dependency. Withdrawal invalidates
the upstream root and refreshes dependent claims. M3 records the before/after
contexts while M3-off retains its frozen control context. These traces are
engineering provenance only: no Docker benchmark execution, scoring, truth
label, or scientific result is produced.
