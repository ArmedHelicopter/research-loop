# Caller-bound exploration drivers Q7.3–Q7.6

These drivers add real operations for the four remaining Q7 questions. They use
caller-frozen public **train** materials, a source-bound input resolver, actual
restricted Docker executions and an independently configured observation port.
They do not change P0, the common registry/controller, custody splits, validation
leases or the frozen Q7.1/Q7.2 implementation. The root integration owns the
formal common entry point; this worktree installs its drivers explicitly in tests.

## API and caller contract

`freeze_extended_exploration_bundle(task, materials=..., budget=...)` requires a
typed `PublicTask`, all variants of all four questions, exact source/version
bindings and these matched opportunity budgets:

| Question | Model calls | Docker opportunities | Verifier calls | Main cells |
|---|---:|---:|---:|---:|
| Q7.3 | 3 | 4 | 8 | 16 |
| Q7.4 | 3 | 2 | 4 | 24 |
| Q7.5 | 3 | 1 | 2 | 32 |
| Q7.6 | 4 | 1 | 2 | 16 |

Each variant supplies `source_id`, `data_version`, `public_issue`, a typed
`hard_constraint`, a two-source `authority_contract`, actual public `jobs`, and
question-specific `config`. Each job has a literal program/hash, digest-pinned
image, exact input hashes/sizes, one execution/token unit and a source-bound
measurement contract. Legitimate unavailable resources or authorization are
retained as blocked opportunities; malformed bindings are rejected.

Question configuration is explicit:

- Q7.3: four distinct ratio IDs/percentages, one common control allocation, four
  main job IDs and four diagnostic job IDs. All ratios share identical jobs,
  source, issue, authority and role order, and must induce distinct actual quotas.
- Q7.4: old/repair job IDs and an instrument ID. A repair can be tested without
  presuming it works; the follow-up can remain invalid.
- Q7.5: observation job ID plus separate observation and novelty claims.
- Q7.6: observation job ID, theory and intended construct.

`extended_exploration_injection(...)` binds the bundle into a frozen scenario.
`install_drivers(target, broker=..., input_resolver=..., authority=...)` installs
all four `ExtendedExplorationDriver` instances. The resolver and execution
helpers currently use the compatible APIs in the frozen base; root may replace
their imports with the equivalent public `panel_execution` interfaces.

The authority implements `verify_preflight(subject)` and
`verify_observation(subject)`. It uses the Q7.1 observation receipt schema plus
the exact `facets` contract: mechanical status, semantic status, diagnostic
value, main progress, prior-art status and old-instrument status. It receives
the **complete** execution receipt, actual program bytes and independently
rechecked public CSV bytes. Those bytes, host details, source documents and
authority identities are excluded from model module context. Dual audit
signatures are checked separately; they do not establish observation truth by
themselves. The caller must actually verify the frozen measurement contract.

All available jobs are source/hash/size checked before the first model or
verifier I/O, including unchosen jobs. Inputs are checked again at execution and
before trusted observation. Reservations precede I/O; raw and typed partial
verifier responses precede validation. Failed/unknown costs remain distinct
from zero and reported exception cost does not become an additional charge.

## Actual interventions

Q7.3 uses `ExplorationBudget` to reserve and execute the diagnostic/main
allocation. The control uses the same fixed control percentage at each ratio.
Caller-verified effective diagnostics, wasted diagnostics and completed main
observations enter the next request. Scientific main completion requires fixed
P0 qualification. Successful process exit cannot establish any of these metrics.

`freeze_ratio_selection(task, bundle)` fixes the criterion before calls; each
Q7.3 trace records that plan before its prospective request.
`select_training_ratio(task=..., bundle=..., panel=..., runtimes=...)` requires a
complete engineering-verified panel and all four ratios in both arms for the
task. It validates the exact job/config/authority/schedule binding and unique
execution indices, retaining all eight rows. The fixed score is main completed
plus effective diagnostics minus waste; ties favor less exploration, then ID.
Missing/unknown required observations give no selection. The caller-owned trace
and observation port remain trust boundaries: trace consistency is not a new
independent scientific scorer, and the chosen ratio has no validation authority.

