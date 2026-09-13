# Q1.1 and Q1.2 history panel drivers

`freeze_history_bundle()` accepts caller-supplied before/current public records,
a frozen replacement transition, and complete Q1.1/Q1.2 historical records.
It verifies the task identity and variant coverage, then freezes one bundle for
all variants of that task. `install_drivers()` takes
a resolver for that bundle and installs Q1.1 and Q1.2 only into a
caller-owned driver mapping. The production registry remains unchanged until a
separate integration change chooses to register them.

The resolver must return the exact bundle whose digest is frozen in the
scenario base evidence. The driver records public observations as unadmitted;
it does not manufacture a trusted validator or scientific admission.
When Q1.2's M2 arm needs a claim supported by that observation, the caller
must supply an admission port and its typed verified receipt. There is no
default admission path.

Q1.1 schedules `history_baseline`, `history_rebuilt`, and `final` for the
selected public-history material. The first request contains the frozen
before-record; an enabled M3 transition journals its withdrawal/replacement and
the second and final requests contain the current-record. M3-off retains the
before-record and frozen baseline control. Variant labels are committed by hash
rather than exposed to the model.

Each request receives a projection containing only its active public record and
the selected historical material. The full frozen bundle, including other
variants and the inactive record, remains outside the model payload.

Q1.2 schedules `upstream_before_withdrawal`,
`downstream_after_withdrawal`, and `final`. M2 creates revisioned claims and,
for registered/withdraw variants, an explicit dependency. Withdrawal invalidates
the upstream root and refreshes dependent claims. M3 records the before/after
contexts and passes the complete rebuilt material to later requests. M2/M3-off
arms preserve a frozen control context. These traces are engineering provenance
only: no Docker benchmark execution, scoring, truth label, or scientific result
is produced.
