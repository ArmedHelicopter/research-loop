# Artifact host coverage gaps after C4 integration

2026-09-14. Read-only source inventory at commit `348017a`; the full SHA and
49 exact source hashes are in `artifact-host-call-sites-r1.json`.
The AST inventory found 128 call sites for the seven named entry types in
`research_loop/modular`. This is a call-site denominator, not 128 runtime outputs
or 128 missing bridges. Replay-only constructors and production writers are
listed separately through their enclosing scope; aliases/indirect dispatch
remain outside this AST check.

## All actual phase callers

| File in research_loop/modular | Runtime entry | Artifact bridge | Existing semantic reader |
| --- | --- | --- | --- |
| full_loo_driver.py | run_stage | Connected; C4 model context, frozen choice and retrieval parents | verify_stage calls verify_phase_artifacts |
| exploration_scheduler_combination.py | run_exploration_scheduler_cell | Missing | verify_exploration_scheduler_cell / verify_phase |
| execution_improvement_combination_driver.py | run_execution_improvement_cell | Missing | verify_execution_improvement_cell / verify_phase |
| admission_prediction_exploration_driver.py | run cell | Missing | host reader plus verify_phase |
| mechanism_scheduling_combination_driver.py | run cell | Missing | host reader plus verify_phase |
| mechanism_exploration_combination_driver.py | run cell | Missing | host reader plus verify_phase |
| state_exploration_combination_driver.py | run cell | Missing | host reader plus verify_phase |
| state_scheduling_combination_driver.py | run cell | Missing | host reader plus verify_phase |

Every missing entry produces allocation, selected programs, individual returns,
scheduler event lines and the phase receipt; enabled parallel scheduling also
produces SQLite state. Existing hashes and aggregate phase replay do not supply
the new per-output catalogue graph. The root confirmed all eight run_phase calls
in production source; exactly one passes artifact_bridge.

The current PhaseArtifactContext requires C4-specific model-context/choice/
retrieval parents. Other hosts can run a phase before their first model call and
without retrieval. Their next implementation needs an explicit phase-input
binding based on their actual task lock, material, selection and allocation,
with a corresponding reader. It must not invent M3/M6 parents to satisfy C4's
contract. Then connect each of these seven writers and readers, covering actual
enabled/disabled and failure execution for each distinct host seam.

## Restricted builder callers

`builder_artifacts.py` owns the new writer and its explicit replay constructor.
`full_loo_driver.py` uses that writer. Direct ports remain in:

- `metaprogram_training.py`: standalone metaprogram training candidate/receipt.
- `state_improvement_build.py`: state-driven TRAIN builder and candidate.
- `scenarios_improvement.py`: scenario-level builder dispatch.

These require adapters for their actual selection/invocation contracts; the C4
recipe-level and last-provider-response contract cannot simply be imposed on a
different study. Original outputs, failures and TRAIN subject binding must be
kept. `_checked_build`/existing history readers remain separate semantic checks.

## Other scopes that remain open

RunSession/ModularWorkflow instantiate the observed evidence, claims, context,
prediction and review implementations. The JSON inventory lists the other
constructors; readers that rebuild `_MemoryLog` state are replay code, not
unobserved production writers. Qualification authorities that run before
RunSession, P0 dataset/split/config custody artifacts, generic external-source
snapshots, cross-catalogue TRAIN configuration edges, resource attribution and
audit overhead still need their own complete output inventory and adapters.

This inventory does not promote code coverage to benchmark efficacy. All
original singleton/pair/triple/full/LOO/C5/Q6.3 experiments and VAL acceptance
retain their separate completion criteria.