Q7.4 executes the old instrument, then either the proposed repair (M7) or the
original instrument again (control). M1 records `InstrumentRepair` only after a
source-verified invalid old instrument. The old raw observation remains stored
and unadmitted; no initially valid audit is fabricated for known invalid data.
Only a new qualified execution can support a result. A separate adversarial
Docker test submits the old ID after a successful repair and confirms fixed P0
blocks the unchanged candidate.

Q7.5 exposes the four independently audited state dimensions through M1. M2
uses real claim and evidence ledgers to update observation and novelty claims
separately. A verified prior-art match is a task-bound observation with the
external receipt hash as provenance, not a fabricated independent data family.
Refuting the novelty claim leaves the valid measurement root active. A pending
data/feasibility qualification retains undetermined scientific support.

Q7.6 executes the observation and obtains a real semantic review response.
M5 seals that response before revealing the earlier prospective assessment; the
control receives that assessment in its review request. Scientific admission
roots are created **after** the review response, so normal reconstructed context
cannot leak the authority's verdict into the independent review. M1's scientific
disposition and the review's actual judgement then enter the diagnostic request.
Mechanical checks, reviewer acceptance and qualified scientific evidence remain
separate. Neither a review answer nor a variant ID controls the P0 outcome.

Every final model response is passed unchanged to `RunSession.finish`. The
drivers do not replace all outcomes with unknown or rewrite a failed overclaim.

## Frozen verification and limits

Executable source froze at `973f112`; its Git blob, pre-run file and post-run file
all have SHA256
`9f17edfa1e0d5b60bd69e2578c02a033a8db6955aaef57da8853496a7f639629`.
The final suite passed **18 tests in 297.276 seconds** with pytest 8.4.2 and
PyYAML 6.0.3 in the existing isolated `custody-root-venv`. No dependencies or
shared environment were modified. Original wheel provenance is unavailable.

The main 88-cell grid completed 160 Docker executions, 280 model requests and
responses, and 320 verifier requests/results. Terminal decisions were 40
`proceed`, 16 `closed_negative`, 24 `invalid` and 8 `unknown`. Every final
candidate digest matched the raw model response. Both synthetic task adapters
selected ratio 25 under the predeclared fixture utility; this is not evidence of
a generally optimal ratio. Source drift consumes zero model/verifier calls;
hard missing resources/authorization retain both-arm denominators. Actual
post-Docker byte drift, partial costs, inconsistent semantic/audit facts and old
invalid evidence are covered by separate tests.

Earlier failures remain archived: live-r1 reached four real executions before
a final-context field error; live-r2 completed 41 main cells before the Q7.5
ledger contract rejection. Two direct seam-test constructor failures are also
retained, followed by the repaired seam check and three successful real Docker
claim/review paths. They are not erased or counted as fresh successful cells.

All data are newly authored public synthetic CSVs and programs. The model port
is a local deterministic test fixture, including deliberate anchoring behavior
to verify M5 context effects. The authority recomputes actual CSV/program/stdout
against frozen control and construct documents. These results establish the
tested engineering paths, not real-model efficacy, real benchmark performance,
independent scientific discovery or programme completion. No paid model,
network, validation or deployment calls were made.

The machine manifest `exploration_extended_verification.json` includes every
JUnit path/hash, source hashes, preserved failure counters, full ratio selection
rows and exact trace paths/hashes. Main traces are at:

`E:/_ryanDev/AI/research-loop-modular/work/exploration-extended-checks/live-r3/test_full_88_cell_real_docker_0/runs/{index}/trace.jsonl`

with `index` 0 through 87. The final JUnit is
`E:/_ryanDev/AI/research-loop-modular/work/exploration-extended-checks/live-r3.xml`,
SHA256 `89ed335ee70de967786b2903b6f5076494c1d9ced95a493795f0217e4f206e17`.
