# Remaining restricted-builder artifact adapters

2026-09-14. Read-only design from source `cd12b9b`; implementation not yet made.
These adapters remain part of the user's all-module/all-output requirement.

## Preserve the different study contracts

- `state_improvement_build.run_build` executes one TRAIN-history proposal slot,
  records `state_improvement_proposal_terminal`, then selects the proposed
  builder when M9 is enabled or the fixed builder otherwise. Its model session
  is already terminal when the restricted build starts. The selected DSL,
  parent manifest, raw return and candidate/receipt files currently exist in
  separate phase logs, without the new per-output catalogue graph.
- `metaprogram_training` Q6.3 uses a proposal session under `proposal/`, invokes
  an evidence-only builder proposal using public histories and target input
  declarations, then calls `plan.selected_builder(proposed, cell)`. It uses the
  parent's actual training manifest; a current proposal task must not silently
  be added to that manifest to satisfy a C4-specific input check. Candidate
  execution/acceptance has further original plan-controlled operations.
- `scenarios_improvement` is explicitly fixture-only. Q6.3 uses two search units,
  can select the fixed DSL without a preceding model response, and uses a
  registry for meta activation. It also creates optimizer, activation and
  rollback artifacts in other questions. Do not describe this fixture as a
  prospective benchmark execution path or force a one-unit C4 allocation.

## Implementation boundary

Factor the M9 durable output writer and its read-only output-state verifier from
the C4-specific selection/invocation verifier. Reuse ordered raw-return,
individual-file and failure-terminal preservation. Make the actual manifest,
selected DSL, parent, search allocation and selection witness explicit inputs.
Keep the C4 adapter's existing exact response, recipe, membership and selection
checks; do not weaken them to accommodate another host.

Each additional host must create and verify its own selection witness using its
existing plan/phase/provider replay. Ordinary/fixed selection must preserve its
real meaning, not fabricate an ordinary-revision response or a missing prior
invocation. A failed output-state verification result cannot satisfy a successful
enclosing study stage. Metadata and read-back paths must not reactivate an
already terminal model session or dispatch new model work.

Keep raw returned components even when one is malformed. Preserve the original
exception and irreversible local writes on later failures. A reader must not
recreate missing files. Describe search/attempt units separately from paid API
or total resource usage. Registered inputs that influence TRAIN configuration
must not be relabeled as task evidence or silently added as cross-task parents.

## Required verification before claiming coverage

Exercise each actual writer and existing success reader for enabled/fixed modes;
exercise original failed returns and partial writes; coherently change the
selection, subject, candidate, allocation and terminal state and confirm the
host reader rejects the mismatch. Preserve old failure artifacts and exact
source ZIPs. Run existing Q6.3 and state-build integration checks using synthetic
peers plus actual restricted interpreter and Docker where those stages require
them. These are engineering checks and do not replace real TRAIN effects,
combination studies or sealed VAL acceptance.
