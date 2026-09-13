# Q1.1 and Q1.2 history panel drivers

`freeze_history_bundle()` accepts caller-supplied public evidence and complete
Q1.1/Q1.2 historical records, verifies the task identity and variant coverage,
then freezes one bundle for all variants of that task. `install_drivers()` takes
a resolver for that bundle and installs Q1.1 and Q1.2 only into a
caller-owned driver mapping. The production registry remains unchanged until a
separate integration change chooses to register them.

Q1.1 schedules `history_baseline`, `history_rebuilt`, and `final` for the
correct, wrong, and neutral selected public-history materials. The material is bound to
the current public task identity. Variant labels are committed by hash rather
than exposed to the model. M3 creates a journaled rebuild after public evidence
changes; M3-off uses a frozen baseline control.

Q1.2 schedules `upstream_before_withdrawal`,
`downstream_after_withdrawal`, and `final`. M2 creates revisioned claims and,
for registered/withdraw variants, an explicit dependency. Withdrawal invalidates
the upstream root and refreshes dependent claims. M3 records the before/after
contexts and passes the complete rebuilt material to later requests. M2/M3-off
arms preserve a frozen control context. These traces are engineering provenance
only: no Docker benchmark execution, scoring, truth label, or scientific result
is produced.
