# Q1 history and evidence fixture scenarios

`research_loop.modular.scenarios_history.run_history_scenario()` runs Q1.2--Q1.7 against one prepared `PublicTask` plus a closed `FrozenRecord` of public task, evidence, and budget digests. It accepts no dataset path, labels, gold output, scorer result, optimizer state, or validation feedback. The optional next-model callable receives the actual post-manipulation payload; tests capture that invocation without calling a real model.

Every trace and payload says `fixture_only: true`. The injected statements are synthetic mechanism fixtures, not observations and not evidence of a benchmark effect. The task, source digests, and budget digest are carried through unchanged. Only predeclared auxiliary representation, ordering, withdrawal, topology, and information-kind fields vary.

| Experiment | Runnable variants | Mechanism exercised |
| --- | --- | --- |
| Q1.2 | `summary_only`, `registered`, `withdraw` | Unattributed summaries request review only; registered dependencies receive propagated revisions after upstream withdrawal. |
| Q1.3 | `log`, `report`, `summary`, `memory` | Multiple representations of one root remain one active evidence root. |
| Q1.4 | `one_withdrawn`, `all_withdrawn`, `copies` | Partial revocation retains the other qualified fixture chain; copied roots do not add support. Distinct IDs never establish independent origins. Fixture qualification is explicit and the statistical source group stays the task identity group. |
| Q1.5 | `blind_first`, `summary_first` | M5 receives a sealed public-evidence snapshot and records review order. The trace does not claim either order is scientifically superior. |
| Q1.6 | `replacement`, `none`, `high_score` | Invalid evidence is withdrawn before any replacement question. An old score is auxiliary narration, never support. |
| Q1.7 | `irrelevant`, `causal`, `unknown` | Irrelevant narration is excluded; causal order is represented through current evidence; unknown remains a permitted state. |

These are integration-verified fixture mechanisms only. They are not train or validation measurements and cannot advance an experiment ledger to a scientific decision without the frozen dual-benchmark receipts required by `experiments.py`.
