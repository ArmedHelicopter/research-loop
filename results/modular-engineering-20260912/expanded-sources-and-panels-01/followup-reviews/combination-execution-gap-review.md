# Combination execution gap review

Reviewed at integration commit `6ac59ba`.  This is a read-only implementation
review.  It did not read labels, validation payloads, or network services, and
it does not claim that any combination has been run or measured.

## Finding

The programme can enumerate the required 36 pairs, five triples, and a full
plus leave-one-out design, but it cannot construct them as executable
`FrozenPanel` instances today.  The current coverage is routing metadata, not
an execution surface.

`Compatibility` is not the blocker.  Its `all_pairs`,
`conditional_factorial`, and `leave_one_out` methods construct the legal
factorial designs and retain structurally unavailable cells.  In particular,
it does not prune a module because an earlier singleton result is null.

The first actual blocker is `FrozenPanel.__post_init__` in
`research_loop/modular/panel_receipts.py`:

* `scope_ids` must be registered Q ids, and `legal_arm_grids` must have exactly
  those keys.
* for each scope id, a non-P0 design must have factors equal to that single
  registry entry's `modules` set.
* every task group must contain that entry's registered variants crossed with
  that entry's legal arms.

There is no registered scope for a pair such as `(M1, M2)`, for a required
triple, or for full/LOO.  Supplying `conditional_factorial(("M1", "M2"))`
under a Q id whose declared module set is, for example, `("M4",)` is rejected
before any cell is made.  Supplying a new combination id is rejected as an
unregistered scope.  `compile_train_panel` reproduces the same restriction:
it derives one grid per Q specification with `obligation_grids`, then creates
cells from Q variants.  Its `CombinationObligations` value records the 36/5/
full/LOO names but serializes its state as `routing_only` and never maps an
obligation to a grid, cells, packages, scenarios, runtime receipts, or a
contrast result.

The second blocker is execution.  `panel_runner.run_train_cell` admits only a
registered Q scenario and looks up `DRIVERS[cell.coverage_id]`; `DRIVERS`
contains only `Q3.1`.  Therefore the compiled 48-Q panel cannot execute every
registered Q item, and there is no driver for a pair/triple/full/LOO cell.  A
passing `PanelReceiptVerifier` on a manually built Q3.1 panel verifies trace
binding and complete declared-cell coverage; it does not infer that the
`CombinationObligations` metadata was executed.  The verifier itself reports
the limitation `combination routing_only: no contrast matrix was measured`.

## Minimal decoupling

Add a *separate* combination-panel contract rather than weakening Q-panel
checks or inventing combination Q ids.

1. Define `CombinationDesign` (or `FrozenCombinationPanel`) with an explicit
   `obligation_id` (`pair:M1+M2`, a preregistered triple id, `full`, or
   `loo:M4`), `estimand`, frozen `Compatibility` design, fixed background,
   feasible-cell list, contrast/alias matrix, target bundle digest when one is
   predeclared, and an explicit `not_identifiable`/`blocked` state.  Require
   exact rebuild with the existing `validate_design`; retain all cells returned
   by `factorial` or `leave_one_out`, including structurally unavailable ones.
   The design must be frozen before runtime receipts exist.

2. Reuse `PanelCell`, `RuntimeReceipt`, `ScientificScorerReceipt`,
   `ValidationAcceptance`, `RunSession`, and `PanelReceiptVerifier` by
   generalizing their **scope binding**, not by relaxing arm validation.  Add
   a typed cell owner such as `owner_kind in {"q", "combination"}` plus an
   immutable owner/design digest.  For `q`, preserve the current registry and
   Q-variant rules exactly.  For `combination`, verify each cell arm is exactly
   the executable arm of the frozen combination design, all predeclared
   feasible cells occur for each paired task/replicate, and each package digest
   binds one declared arm.  Give structurally unavailable cells immutable
   reasons in the design; do not create fake runtime rows for them and do not
   call them failed runs or measured effects.

3. Add a `CombinationWorkflowDriver` selected by the typed owner rather than
   `DRIVERS[coverage_id]`.  It must accept only a frozen public task, scenario
   / objective, exact arm/package, and fixed call plan; journal every call via
   `RunSession`.  It should run the same public task and source group across
   every feasible arm.  A missing driver, infeasible package, budget breach,
   failed callback, or absent source group must emit a trace-bound blocked or
   failed receipt and prevent scoring/acceptance.  It must not fall back to a
   Q driver or synthesize a favourable candidate.

4. Keep the existing verifier/custody path as the common gate: complete runtime
   coverage first, independent scorer receipts only for successful cells,
   calibration receipt and consumed custody lease only on a validation panel,
   then a separately signed acceptance result.  Extend the verifier to bind
   the combination design digest, fixed background, feasible cell schedule,
   estimand and score scale into its panel digest, lease schedule, scorer
   receipt verifier and acceptance receipt.  It should return engineering
   verification when only journals are valid, never scientific acceptance by
   default.

5. Put contrast estimation after independent scoring.  It must consume the
   complete predeclared feasible-cell score matrix and emit either a frozen
   contrast receipt or `not_identifiable` with the actual missing/aliased
   condition.  A `not_identifiable` result is retained as an unmeasured
   obligation; it cannot be rewritten as a zero interaction or a passed
   control.  Full/LOO should use the same mechanism with estimand
   `leave_one_out_at_full`, and only legal LOO cells can enter that estimator.

P0 remains a fixed control-plane binding for each combined arm; it is neither
a binary factor nor a fabricated contrast.  The combination panel can carry
the existing P0 fixed-control digest in every request and retain the current
fail-closed check in `PanelReceiptVerifier._verify_runtime`.

## Smallest useful delivery slice

Implement one pair panel (a pair whose four cells are legal) plus one
structurally unavailable pair.  The integration test should construct the
combination panel, execute every feasible arm over both public adapters through
the common `RunSession` driver, retain all journals, verify them through the
existing receipt verifier, reject a removed cell/wrong background/wrong arm,
and report `engineering_verified` only.  A separate test should prove a
positive combination cannot be chosen by singleton score: all declared pair
obligations remain constructible before outcomes.  Add a scored validation
test only once an independently configured scorer, custody lease, calibration
receipt, and acceptance authority are available; fixtures remain engineering
checks and do not establish an interaction or scientific effect.

This path preserves the current Q48 registry for Q coverage while making C2--
C5 actual panels.  It does not claim all 36 pairs/five triples/full+LOO are
measured until each has a frozen design, full trace-bound runtime matrix, and
the relevant independent scoring/acceptance evidence.
