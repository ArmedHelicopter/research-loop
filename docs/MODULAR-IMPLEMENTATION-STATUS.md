# Modular implementation ledger

Goal: implement all 48 research scenarios, M1–M9 including the separate meta-program
stage, and C1–C5 combination experiments defined in the design documents.

## Per-event M1/M2 audit bridge (2026-09-14)

The isolated implementation records every RunSession admission operation and
every durable evidence/claim event, including direct ledger callers, withdrawal,
revision and downstream review propagation. Independent stage verification
reconciles the actual source logs and replays public ledger operations in order.
It returns historical snapshots for each model request, preserving the state
before a later withdrawal. See [the M1/M2 contract](M1-M2-ARTIFACTS.md).

Frozen r1 at `3c016a53e11366347cf6f29d368a30d9b622d5c1` ran 24 cases:
20 passed and four failed. The actual Docker history-to-target pipeline and its
independent stage verification passed. Three failures exposed error wrapping
that obscured ContractError reasons; the fourth exposed an old failure-test
assumption about the now-expanded journal and independent failure marker.
The original failed report remains unchanged. At `863cb5c6b87bb5389ea75203b2c83ff9c0a1dcd9`,
r2 reran those four cases and passed all four. Both runs retained 676 unchanged
source files. These are engineering checks with synthetic model responses and
no added paid API calls, not scientific benchmark or VAL acceptance results.

`results/modular-engineering-20260914/artifact-events-r1/` retains the exact
source ZIPs/JUnit/closures, original runtime logs from two successful and two
failed stages, independent review findings and the closed Grok stdin A/B
diagnostic. The M3 r1/r2 checks in this archive passed their tests but were later
found insufficient by independent review; their historical-state and projection
repairs are separately tested in the M3 worktree. The two Grok initialize-only
attempts both timed out, and settlement remains unknown. These records do not
establish model availability or complete artifact coverage.

Archive validation checks each recorded producer/bridge source against its
original frozen source ZIP even after the live file changes. A general runtime
historical-source resolver remains necessary before claiming old runs can be
fully reverified through the normal current-code entrypoint. Other module
writers and independent ledgers remain listed in the coverage document.

## Module artifact provenance: integrated and exercised (2026-09-14, earlier update)

The catalogue core and native history/target bridges are integrated. Descriptors
bind canonical payloads, actual producer source, configuration/check references,
task/domain identity and independent run IDs. Both append and disk reload reject
unassigned events falsely marked covered, invalid costs and visible validation
artifacts. Persistent seals bind count/head; the stage receipt independently
binds the seal and original file inventory. Native replay compares catalogue
trace entries to the original trace. A failed recovery journal preserves a
separate failure receipt and stops subsequent work.

Root source `9c07b35` passed 71/71 focused catalogue, runtime, typed-subject,
selected-snapshot, selection, scoped-lease and label-isolation checks with 670
source files unchanged. Root `11c81a0` then passed 3/3 actual native seam checks
in 582.875 seconds, also with 670 unchanged source files: complete representative
history-to-target execution, unknown MAIN failure, and artifact writer failure.
Root independently re-read four stage catalogues and their seals; the two
successful stages reconcile with trace, while the writer-failure stage retains
the expected trace/catalogue gap and an outer failed record with zero MAIN calls.
These use synthetic model responses and actual Docker, not real benchmark effect
or validation acceptance. They do not execute the complete 46-build/118-target C5.

Exact evidence is retained under
`results/modular-engineering-20260914/artifact-provenance-closed-r1/` and
`results/modular-engineering-20260914/artifact-native-root-r1/`. Root verified
seven prior passing source archives against their frozen before/closed maps,
JUnit and individual ZIP members, and separately verified the new native source
archive. Older partial/failing attempts remain explicitly non-passing.

The [coverage inventory](MODULE-ARTIFACT-COVERAGE.md) lists the actual boundaries.
There are bridges for P0 and selected M1-M9 outputs; this is not every output
of every module. Actual M3 contexts remain generic trace events. General typed
cross-subject catalogue edges, lifecycle/affected-descendant processing and
per-artifact environment/resource attribution remain outstanding. Tags cannot
replace independent TRAIN/VAL storage and custody access enforcement.

C5's complete controller, authenticated selector, scoped replay repairs and
nine-component snapshot factory are now integrated. Focused selection and
snapshot checks passed; the full controller remains unclosed after the retained
r2 timeout. No actual complete C5 selection, deployment or VAL acceptance is
claimed. All original questions and singleton/combination experiments remain
in scope, including combinations whose singletons are negative.

The C5 selected-bundle registration adapter is also integrated. Registration
authenticates the complete original TRAIN run, freezes the actual selected
snapshot and exclusively writes its nine component digests, source, TRAIN
history/selection provenance and component-to-bundle edges. Verification reads
exact original bytes without writing and reauthenticates the run before comparing
the complete registration. A bare record does not authenticate a run or grant
validation, scientific or deployment authority. This independent registration
does not yet connect general cross-subject edges into ArtifactCatalogue.

Latest isolated source `8d1bad9` passed 34/34 focused checks in 121.546 seconds
with 672 source files unchanged, including real snapshot projection across a
controlled authentication boundary, rehashed semantic substitution, exact-byte
rejection, exclusive creation and read-only verification. The complete-controller
test now calls register and verify through the actual authentication entry; that
full 930-synthetic-MAIN execution is still unclosed. Exact r1 and r2 originals are
retained at `results/modular-engineering-20260914/c5-artifact-registration-r1/`.
Root compared the tested Python sources with the integrated files and records
any Git newline conversion separately from exact byte equality.

## Module artifact provenance and closed Q6 cases (2026-09-14, earlier update)

The [module artifact provenance contract](MODULE-ARTIFACT-PROVENANCE.md) now
applies to P0, M1–M9 and every singleton/combination study. It requires resolvable
payloads, actual producer source/config bindings, typed dependency edges,
append-only lifecycle events, a stage-bound terminal count/hash, explicit
coverage gaps and separate TRAIN/VAL storage and access. The first isolated
implementation `ae2e70b` is under repair: review found missing terminal anchors,
insufficient payload/source binding and incomplete native stage verification.
It is not integrated or accepted as complete provenance coverage.

All twelve separately bounded native Q6/M9 engineering cases at `f0869c4`
have now closed successfully. Root independently checked the twelve archive
digests and all 17,990 original file members before importing 31 delivery files
under `results/native-build-all12-20260914/`. The original 45-minute batch
timeout remains a failed attempt. The delivery scope also records that one
failed partial Q6.6 archive was deleted during its creation; its test originals
and final archive remain, and the missing partial archive is not reconstructed
or represented as retained. These are synthetic-model/actual-Docker engineering
checks, with no actual benchmark effect or VAL acceptance.

C5 complete-controller attempt r2 reached its original 45-minute limit with
27/46 history builds completed and no target dispatched. The observed owned
process tree was closed by its watchdog. No pytest pass or complete controller
receipt exists. Its source, watchdog and partial denominator are retained at
`results/modular-engineering-20260914/c5-common-timeout-r2/`; original stage
files remain in the recorded work directory. Scoped replay performance repairs
and the selected nine-component snapshot remain in isolated worktrees pending
integration and complete verification.

The initialize-only Grok A/B diagnostic timed out under both the previous
configuration and the new isolation configuration. It sent no session or
prompt request. It does not establish the isolation configuration as the
cause. Sanitized exact source/configuration/closure evidence is retained under
`results/modular-engineering-20260914/grok130-initialize-config-ab-r2/`.
Usage and settlement remain unknown. All research questions and experiments
remain in scope; no acceptance threshold or data isolation rule changed.

## C4 completion checks and Grok isolation repair (2026-09-14, earlier update)

C4 source `840697c` passed the complete success grid and unknown-MAIN
denominator checks: 2/2 in 1104.297 seconds with 651 source files unchanged.
The success case exercised 169 synthetic MAIN opportunities, nine builds,
80 Docker executions and 22 independent scores. The unknown-MAIN case retained
all 22 blocked targets. This closes those engineering checks, not real-model
effect evaluation. The complete root evidence is retained under
`results/modular-engineering-20260914/c4-native-root-r1/`.

The explicit Grok 1.0.30 isolation repair is integrated through `805fbca`.
Root checks passed 36/36 in 15.359 seconds, including label isolation. It accepts
the documented internal reload response without treating it as a completion,
excludes skill sources through the native configuration, and allows the CLI's
empty plugin registry lock while rejecting registry data. These are synthetic
ACP checks. The admitted model remains Grok 4.6 through the existing subscription;
Daybreak is not a requirement in this implementation or experiment protocol.

Actual readiness r3 then timed out in 61.453 seconds before an initialize
response. The transport wrote only initialize: no session or prompt request,
zero prompt reservations, and empty native stdout/stderr. Accepted remains false;
unknown usage or settlement is not converted to zero. This initialization
failure is separate from r2's post-prompt reload rejection. Exact source,
configuration, envelope and closure are retained under
`results/modular-engineering-20260914/grok130-readiness-r3/`; private login bytes
and streams are excluded. No benchmark or validation data was sent.

C5's complete controller and authenticated TRAIN selector are implemented in
their isolated worktrees. Selector arithmetic and label checks passed 19/19,
including a case where negative singletons combine positively. This is not a
completed full-controller result. The full 46-build/118-target check remains
unclosed at this update; no selection or validation acceptance is claimed.
All 48 questions and all singleton, pair, triple, full/LOO and final joint studies
remain in scope. Optimization may access TRAIN only; VAL remains acceptance only.

## Native Q6/M9 integration and common C5 runtime (2026-09-14, earlier update)

The separate Q6 and M9 native provider implementation is now integrated through
`5619cd5`. Its root check passed12/12 in65.985s with645 source hashes unchanged,
including an actual restricted build, the complete separate Q6.3 fixture and
its failed-call denominator. The owner execution-family check at `f0869c4`
closed1/1 in956.546s: six builds,70 synthetic MAIN opportunities,96 Docker
executions and32 independent scores. The previous12-case45-minute timeout is
retained without a pytest pass claim. Other owner cases remain separate work;
neither this one success nor partial earlier controller scores complete them.

The C5 runtime kernel is integrated from `11243b2`. Root `0644e32` passed22/22
runtime/panel checks in166.687s with648 unchanged source hashes. It uses actual
module consumers, restricted builds and Docker, replays the original protocol
file, and reconstructs stage/barrier bindings from original inputs. Its formal
catalogue remains59 recipes,46 history builds and118 targets for two TRAIN tasks.
The exercised kernel path contains only one history and one target with11
synthetic MAIN opportunities. Successful full history barrier to formal target,
complete-grid scoring, authenticated TRAIN selection and validation acceptance
remain outstanding. No actual model efficacy or validation result is claimed.

The imported kernel archive's10 Git blobs and5,936 raw ZIP members were checked
against disk. Closed root and native owner evidence is retained under
`results/modular-engineering-20260914/native-build-q6-root-r1/`,
`c5-runtime-root-r1/` and `native-build-owner-closed/`.

## Common C5 scorer and native deployment checks (2026-09-14, later update)

The new common TRAIN panel/scorer scope is integrated from `712d242`:44/44
checks,639 unchanged source files. Root `b31acf2` subsequently passed23/23
integration/label checks with639 unchanged files. It preserves the full recipe-by-target grid,
history-only packages, full-protocol build identities and the frozen ranking
rule. A real independent scorer process accepted synthetic signed candidates
from both primary benchmarks. The earlier43/44 fixture-hash failure is retained.
This is a scoring boundary; actual common history/target execution, authenticated
selection and validation acceptance remain outstanding.

Isolated Grok1.0.30 deployment and its response-before-inventory compatibility
repair are integrated. Independent frozen checks passed115/115 and124/124;
root deltas passed30/30 and39/39. These are synthetic checks. Both imported
archives have20 Git blobs and5,567 raw members verified against disk and ZIPs.

Actual separately frozen readiness r1 returned a session but stopped before
billing/prompt because inventory had not yet arrived. After the ordering repair,
r2 received explicit empty-tool inventories and passed the included-subscription
and no-topup check, then wrote one prompt. An unsolicited `skills-reload` response
caused `rpc_binding` rejection before terminal usage. Its MAIN usage and possible
initial TITLE/all-settlement totals remain UNKNOWN; this is a spent failed
attempt, not a zero-cost success. No third probe or permissive reload handler was
introduced. Exact source snapshots, closure and frame hashes are retained under
`results/modular-engineering-20260914/grok130-readiness/`; private native streams
and opaque login copies are not published. The pinned public implementation
reloads skill baselines, so the response is not presumed harmless to context.

The parallel C4 source `61fea55` closed its complete success check1/1. Its final
accounting-drift assertion is repaired and being checked separately. The other
12-case native build batch hit its45-minute wall; no final JUnit was emitted and
no pytest pass count is claimed. Original state/mechanism controller receipts
record22/22 and24/24 scores; remaining cases retain incomplete/not-started states.
A bounded duplicate-replay repair at `f0869c4` passed58/58 independently, reducing
one tested verify_build boundary from5 to3 fresh provider inspections. This is
not yet evidence for complete-batch speed or completion of the12 cases.

## Ordinary native ports and Grok initialize observation (2026-09-14)

The ordinary native source chain is integrated through `db11758`. Its independent
11-family checkpoint passed82/82, with258 cells,816 synthetic MAIN opportunities,
498 Docker attempts and258 scorer calls; Q3.2's final historical/current-status
repair passed14/14. Root frozen `d40c6cd` then passed78/78 integration checks with
632 unchanged source hashes, covering provider compatibility, singleton dispatch,
Q3.2, final provenance faults and label isolation. The full family grid was not
repeated. Exact sources, failures/qualifications and original receipts are retained
in the ordinary archives; root verified their24 Git blobs and34,571 raw ZIP members.
These are engineering checks, with no real model/API calls or validation access.

One separately reviewed initialize-only Grok1.0.30 diagnostic returned its ACP
response after29.844s and closed at30.0s, without session/account/prompt RPCs.
Standard model/settings/announcement notifications then triggered the unchanged
strict diagnostic's rejection. Its accepted_initialize=false remains preserved.
The normal transport already handles those notification names. A returned
initialize response does not prove generation, tool isolation or billing readiness;
the minimal versioned native deployment/readiness path remains to be connected.
Exact reviewed sources and numeric OS metadata are in
`results/modular-engineering-20260914/grok-initialize-wct/`; raw native frames and
opaque login copies are excluded. Earlier timeouts remain part of the record.

## C5 atomic component snapshot and provider replay (2026-09-14)

The C5 local deployment port now represents every enabled module with separate
source, configuration, state and TRAIN provenance digests. It publishes the
complete bundle and consumes the independent acceptance in one SQLite
transaction. Rollback restores the exact prior bundle. Tasks keep one whole
snapshot across concurrent activation. This is a new local port, separate from
the older M4/M5 prepared handoff; its upstream C5 acceptance issuer and actual
TRAIN-selected target are still missing.

Frozen `fc11452` passed 82/82, including a real RunSession request carrying nine
synthetic component payloads, competing processes, failure after each component
write, transaction-tail failure, complete rollback, source drift and restart.
The first attempt retained 20 failures caused by passing a mapping to the
compatibility interface; its repair passed 79/79. Independent review then found
that a different envelope could reuse an acceptance after rollback. The final
repair uniquely consumes the original acceptance digest and reconstructs past
consumption on reopen. Independent re-review found that defect closed.
Exact tested sources and all attempts are retained under
`results/modular-engineering-20260914/c5-joint-deployment/`.

Separately, provider phase verification now performs one fresh original replay
instead of two in the same call. Frozen `0c5c63e` passed 67/67 across both
provider types, later file/configuration drift and terminal refusal. It is not
a persistent cache and does not grant sealing or scoring authority. All red
and repaired attempts remain in the `provider-observation/` archive. No overall
throughput improvement is inferred. These are synthetic engineering results;
neither checkpoint performs real model generation or validation acceptance.

## Final native provenance gates (2026-09-14)

The native M4/M5 path now checks original records after scoring and at final
contrast/report boundaries. Two complete eight-cell regressions reproduced
the old error: a late original-file change still released an estimated
contrast. The repair retains every authenticated scorer return but exposes
zero eligible scores and an inconclusive contrast when provenance fails.
Native attempt/receipt schemas are v2; legacy Codex schemas remain v1.

Frozen source `acde220` passed 42/42, including the complete native grid, both
late-fault cases, old useful controls and label isolation. The earlier run on
the same source passed 35/42 because seven legacy fixture preflights detected
the real user configuration above their temporary directory. No admission
rule was relaxed; a fresh C:/codex-modular-checks directory outside that user
profile resolved this environment issue. Both runs and the initial 2/2 failing
regressions remain archived with exact tested source bytes.

Root source `75056cf` separately passed 25/25 for originating-session-bound
phase aborts, terminal usage snapshots and labels. Integration `2f37cee`
combines these source closures; no additional combined rerun is claimed.
The archive at `results/modular-engineering-20260914/final-provider-provenance/`
also retains earlier helper failures, explicit archive exclusions and source
recovery receipts. New frozen runs save source ZIPs before execution.
These are synthetic engineering checks; real calibration, remaining native
controller grids and C5 TRAIN selection/independent acceptance remain pending.

## C4 runtime and shared provider checkpoint (2026-09-14)

The full/leave-one-out controller now completes its 22-cell engineering grid:
nine canonical history builds, 169 scripted model calls, 80 actual Docker jobs
and 22 independent process scores. All legal removals, B0, the useful ordinary
control and both structurally unavailable minus-M2 rows remain represented.
M8 changes target scheduling only; M9 builds candidates from TRAIN history.

Root checks retained two real integration failures and their repairs. Initial
source `29f4b7` passed 20/21 checks and exposed short workers finishing before
the next ready lease was persisted. Source `3e750be` passed 26/26 after batching
ready reservations. The later merged source `ea0d9d7` passed 142/143, including
C4, but found two equal timeout jobs colliding on a clock-derived container
name. Per-invocation nonces repair that collision. Final focused source
`a1b4151` passed 104/104 with 617 source/document hashes unchanged, including
fixed-clock concurrent naming and actual timeout cleanup. These checkpoints
provide accumulated coverage, not one final 143-test rerun. Original evidence
is in `results/modular-engineering-20260914/c4-provider-root/`.

The core provider and ordinary native preflight now bind original native
configuration, explicit per-cell call spans, historical usage and terminal
failure snapshots. These snapshots cannot authorize scoring. The C5 preparation
also replays original M4/M5 source journals and freezes a complete synthetic
target/control/ablation identity grid; it cannot select, lease, accept or deploy.
Their source archives, original failures and nested ZIP members were verified
against committed bytes after integration.

The 90-entry routing inventory retains 48 question IDs, 36 pairs, five triples
and C4, with Q6.3 counted once inside the 48. Native execution coverage remains
under implementation in three isolated worktree lines: ordinary experiments,
Q6/M9 history phases, and C4. Their subsequent controller closures are not
established by these foundational checks. C5 joint selection and acceptance
remain separate unfinished work.

Two isolated Grok CLI 1.0.30 initialize-only runs timed out, including a bounded
128-output-cap comparison. Each sent one initialize and no model prompt; both
cleaned up. This establishes neither startup readiness nor the failure's cause.
Safe original evidence is retained under
`results/modular-engineering-20260914/grok-130-initialize/`. Real authoring,
calibration, TRAIN effects and sealed validation acceptance remain unfinished.

## Merged native TRAIN provider repair (2026-09-14)

Root source `834b3b6` passed 33 integration checks with all 588 frozen
source/document hashes unchanged. The repaired Grok entry creates fresh native
contexts and exact per-slot configurations, verifies original native requests,
responses, reservations and usage, and durably stops dispatch after provenance
failure. Its eight-cell M4/M5 panel completed 40 synthetic MAIN calls, eight
Docker executions and eight independent scores; unknown MAIN and provenance
failures retain all eight rows and the known consumed usage. Authoring and
diagnostic worker seams pass alongside it. Evidence is in
`results/modular-engineering-20260914/grok-provider-root/`.

The root independently verified all 1,252 imported source-archive files,
including both original ZIPs. Checkout text conversions, their byte repairs
and the original failed verification attempts are preserved. These are
engineering and provenance checks; no actual model generation occurred.

The native provider currently admits only the fixed M4/M5 v4 panel. Explicit
provider portability for the other registered controllers is being implemented
in an isolated worktree. Grok CLI 1.0.30 also timed out before session creation
in a separate one-initialize/no-prompt observation; the cause remains unknown.
Real material generation, calibration, TRAIN effects, final bundle selection
and independent validation acceptance remain unfinished.

## Merged provisional material-authoring seam (2026-09-14)

Root source `986c25c` passed 36 focused integration checks with all 585 frozen
source/document hashes unchanged. Four synthetic authoring sessions produce
signed provisional materials and a complete future review inventory; existing
diagnostic worker execution, native binding rejection and label isolation also
pass. All 36 slots and 72 evaluator opportunities remain represented, including
unsupported categories. Evidence is in
`results/modular-engineering-20260914/authoring-root/`.

The source authoring and initialize-only archives were independently verified
after merging, including all committed bytes and ZIP payloads. The M9 cost
replay archive is also merged and verified. Its checkout normalization mismatch
and exact committed-byte repair are retained in the root archive.

The real authoring attempt remains a pre-prompt initialization failure with no
accepted material. An isolated newer Grok CLI is undergoing a separate startup
check; no model, account, quota or tool property is inferred from its version
output. No actual generation or validation access occurred in this checkpoint.
Real calibration, TRAIN effects and final validation acceptance remain open.

## Complete pair/triple controller engineering coverage (2026-09-14)

Root source `ee8b45a` passed 32 integration checks with all 580 frozen source and
document hashes unchanged. The initial command named a nonexistent label test;
its zero-test failure is retained, followed by the corrected passing selection
at the same source commit. Evidence is under
`results/modular-engineering-20260914/remaining-combinations-root/`.

The added M3×M6×M9 grid completed 16 targets and scores after two shared history
builds, using 34 scripted model calls, 68 qualifications, 48 retrieval requests
and 16 target Docker executions. M7×M9, M8×M9 and M7×M8×M9 completed 32 targets
and scores after six builds, using 70 scripted model calls, 76 qualifications,
64 auxiliary and 32 solver Docker executions. Original state/mechanism M9 grids,
source-cost replay regressions, cross-family scorer routing and label isolation
passed in the same root checkpoint.

Accumulated engineering coverage is 36/36 requested pair controllers and all
five required triple controllers. Dependency-constrained and structurally
unavailable arms remain explicit; this does not identify every factorial effect
or represent a fresh rerun of all historical cases. No actual model generation
or validation access occurred. Source checkpoints, original failures and native
synthetic observations remain separately indexed.

Full/LOO composition is undergoing its own implementation and checks. P0/real
calibration, all real TRAIN effects, the final TRAIN-selected bundle and sealed
validation acceptance remain unfinished. The Grok material-authoring attempt
stopped before any model prompt at CLI initialization; no actual material or
calibration success is inferred from the engineering closures.

## Included-subscription diagnostic bridge checkpoint (2026-09-14)

The separately versioned Grok4.6 native diagnostic bridge preserves all36
material slots,72 evaluator opportunities and the maximum180 review/arbitration/
evaluation main calls. Possible initial title calls are separate; known main
usage does not establish title totals or final settlement. Complete private
references, original native receipts and request/reservation/source bindings
are checked before review signing. Unknown main usage stops later calls.

Root source `2533276` passed20 focused checks with560 source hashes unchanged.
This repaired all3 failures in the preceding37-test checkpoint; coverage of
all37 cases is accumulated across the two checkpoints, not a fresh final37 run.
The initial11-failure checkpoint is also retained. Root repairs changed only
synthetic peer import environments, process-tree ownership and fixture time
bounds; the actual native60-second limit and acceptance rules did not change.
The old timed-out pilot retains132/144 closed calls and60/72 closed evaluation
opportunities. Its repaired integration run completes the original full scope.

Evidence is in `results/modular-engineering-20260913/grok-subscription-bridge-root/`.
This checkpoint made no actual generation calls and prepared no actual materials.
Private provisional material authoring is a separate pending4-main/4-possible-title
phase. Real calibration, TRAIN effects, remaining combinations, full/LOO and
independent validation acceptance remain unfinished; validation stays sealed.

## Current mechanism/improvement and triple integration checkpoint (2026-09-14)

Source `8f9b16c` passed 50 root integration checks, with all 556 frozen
source/document hashes unchanged. M4×M9, M5×M9 and M6×M9 now freeze six
actual history-only candidate builds and twelve arm bindings before 24
targets. The complete grid used 78 scripted model calls, 76 qualifications,
24 retrieval operations, 24 actual target Docker executions and 24 process
scores. Other target factors share the exact candidate at a fixed M9 level.
The two original RED closures remain archived, including the reproduced
early-registration score-input bypass and its original-response-order repair.

M1×M4×M7 also has a complete 16-cell prospective controller. Its root grid
used 48 scripted model calls, 32 admission qualifications, 48 actual Docker
executions and 16 process scores. Seven descriptive components use frozen
main/pair/triple coefficients. Each benchmark has one independent group;
confidence limits are null, and qualification drift makes contrasts inconclusive.
Predictions freeze before fresh auxiliary measurements; state, proposal and
phase outputs actually enter the common solver. Useful off controls remain.

Root checked merged scorer-family isolation, exact candidate provenance,
original response ordering, coherent Docker attacks, component normalization
and label isolation. The two source archives contain 25 and 11 committed
files, with all 11,686 and 1,483 ZIP members verified. Root evidence is under
`results/modular-engineering-20260913/mechanism-improvement-triple147-root/`.
Engineering coverage is 34/36 pair controllers and 3/5 required triples.
No actual generation or validation access occurred in this checkpoint.
Real TRAIN effects, calibration, remaining combinations, full/LOO, the final
TRAIN-selected bundle and independent validation acceptance remain unfinished.

## Prior mechanism/scheduling integration checkpoint (2026-09-13)

Source `e61dadd` passed 46 root checks with all 542 frozen source/document
hashes unchanged. M4×M8, M5×M8 and M6×M8 now have prospective TRAIN
controllers with actual FIFO scheduling. The complete 24-cell grid used 72
scripted model calls, 48 source qualifications, 24 retrieval calls, 72 actual
Docker executions and 24 independent process scores. M7 is absent; both M8
levels select the same two useful literal jobs and two cost units.

Five focused real Docker variants verified container-internal overlap,
dependency/resource serialization, reversed completion with FIFO public
results and timeout cleanup. Four successful variants received independent
scores; the timeout retained its failure without scoring. Persistent queue,
snapshot, lease, reservation and barrier attacks, exact scorer-family scopes,
the legacy prediction scorer and label isolation passed root verification.
These checks establish scheduling behavior, not throughput gains on a busy host.

The isolated source passed 114 checks. Its 11-file archive has 10 indexed
artifacts and 2,124 verified ZIP members, including all original synthetic
failure/unknown/unused rows. Root source review and closure are under
`results/modular-engineering-20260913/mechanism-scheduling-root/`.
Coverage is now 31/36 pair controllers and 2/5 triple controllers. No actual
generation or validation access occurred in this checkpoint. Real TRAIN
effects, calibration, remaining combinations, the frozen final bundle and
validation acceptance remain unfinished.

## Prior mechanism/exploration and Grok integration checkpoint (2026-09-13)

Source `20a1c29` passed 81 root checks with all 537 frozen source/document
hashes unchanged. M4×M7, M5×M7 and M6×M7 now have prospective TRAIN
controllers. All 24 paired cells freeze before execution. Actual prediction,
review or retrieval output freezes before the auxiliary phase, and both
mechanism and phase outputs reach one shared solver. The complete grid used
72 scripted model calls, 48 source qualifications, 24 retrieval calls,
72 actual Docker executions and 24 independent process scores.

Original-input and repaired-chain replay, solver Docker limits, mutually
exclusive scorer families, the history-built M9 panel and native ACP protocol
fixtures passed root integration. The isolated mechanism source passed 101
checks; its first collection-error closure remains preserved. Source accounting
bounds opportunities and retains unknown realized external costs; it does not
certify actual source expenditure. Source evidence contains 15 files, 14
indexed artifacts and 1,937 verified ZIP members.

Native Grok 4.6 is now integrated as a separate transport. Its third constant
smoke was accepted before integration: the main ledger reports 2,301 tokens
and $0.00116892 service cost. Title usage, all-opportunity totals and settlement
remain unknown. Same-session empty tool inventories and fresh before/after
included-only account snapshots passed. The first two rejected attempts and
all five original check closures remain in the 48-file, 46-payload archive.
No real generation was repeated by the root check. The native transport is
not yet wired to the actual diagnostic or benchmark controllers.

Root evidence is under
`results/modular-engineering-20260913/mechanism-exploration-grok-root/`.
Coverage is now 28/36 pair controllers and 2/5 triple controllers. These are
engineering checks; real TRAIN effect experiments, calibration, remaining
combinations, the final frozen bundle and validation acceptance remain open.

## Prior state/improvement integration checkpoint (2026-09-13)

Source `103ab6d` passed 27 root integration checks with all 526 frozen
source/document hashes unchanged. M1×M9, M2×M9 and M3×M9 now have explicit
history-trained candidate barriers and independent target scorer processes.
All 11 history builds freeze before 22 legal targets; the two M2-off/M9-on
structural exclusions remain in the denominator. The target provider ledger
seals before any scoring. History and target tasks are distinct; independent
data-family transfer has not been established.

The full synthetic fixture used 55 scripted model calls, 66 source
qualifications, 11 actual candidate builders, 22 target Docker executions and
22 independent process scores. Its inherited history adds two scripted calls
and one Docker execution, reported separately. M9-off executes a useful fixed
builder under the same reserved proposal/build allocation.

A concrete barrier-proxy bypass missed in the initial source review was
reproduced, repaired and checked again. Exact barrier, plan, build and ledger
types now precede replay. Rehashed order and Docker-limit attacks and merged
scorer family exclusivity passed the root check. The source archive preserves
all eight original closures, including failures; its 95 distinct accumulated
checks are not a fresh 95-check final-source run. Evidence and both reviews are
under `results/modular-engineering-20260913/state-improvement-root/`.

Coverage is now 25/36 pair controllers and 2/5 triple controllers. Real TRAIN
effect experiments, calibration, remaining combinations, the final frozen
bundle and validation acceptance remain unfinished. No actual model generation
or validation access occurred in this checkpoint.

## Prior state/scheduling integration checkpoint (2026-09-13)

Source `ed4098c` passed 34 root integration checks with all 517 frozen
source/document files unchanged. M1×M8, M2×M8 and M3×M8 now have complete
prospective TRAIN controllers and independent primary scorer processes. The
24-cell grid used 48 scripted model calls, 48 source qualifications, 72 actual
Docker executions and 24 independent scores. M3 fixes M2 as background.

M7 is disabled. Both scheduler levels execute the same two literal jobs and
cost units. M8-on uses actual FIFO leases, immutable snapshots and the complete
merge barrier; M8-off runs serially. Actual container timestamps establish
overlap in the focused independent-job fixture. Dependency/resource conflicts
serialize, reversed completion retains FIFO output order, and timeout cleanup
is verified. These fixtures do not estimate scientific workload throughput.

The isolated source passed 102 checks. All original failure, unknown and unused
opportunities remain recorded, and M1 qualification drift blocks its contrast.
Root review found no concrete blocking source defect. The source archive has
16 files, 15 indexed artifacts and 4,315 verified ZIP members. Root closure and
source review are under
`results/modular-engineering-20260913/state-scheduling-root/`.

Coverage is now 22/36 pair controllers and 2/5 triple controllers. These are
engineering checks with synthetic model/source/scorer responses. Actual TRAIN
effects, calibration, remaining combinations, the frozen final bundle and
validation acceptance remain unfinished. This checkpoint used no actual model
generation or validation access; Grok transport probes are recorded separately.

## Prior state/exploration integration checkpoint (2026-09-13)

Source `694d126` passed 40 root integration checks with all 512 frozen
source/document files unchanged. M1×M7, M2×M7 and M3×M7 now have complete
prospective TRAIN controllers and independent primary scorer processes.
The full 24-cell grid used 48 scripted model calls, 48 source qualifications,
72 actual Docker executions (48 auxiliary jobs and 24 solver executions),
and 24 independent scores. M3 keeps M2 as fixed background.

The actual M7 permit and resource budget select a restricted range probe;
the useful ordinary arm runs dispersion analysis. Both consume the same two
literal jobs/cost units under serial FIFO; M8 is not enabled here. Actual job
outputs and reconstructed state reach the same solver. Replay binds source
qualification, permit/selection, state/phase journals, complete bounded Docker
argv, model requests, literal programs and scoring. Repaired-chain attacks
pass the generic trace checker and are then rejected by family replay.

The isolated source passed 88 checks. Source/phase/scorer failures, unknown
model usage and M1 qualification drift retain all planned rows. Root source
review found no concrete blocking defect, with selected-cell adversarial
coverage and synthetic solver/scorer limitations recorded. The 14-file source
archive has 13 indexed artifacts and 3,072 verified ZIP members. Root closure
and source review are under
`results/modular-engineering-20260913/state-exploration-root/`.

Coverage is now 19/36 pair controllers and 2/5 triple controllers. These are
engineering checks. Actual TRAIN effects, calibration, other combinations,
the final frozen bundle and validation acceptance remain unfinished. No actual
model generation or validation access occurred in this checkpoint.
Grok transport/accounting work is recorded separately in
[the transport contract](GROK-CLI-TRANSPORT.md).

## Prior state/retrieval integration checkpoint (2026-09-13)

Source `a98f580` passed 50 root checks with all 504 frozen source/document files
unchanged. M1×M6, M2×M6 and M3×M6 now have complete prospective TRAIN
controllers and explicit independent process scoring. The complete 24-cell
grid used 48 scripted model calls, 96 separately bound state/corpus
qualification calls, 72 retrieval calls, 24 actual Docker executions and
24 independent scores. M3 retains M2 as fixed background. Both M6 levels
retrieve useful material with the same three reserved opportunities; M6-on
changes the actual query intents to support, counterevidence and methods.

The root checks retain all 24 scores under M1 qualification drift but block
its contrast, preserve all planned rows under source/provider failures, and
stop a poisoned model ledger without retry. Persistent replay and score
issuance reject modified state, retrieval, program and request bindings.
The isolated source passed 78 checks; independent read-only review found no
concrete blocking defect. Mutation coverage selects BLADE arm 11, and separate
state/corpus request bindings do not require four globally distinct authority
keys. Scripted retrieval, solver responses and fixed synthetic scores establish
engineering behavior only.

The source archive has 26 files, 25 indexed artifacts and 1,766 ZIP members,
verified against committed Git bytes. Root closure and independent review are
under `results/modular-engineering-20260913/state-retrieval-root/`. Original
failed driver attempts remain preserved in the source archive.

Coverage is now 16/36 pair controllers and 2/5 triple controllers. Actual TRAIN
effects, calibration, the remaining combinations, the final frozen bundle and
validation acceptance remain unfinished. This checkpoint used no actual model
generation and did not open validation. The separate Grok transport smoke is
recorded separately and is not part of these synthetic test counts.

## Prior state/prediction integration checkpoint (2026-09-13)

Source `9b18e47` passed 32 root integration checks with 498 unchanged frozen
source/document files. M1×M4, M2×M4 and M3×M4 now have complete prospective
TRAIN controllers and independent process scoring. The 24-cell grid uses
72 scripted model calls, 48 source calls, 24 actual Docker executions and
24 process scores. M3 keeps its registered M2 background; both M4 levels
supply their original useful proposal to the solver, and M4-on additionally
uses the actual persistent prediction registry.

The isolated source passed 45 checks, including source and model failures,
M1 qualification drift and eleven rehashed replay attacks. The root run also
checked the shared v3 admission qualification guard and legacy admission
process behavior. Independent source review found no concrete blocking defect;
its limits are recorded: mutation cases select BLADE arms 00/01, and later
model/Docker failure paths lack specific coverage in this controller family.

The original archive has 245 files (244 indexed), verified against committed
Git bytes. The nine-file root checkpoint is under
`results/modular-engineering-20260913/state-prediction-root/`; it includes the
source review, before/after hashes, JUnit and archive verification. The prior
lineage-useful archive has 18 total files and 17 indexed entries, correcting
the earlier audit's wording without changing its original evidence.

Coverage is now 13/36 pair controllers and 2/5 triple controllers. Scripted
responses and fixed synthetic scores establish execution/replay/scoring wiring,
not scientific gains. The remaining combinations, actual TRAIN effects,
calibration, final frozen bundle and validation acceptance remain unfinished.
No actual generation or validation access occurred in this checkpoint.

## Prior lineage review and qualification parity checkpoint (2026-09-13)

Source `33296e4` passed 25 integrated checks with all 490 frozen source/document
hashes unchanged. The seven lineage/admission panels now have an explicit v3
primary-TRAIN recipe that retains both actual review outputs in every solver
arm. M5-off uses sequential revision; M5-on uses the actual sealed review barrier.
The original v1/v2 recipes and historical results remain separate.

The closed grid includes 58 new-recipe cells, 24 drifting-qualification cells
and 24 legacy admission cells: 106 actual bounded Docker executions and
independent process scores, with 424 synthetic model calls. The normal v3
admission grid retained three estimated contrasts and six semantically uniform
task/pair groups. In the drift grid, every cell remained scored, but all three
contrasts became inconclusive because the consumed qualification state differed
across arms. The two structurally incomplete lineage contrasts remain
`not_identifiable`. See [useful review controls](LINEAGE-USEFUL-CONTROLS.md) and
[qualification parity](V3-ADMISSION-QUALIFICATION-PARITY.md).

The root archive contains 12 files and 3,615 verified ZIP members under
`results/modular-engineering-20260913/lineage-parity-root/`. Its earlier archive
contains 18 files and 5,437 members verified against actual and Git
bytes. An initial audit used the wrong directory and a mistyped count; both
that report and its correction are retained. Unlocated earlier parity test
reports are not counted as proof; this source's original before/after and
JUnit reports establish the current checkpoint.

These are synthetic functional checks, not efficacy or throughput estimates.
No actual model generation or validation access occurred in this checkpoint.
Coverage remains 10/36 pairs and 2/5 triples pending complete verification of
the new state/prediction and state/retrieval families. Real TRAIN effects,
calibration, the remaining combinations and frozen validation remain open.

The current deployment constraint permits no additional API fees. Grok CLI
`grok 4.6` is authorized as a runtime candidate; its actual invocation and
capacity/usage contract still need verification. The historical HTTP pricing
contract is not satisfied by treating subscription quota as a zero USD tariff.

## Prior useful-output control checkpoint (2026-09-13)

Source `c846ea8` passed 25 integrated checks with 486 unchanged frozen
source/document files. The explicit M4/M5 v3 primary-TRAIN configuration now
retains the proposal and both reviews in every solver arm. M4-off uses ordinary
three-branch reasoning; M5-off uses sequential revision. M4-on still registers
discriminating predictions; M5-on still exercises the actual sealed barrier.
The recipe is frozen into each scenario and signed panel/score binding. Legacy
v1/v2 runs keep their original behavior and cannot be silently pooled with this
new estimand. See [the recipe and evidence](M4-M5-USEFUL-CONTROLS.md).

The isolated final source passed 26 checks; the earlier 67-check run retained
one incorrect test expectation about a poisoned provider ledger. The corrected
test preserves one failed plus seven blocked cells, with no retry. Eight-cell
success, 18 rehashed input/joint forgeries and a separate eight-cell runtime
review failure grid are preserved. Archive: 21 files and 1,336 ZIP members,
independently compared against Git bytes. Root closure evidence is under
`results/modular-engineering-20260913/m4-m5-useful-controls-root/`.

These are synthetic engineering checks, with zero new actual paid calls and
validation unopened. Coverage remains 10/36 pairs and 2/5 triples. The same
off-review omission exists in the lineage/admission family and is being handled
as another explicit recipe. Real TRAIN effects, calibration, remaining
combinations and validation acceptance are still unfinished.

## Prior common primary TRAIN source checkpoint (2026-09-13)

Source `64798f4` passed 44 integrated checks with 466 unchanged frozen
source/document hashes. Admission and M7×M8 now accept explicit v2 primary
TRAIN tokens; Q3.2 has a separate typed prospective-source entry sharing its
unchanged execution kernel. The new source grids executed 24 admission cells,
eight M7×M8 cells and four Q3.2 cells with 12 measurements. Original legacy
entries and budgets remain available. Source faults are rejected before model,
qualification, Docker or scorer dispatch, while completed export audit records
are retained. The first scheduler source run kept all eight failed cells after
an old benchmark/task lookup remained in execution; complete-identity binding
fixed it before the 54-check isolated run and this root integration.

Pair/triple coverage remains 10/36 and 2/5; this is a data-port extension, not
new combination efficacy evidence. Validation remains sealed and no new actual
paid model call was issued. Scientific measurement, real model calibration,
TRAIN effect studies and final validation remain open. Evidence:
`results/modular-engineering-20260913/remaining-prospective-sources/` and
`results/modular-engineering-20260913/remaining-prospective-source-root/`.

## Prior admission, execution and private transport checkpoint (2026-09-13)

Source `a70482a` passed 81 integrated checks with no failures, errors or skips;
all 463 frozen source/document hashes remained unchanged. The preceding
prospective-source integration passed 123 checks with 451 unchanged files.

Ten of 36 pair controllers and two of five triple controllers are now wired.
M1 contributes three panels totalling 24 cells; M7×M8 adds an eight-cell actual
Docker and independent-primary-scoring grid. Q3.2 also has an explicit four-cell
prospective execution phase, while its original planning-only ablation remains.
The three existing combination families support an audited primary TRAIN
exporter through explicit v2 configuration; admission v1 remains closed.

The four-TRAIN diagnostic pilot and private HTTP worker execute with synthetic
references, blinded requests and retained usage/failure evidence. Real model
calibration, scientific measurement qualification, actual TRAIN effects and
validation acceptance are still incomplete. Twenty-six pairs, three triples,
full/leave-one-out and the final TRAIN-selected bundle remain required. No new
actual paid model call or validation export occurred in this checkpoint.

See [checkpoint and limits](MODULAR-CHECKPOINT-20260913-ADMISSION-PROSPECTIVE-EXECUTION.md).
Three agents stopped on account usage limits; root finished their local checks,
repairs and integration. No successful fixture result is promoted to efficacy.

## Historical reference, combination and linked training checkpoint (2026-09-13)

Source `d168781` passed 104 integrated checks with zero failures, errors or skips;
all 441 frozen source/document hashes remained unchanged. The 43 registered
drivers and five separate Q6 phases still cover all 48 engineering execution
contracts. Generic benchmark linking now supports Q1.1–Q1.5, Q3.1, Q3.2, Q4.3,
Q5.3, Q8.2 and Q8.3. Q3.2 remains planning-only: downstream solving does not
execute its three proposed experiments or acquire independent observations.

Six of 36 pair controllers and two of five triple controllers are wired. The new
M4×M6, M5×M6 and M4×M5×M6 panels executed 32 synthetic cells with independent
primary scorer processes. Q1.1–Q1.4 linking executed 58 synthetic cells. Review
also repaired prediction freeze chronology and Q8.2/Q8.3 public metadata leakage;
the original failures and earlier limited GREEN reports remain archived.

The four fixed primary TRAIN tasks now have independently prepared references.
Root verified identities, hashes, all eight audit events and unchanged protected
inputs without parsing reference bodies. No new actual paid call or validation
call was made. The primary 95 validation items stay sealed and SAB's 18 stay on
hold; BLADE still has only one validation family.

The archive now contains 1,981 indexed files, preserving all previous 1,680, with
nine synthetic ZIPs containing 2,630 individually hashed members. Thirty pairs,
three triples, full/LOO, the final train-selected bundle, scorer calibration,
actual mechanism effects and validation acceptance remain open. No singleton
result prunes combinations. See [the checkpoint](MODULAR-CHECKPOINT-20260913-REFERENCE-COMBINATIONS-LINKED.md).

## Previous all-question execution and training export checkpoint (2026-09-13)

Source `b9f7ff4` passed 121 integrated checks with no failures or skips. There are
now 43 registered question drivers and five separate Q6 training phases, covering
all 48 engineering execution contracts. Generic mechanism-to-benchmark solving
currently supports Q1.5, Q3.1, Q4.3, Q8.2 and Q8.3; the other questions still need
their complete benchmark/scoring paths and effects measured. The separate Q6.3
metaprogram phase remains a distinct obligation.

The final Q8.5/Q8.6/Q8.7 delivery exercised 92 synthetic cells, including actual
post-pause I/O rejection. Retrieval-linked Q8.2/Q8.3 exercised 24 synthetic cells
with 24 Docker executions and independent fixture primary scores. Review found
variant labels in an earlier fixture's source IDs; the original run is retained
as review-limited, and neutral IDs plus actual precursor/solver request checks
passed the corrected frozen run. These results do not establish scientific effect.

The primary prospective exporter actually published four fixed training tasks,
two from each primary benchmark. Root independently verified 26 artifact hashes,
24 input pins, four protected files, the deterministic original-train selection,
and the seven-event exposure chain. No validation or reference payload was parsed
by that root check. All 95 primary validation items remain sealed; all 18 SAB
validation items remain on hold. BLADE still has only one validation family.

The evidence archive has 1,680 indexed files, retaining all previous 1,595. The
remaining 32 pair controllers, four triple controllers, full/LOO, final
train-selected bundle, calibration and validation acceptance remain open. No
singleton result has pruned a combination. See [the checkpoint](MODULAR-CHECKPOINT-20260913-ALL48-EXPORT-LINKED.md).

## Previous primary partition and lineage checkpoint (2026-09-13)

Source `73a6c2d` passed 201 integrated checks covering the new primary seal,
prospective exporter, custody, shared M2/M3 behavior and combination controllers.
The primary observed-family split has 308 train and 95 sealed validation items:
Discovery 294/94 and BLADE 14/1. Root recomputed the frozen allocation and checked
all 24 declared input pins and retention of the old 81 train items. This is a
bounded history/relationship qualification; BLADE's sole validation group cannot
satisfy the protocol's multiple disjoint stage shards. All SAB 18 remain on hold.

Four lineage panels now execute 34 synthetic controller cells. M2×M5 and M3×M5
with fixed M2 background have complete factor grids; M2×M3 and M2×M3×M5 retain
their structural missing cells and unidentifiable interactions. The earlier
M4×M5 panel remains separately source-qualified. Thus four of 36 pair controllers
and one of five triple controllers are wired; the other 32 pairs, four triples,
full/LOO and final train-selected bundle still require execution. No null result
has pruned any combination. A real lineage scorer process is in a separate
delivery; current synthetic scores do not measure scientific effects.

The registry still contains 40 question drivers plus five separate Q6 phases;
the final three drivers await source integration. The evidence archive now has
1,595 indexed files, preserving all previous 1,524. It includes the closed 1,078
file lineage grid, original failures and a recorded archive-path repair. See
[the checkpoint](MODULAR-CHECKPOINT-20260913-PRIMARY-LINEAGE.md).

## Previous train export and retrieval checkpoint (2026-09-13)

The integrated registry has 40 question drivers plus the five separate Q6 train
phases, covering 45 engineering execution contracts. Q8.5/Q8.6/Q8.7 are undergoing
their separate frozen delivery. All 48 scientific questions, calibration, actual
validation acceptance and outstanding combination effects remain open.

The fixed four-task train export succeeded (two SciCode and two SAB) after the
original pre-materialization failure was retained. Root verified the sealed
selection, artifact hashes, ten-event audit chain and unchanged input pins without
parsing task bodies. The integrated exporter checks passed 75 tests on `2074352`;
the merged Q8.1/Q8.4 controller checks passed 105 on `8aff4f1`. These are engineering
results; Q8.4's complete factorial retains an estimable, expected-null contrast.

All 18 SAB validation records are now on an eligibility hold: an earlier manifest
selected 12 identities, with three observed successful calls and 75,272 historical
tokens, but its relation to the sealed revision is unresolved. The original
164/18 allocation is unchanged; no validation lease is allowed. A separately
delivered primary 308/95 metadata partition awaits root source integration and
review; it does not relax this hold or establish absolute independence.

The archive contains 1,524 indexed files, preserving the earlier 1,459. A publisher
path error was repaired by verifying and retaining all 49 partial copies before
adding the remaining files; the original script and recovery receipt are retained.
See [the checkpoint](MODULAR-CHECKPOINT-20260913-TRAIN-EXPORT-RETRIEVAL.md).

## Previous Q6, retrieval and source checkpoint (2026-09-13)

The production registry has 38 question drivers. Q6.1, Q6.2, Q6.3, Q6.5 and
Q6.6 use separate train phases; Q6.4 remains a registered driver. Together these
cover 43 question execution contracts. Q8.1, Q8.4, Q8.5, Q8.6 and Q8.7 still
require production drivers. This is engineering coverage, not completed science.

Q6's integrated checks passed 53 tests on `9ca3214`; the later merged retrieval,
custody, failure-verification and controller regression passed 222 on `39cfac6`.
Q8.2/Q8.3's frozen agent delivery contains 24 actual synthetic controller cells
and 89 passing tests. The archive now contains 1,459 indexed files; all earlier
1,396 entries retain their bytes and hashes. A separate read-only replay verifies
all eight original M4/M5 records with all 302 original files unchanged. Its
five scores, three failures and inconclusive result remain unchanged.

The separately scoped extended partition is sealed at 164 train and 18 validation
records. Its train exporter is under repair after the first fixed four-item
public projection was rejected without materializing output. Primary benchmark
validation remains a separate process/lineage audit obligation. Q6.6's train
staging/rollback checks do not establish production acceptance. All scientific
questions, calibration and required combination effects remain open.
See [the checkpoint](MODULAR-CHECKPOINT-20260913-Q6-SOURCE-REPLAY.md).

## Previous combination and exploration checkpoint (2026-09-13)

The production registry has 36 question drivers plus the separate Q6.3 train
phase. Extended exploration passed 69 root checks including its full 88-cell
controller grid; Q5.5's formal 32-cell controller is integrated. The archive
contains 1,396 indexed files with the earlier 1,194 entries preserved.

The first complete M4/M5 training factorial is closed: eight cells, five scores,
three failures, 45 provider calls and 476,790 tokens. Its frozen result is
inconclusive. An execution-failure verifier repair remains under independent
review; the original failure denominator and all paid-run files are unchanged.
No validation or scientific acceptance is claimed. The separate prospective
extended-data split and remaining Q6/M6 controllers are under root review.
See [the current checkpoint](MODULAR-CHECKPOINT-20260913-COMBINATION-EXPLORATION.md).

## Previous scoring recovery and resource checkpoint (2026-09-13)

The production registry has 31 question drivers. Q5.4's actual custody/export/
controller/diagnostic/authority path passed 97 root checks on `f41982d`. Shared
public execution helpers passed 68 checks on `07bdc04`. Explicit UTF-8 scorer
stdio repaired a reproduced GBK decoding failure (18 checks); read-only completed
cell recovery passed 21 checks on `7441cfd`.

The closed Q3.1 repeat and its separate scorer-only recovery used 59 provider
calls and 686,713 tokens. Eleven of 12 cells executed and received adapted scores;
one generated-program failure remains in the denominator. No solver call was
repeated during recovery. The frozen selection is inconclusive, with no selected
package, deployment or combination pruning. The archive has 1,194 indexed files,
preserving all earlier 999 bytes/hash entries. No scientific efficacy, scorer
calibration or validation acceptance is established. Q5.5, extended exploration
controller wiring, the separate Q6.3 phase and remaining M6/M9 implementations
still need work; all 48 scientific questions and all combinations remain open.
See [the checkpoint](MODULAR-CHECKPOINT-20260913-SCORING-RECOVERY.md).

## Previous protocol and exploration checkpoint (2026-09-13)

The production registry has 30 question drivers. Q2.7 now binds the actual P0
control, completed source trace and independently verified read-only replay.
Two stale fixture classifications were repaired after retaining the original
failed reports; their complete files passed 55 root checks on `744387a`.
Q7.1/Q7.2 now pass through the actual custody exporter and production controller,
with 91 root checks passing on `d4d393d`, including the complete 52-cell synthetic
Docker/audit grid. These are engineering results, not benchmark effect estimates.

The archive contains 999 indexed files, including all 52 frozen agent exploration
traces; all earlier 924 files are unchanged. A separate 12-cell Q3.1 training
repeat is running on `a8449fa`, with only immutable controls archived so far.
Its failures, usage and terminal result will be reported after completion.
No validation lease or scientific acceptance is claimed. Q5.4/Q5.5 and M6
remain under causal repair; all remaining questions, the separate meta-program
stage and every required combination remain open. See
[the checkpoint](MODULAR-CHECKPOINT-20260913-PROTOCOL-EXPLORATION.md).

## Previous feasibility and lineage checkpoint (2026-09-13)

The production registry has 27 question drivers. Q5.1/Q5.2 now pass through
the actual typed compiler, train custody exporter, model port and Docker, with
source-bound stage verification. The 36-cell synthetic grid is covered by 186
root checks on `be65ef5`. Prospective assessments precede execution. This is
engineering evidence; no benchmark scientific efficacy is established.

The complete suite on frozen `286f5b1` passed 1,143 tests with zero failures,
errors or skips. That source predates feasibility and canonical lineage; their
later focused checks are source-qualified separately. A metadata-only audit of
605 records gives 202 conservative grouping constraints, with zero records
qualified for independent validation. Static parsing of 40 fixed preparation
slots yielded no references under its predeclared API rules.

All 924 indexed archive files have exact byte hashes; the earlier 899 are
preserved. Q2.7 controller wiring remains under review. Q5.4/Q5.5 and M6 drafts
have substantive causal defects and are not credited as completed production
drivers. All 48 scientific obligations and all required combinations remain
open; no null singleton has pruned a combination. See
[the checkpoint](MODULAR-CHECKPOINT-20260913-FEASIBILITY-LINEAGE.md).

## Previous semantic, custody and combination checkpoint (2026-09-13)

The production registry has 25 drivers, including Q2.2/Q6.4 through the actual
fixed-P0 compiler and train controller. Their root suite passed 109 checks on
`0b146a4`. The M4+M5 four-arm controller now connects custody, actual Docker,
separate signed adapted scoring and contrast; synthetic checks establish the
interface behavior, not benchmark scientific gain. AIRS contributes 20 newly
received records, with zero validation-eligible records. The undeclared YAML
dependency and the older full suite's 7 failures are retained and repaired
under source-qualified targeted checks (67 root checks on `286f5b1`). The
archive contains 899 indexed files, preserving all earlier evidence. Current source has no new full-suite
pass or validation acceptance claim. See
[the checkpoint and evidence limits](MODULAR-CHECKPOINT-20260913-SEMANTIC-CUSTODY.md).

## Previous scheduler controller checkpoint (2026-09-13)

Source `ce2e81b` additionally connects Q3.3–Q3.5 through the production scenario
compiler, custody exporter, frozen train controller and Codex model port.
The registry now has 23 question drivers. The 36-cell synthetic M8 grid uses
both benchmark adapter shapes, caller-owned integer work and actual worker
threads/SQLite; it does not solve actual benchmark questions. All 212 focused
root checks passed in 319.951 seconds. The agent's source-qualified 100-test
suite and 152-test expanded suite overlap; they are not independent replications.

The baseline actually executes the same workload and publishes each return.
M8-on applies resource locks, invalidation, merge barriers, typed receipt
deduplication and confirmed-termination recovery. Costs include every started
attempt. Q3.3 throughput/fairness, Q3.4 unfinished scientific-context pollution,
OS process-crash durability and benchmark scientific quality remain unmeasured.
See [the driver contract](MODULAR-SCHEDULER-PANEL-DRIVERS.md).

The archive contains 876 byte-hash-indexed files, including closed reports and
the explicit notice excluding intermediate source-unfrozen runs from final
verification. Earlier reports are unchanged. No new paid call, validation lease,
scientific effect, combination pruning or deployment occurred. The separate
full suite on source `fd985fa` later finished with 989 checks and 7 failures;
its source predates these M8 changes. The newer checkpoint records the repair.

## Previous combination scoring checkpoint (2026-09-13)

Source `fd985fa` connects 20 production question drivers and the first actual
four-arm M4+M5 execution-to-signed-adapted-score-to-contrast path. Q3.2/Q5.3 are
planning-only; Q2.5/Q2.6 signed material is not session execution evidence.
Source-specific suites passed 63, 42, 131, 108 and 34 tests; the first prediction
semantic failure is retained. A new full suite runs on a separate frozen checkout.
No new paid call, scientific effect, candidate selection or validation acceptance
is claimed. The remaining question drivers and all required combinations stay in scope.

SciCode and ScienceAgentBench have conservative metadata grouping evidence but
remain unknown-exposure and unsplit. A recorded CORE-Bench diagnostic exposure
disqualifies that acquired source from an unseen validation claim in this context.
See [MODULAR-CHECKPOINT-20260913-COMBINED-SCORING.md](MODULAR-CHECKPOINT-20260913-COMBINED-SCORING.md)
for exact behavior, source bindings, failed checks and archived receipts.

## Previous terminal training checkpoint (2026-09-13)

The frozen `c3a4b21` linked train attempt is closed: 12 cells, 10 successful
restricted-Docker executions with independent adapted scores, and 2 retained
execution failures. There were 58 provider calls and 935,043 tokens. Selection
is `inconclusive`; dynamic controller metadata affected all 12 cells, so this
attempt is engineering wiring evidence and does not qualify a clean module
effect. No combination pruning, validation acceptance or deployment occurred.
The full 928-test result belongs only to `c3a4b21`. Subsequent focused suites
passed 26 (`a111e1c`), 61 (`718fc84`), 83 (`b59bb3e`) and 70 (`7aa349d`) tests.

Production drivers cover Q1.1–Q1.7, Q2.1/Q2.3/Q2.4, Q3.1 and Q4.1–Q4.5.
All 48 obligations, combinations and the separate Q6.3 phase remain required.
See [MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md](MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md)
for the terminal attempt, failure denominator, public-context repairs and
source-specific evidence. The archive now contains 852 hash-indexed files.

## Previous scorer checkpoint (2026-09-13)

Source `c3a4b21040e419692a74382c973104d5fe5cf7e1` adds production Q1.1–Q1.4 and
Q2.1 wiring, frozen train-reference extraction, a separate evaluator provider
contract and a real stdio scorer process. The current archive has 448 files,
including both failed planning-assertion reports and their 55-test repair.
The source is frozen in a separate worktree for a full regression and the first
12-cell linked training solve/adapted-score run; neither is claimed complete in
this checkpoint. See [MODULAR-CHECKPOINT-20260913-SCORER.md](MODULAR-CHECKPOINT-20260913-SCORER.md).

## Previous selection checkpoint (2026-09-13)

Source `bd302e7b91771514f1f327f5e0229b5d00baeae3` additionally integrates the
linked training controller, signed linked adapted scorer, train-only grouped
selection and Q4.1/Q4.2/Q4.4/Q4.5 material-bundle drivers. The controller/selection
seams passed 42 focused tests and Q4/compiler regressions passed 81. This batch
has no full-suite result, live effect estimate or validation result; Q4.5
heterogeneous routing remains unsupported and counted as failed observations.
There are 413 hash-indexed archive files. See
[MODULAR-CHECKPOINT-20260913-SELECTION.md](MODULAR-CHECKPOINT-20260913-SELECTION.md).

## Previous full-suite checkpoint (2026-09-13)

Source `cc640f79fe258bd27cd0d1d43ac1036f2d8957cf` passed the full 854-test suite
with zero failures/errors/skips (1438.961 seconds). Q1.5/Q3.1/Q4.3 production
mechanisms, Q3.1/Q4.3 linked benchmark solver, complete protocol terminal checks
and frozen rubric endpoint are integrated. No module efficacy, scorer
calibration or validation result is claimed. The archive now has 404 hashed
files, preserving the previous 395 files byte for byte.

See [MODULAR-CHECKPOINT-20260913-LINKED.md](MODULAR-CHECKPOINT-20260913-LINKED.md)
for the tested source and remaining obligations. Linked controller, adapted
train selection and additional Q drivers are the next integration batch.

## Earlier live training checkpoint (2026-09-13)

The tested source is `67b55b07464df9baa4666d4027f3ce376f8fcb2c`: 815 tests passed,
zero failures/errors/skips (690.571 seconds). The first complete scheduled real
Q3.1 training transport panel made 23 provider calls, used 208,955 tokens and
retained 11 successful runtime cells plus one rejected prediction plan. It is
`execution_incomplete`, with no benchmark-program execution, independent score,
scientific effect or validation result. The two new pinned sources were actually
acquired and imported as 182 unknown-exposure items in a separate unsplit store.
The original 403-item store is unchanged. Combination panels and grouped contrast
calculation now exist, but actual combined module intervention is not connected.

See [MODULAR-CHECKPOINT-20260913.md](MODULAR-CHECKPOINT-20260913.md) and
`results/modular-engineering-20260912/live-training-20260913/` for that checkpoint's evidence,
complete failure denominators and scope. The sections below preserve the earlier
2026-09-12 checkpoint and do not supersede the newer record.

## Earlier working state (2026-09-12)

- Integration checkout: `E:/_ryanDev/AI/research-loop-modular/integration`, branch
  `codex/modular-integration`, based on `dfaebe554d8bae0191ece2251a812682054a2169`.
- P0 and M1–M9 have initial implementations, independent worktree commits and
  component tests. Shared immutable contracts bind task/source/split identities.
- M2/M3 include claim dependencies, continuous revisions, withdrawal propagation,
  independent surviving roots and context rebuilding. M4–M8 have workflow hooks.
- Stage 9 now makes actual evidence-first/sealed/reveal review calls, with a
  matched summary-first control. Frontier audit makes a source-bound proposal
  call and rejects validation-to-training exports and programme completion.
- M9 includes a genuinely executed restricted meta-builder DSL, independent
  acceptance signatures and whole-package file deployment/rollback fixtures.
- `python -m research_loop.modular plan` emits all 48 Q obligations, 9 singleton
  or conditional designs, 36 pairs, 5 specified triples, full-bundle ablations
  and a pending train-selected final target. Illegal cells remain unscored.
- Original study protocols, results, production pause and historical worktrees
  are unchanged. The two original checkouts retain only their prior design edits.
- A full regression attempt beneath the source checkout correctly triggered the
  inherited `data/labels` ancestor guard. The runner root was moved outside the
  checkout; the guard was preserved. A subsequent missing-parent setup failure
  was repaired by creating the E-drive task work parent before retrying.

## Evidence boundaries

The combined Python suite passed 768 tests with no failures, errors or skips
on source commit `6ac59bad4fc7fb0215a6a80b3fa0b1fc9e1cc6d0` (397.321 seconds).
The earlier 308, 435 and 723-test checkpoints remain retained. The intervening
767-test run had one real Windows SQLite handle-cleanup failure; its report is
preserved alongside the scheduler lifecycle repair and 44 passing focused checks.
The final source hashes, all 48 coverage records, 826 compiled synthetic cells,
source metadata and raw test reports are archived under
`results/modular-engineering-20260912/expanded-sources-and-panels-01/`.
Current test commands and entrypoints
are in [MODULAR-RUNNING.md](MODULAR-RUNNING.md). Component test counts are not
scientific benchmark results.

Two synthetic tasks passed actual public-adapter → restricted Docker → dual
scientific-audit verifier → final gate wiring. Both adapter schemas were exercised;
these are synthetic integration observations, not DiscoveryBench/BLADE efficacy
measurements. The Docker checks also cover non-root execution, no networking,
read-only input/root, timeout cleanup and path/junction rejection.

Two actual previously exposed training packets (one per benchmark) were exported
using the custody allowlist and matching input hashes. The first real Luna model
call completed, but the port rejected additional CLI usage fields; its raw event
stream reports 15,980 input and 989 output tokens. It also warned that global
skill descriptions were present despite the requested configuration. This run
is a retained transport failure, not an accepted benchmark experiment. Read-only
reconciliation now recovers its output and all five usage fields, while keeping
the skill-context faults and original failure. Context isolation still needs
verification before the next experimental call.

All 48 obligations now have typed input builders and callable engineering
scenario drivers. The added drivers cover the exact registered Q3 recovery,
Q4 review, Q5 feasibility, Q6 improvement/scorer and Q8 retrieval variants;
Q1.1/Q2.1/Q2.3 no longer stop at input metadata. Q6.3 executes the restricted
meta-builder separately. These are fixture mechanisms, not 48 completed
benchmark experiments. Several drivers still need their full formal-panel
adapter, matched module-off control and provider/scorer integration.

The train-only panel compiler now constructs a complete frozen grid for every
registered obligation from prepared public tasks and actual package records.
P0-only Q2.2/Q2.7/Q6.4 use a single fixed control bound to source/protocol material;
P0 never has an off arm. The production per-cell entry point currently connects
Q3.1 through real runtime requests, M4 plan/control handling and final journals.
The compiled two-benchmark synthetic Q3.1 grid contains 12 cells. A separate full
grid fixture retains two failed cells (a rejected plan and a model exception),
and its verifier rejects tampered failure binding. Other formal per-cell drivers
remain explicitly unavailable at this entry point.

Q6.2's fixed arm now preserves the original package and invokes no optimizer or
proposal callback. Q6.5 executes two linked offline-shadow updates through one
authority. Its protected control rejects an authenticated but ineligible
synthetic calibration receipt before activation; a positive control proves the
same guard admits an eligible receipt. This checks the guard mechanism and does
not establish calibration of a real scientific scorer or a measured feedback effect.

ExperimentLedger now re-verifies a complete FrozenPanel, actual RunSession
journals and independently verified scorer receipts before measurement. Legacy
opaque hashes are insufficient. Candidate selection binds the training panel,
split, scorer, criteria and required benchmark set. Validation requires a
consumed custody-issued lease, eligible signed scorer calibration and an
independent decision; the final ledger decision must match it. Custody checks
each panel identity against its actual inventory and split before issuing a
panel receipt. These local checks still require separately deployed trusted
services and access restrictions; in-process signing fixtures do not establish
that deployment or substantive scientific calibration.

The retained Discovery training output was executed once as a separate Docker
diagnostic without new model calls. It observed a constant target across 500
rows and skipped regression. No scientific audit or score was issued; the
original failed pilot remains unchanged. Q2.4 also retains the authentic but
scientifically wrong agreeing-auditor fixture as a false-admission observation.
The original pilot's CLI cwd was inside the source checkout, so it also lacks
the required exported-workspace qualification. Future model runs must use a
fixed public work root outside all label-bearing source ancestors.

The subsequent BLADE training transport call completed with 7,085 input and
1,271 output tokens and no tool events. Its pre-call visible context matched a
reviewed frozen two-message base context. The controller nevertheless rejected
the CLI startup notice containing `skip_host_skill_discovery` as a skill-context
fault. This failed pilot is retained; it is not an efficacy observation. A
separate, zero-new-model-call diagnostic executed its program on the allowed
250-row BLADE fish input in restricted Docker. No scientific audit or score was
issued. Exact startup-notice classification has since been repaired and its two
prospective exceptions reviewed, without reinterpreting the failed ledger. Every
future model call still requires a fresh live match to its reviewed context. A
preceding root audit also caught a changed bundled
skill file; its failed audit and the subsequent stable render are preserved.

Review rejected preliminary Q7 code that relabelled validation identity as
train, and Q3/Q5 fixtures whose variant changes did not reach callbacks. The
integrated repairs preserve original provenance, retain actual callback outputs,
and exercise fixed execution allocation and evidence withdrawal. Q7's fixture
token budget is explicitly unexercised; four-execution ratio rounding is reported
alongside requested and effective percentages. No fixture result qualifies a
validation lease or turns successful execution into scientific evidence.

No new module or combination has completed its required paired training effect
study and independent validation. The live metadata inventory checked in this
continuation contains 403 items: 81 training items in 23 source groups, 322
quarantined items in 53 groups, no validation items and no leases. No task or
reference content was opened for this count. Repetitions or renamed tasks do
not create independent data.

The user authorized additional relevant datasets on 2026-09-12. The frozen
required benchmark set can now include ScienceAgentBench, SciCode, CORE-Bench
and AIRS-Bench while retaining DiscoveryBench and BLADE. Their source catalog
and metadata pins are in [MODULAR-EXTENDED-DATASETS.md](MODULAR-EXTENDED-DATASETS.md).
Catalog membership does not mean a runtime adapter, qualified split or scorer
exists. Shared datasets, papers and artifacts must be grouped before splitting.

All four new sources have retained pinned Git-tree metadata and repository
license artifacts with verified hashes. SciCode and ScienceAgentBench also have
restricted public-projection adapters and synthetic runtime-request integration
checks. CORE-Bench and AIRS-Bench remain catalog-only. No new source task payload
has been acquired, no validation groups have been assigned, and no scientific
score has been obtained from these four sources.

## Next required work

1. Complete the next bounded training transport contract with the repaired
   model port and freshly reviewed context; retain both earlier failed pilots.
2. Finish formal per-cell scenario adapters and substantive blind scorer
   calibration. Do not substitute synthetic signed counts for actual calibration.
3. Freeze matched schedules and conduct all required training-side module and
   combination experiments, including the separate meta-builder phase. A
   dedicated combination panel is still required: the Q-specific factor
   restriction cannot encode arbitrary pair/triple/full/LOO scopes. Its routing
   manifest must not be treated as an executed or scored contrast.
4. Acquire and qualify independent data under the expanded source scope, add
   restricted public adapters/scorers, verify deployment access isolation, then
   freeze validation panels and run acceptance. Never tune from validation.
5. Verify approved whole-package deployment and rollback on the intended host;
   report every Q/C obligation with evidence and unresolved limitations.
# 2026-09-14 C5 common TRAIN precommit

`joint_train_protocol.py` now freezes the union of C1/C2/C3/C4 legal factor
settings as new common-procedure recipes, retaining structural exclusions and
all 48 original issue/variant contracts. It fixes complete protocol/trial
identity, TRAIN-only source inputs, history/target group isolation, separately
versioned component templates, provider/scorer/rule and resource denominators.
B0 remains a separately reported unequal-budget reference. Original family
scores and candidate identities are not relabelled as common comparisons.

Frozen `b3cd0459a1c09360608eb78f6c0d7a36f4223456` passed 31/31 checks with all
625 source hashes unchanged; the preceding 461575a checkpoint also passed31.
The original-byte verifier and exclusive disk lock are exercised with synthetic
inputs, with no model/scorer/Docker calls. Exact sources and check originals are
archived under `results/modular-engineering-20260914/c5-common-train/`.

This closes the common comparison precommit boundary only. Actual common-grid
execution, complete component consumers, authenticated TRAIN selection, V_final
custody/calibration/acceptance and the independent deployment-grant issuer remain
required. All previous experimental obligations and separate Q6.3 remain open
until their own required evidence exists; no scientific efficacy follows here.
# 2026-09-14 M1–M6 artifact integration and independent review

The artifact worktree now connects M1–M6 writers and readers to the actual C4
stage. Context witnesses precede their matching requests; prediction/submission
records precede C4 freeze/seal claims; each reveal uses only already submitted
records. Disabled M4/M5 retain the ordinary control. Q8 events are registered
immediately after their own fsync, and Q8.4's separate source ledger binds the
complete PublicTask digest without becoming P0 scientific evidence.

Frozen `128fad63` passed 82 unit/contract checks and two actual Docker plus
synthetic-provider stage checks in separate runs. Independent review then
demonstrated coherent-hash order and Q8.4 task-binding gaps. Frozen `73b4e743`
repaired them and passed 46 focused checks including actual history→target
execution; the unchanged writer-failure case was not repeated. All three runs
retained 687 unchanged source files and used no paid API. These are engineering
checks, not module efficacy, scorer calibration or VAL acceptance.

Exact source ZIPs, reports, previous failures, five complete selected public
stage directories and review records are under
`results/modular-engineering-20260914/artifact-events-r2/` (179 files). Earlier
M3/M4/M5/M6 helper checks remain attached to their original versions and do not
inherit the repaired implementation's coverage. A separate real reader check
reopened four previously committed catalogues through frozen source archives
after live source changes; it verified historical byte integrity, not semantic
execution in the original environment. Two completed M3 checks had left unsafe
PID-only timeout watchers; root retired those exact watcher identities and
retained the cleanup record. Subsequent root watchers bind PID, creation time
and command and close when their owner exits.

This work is in `codex/artifact-evidence-provenance`. Main integration remains
frozen at `98eae28` while the complete C5 r3 engineering run is active. M7/M8/M9
per-output stage wiring, other module entry points, cross-catalogue relationships,
resource attribution and audit overhead remain required. All original 48
questions and singleton/pair/triple/full/LOO studies remain in scope.

# 2026-09-14 C4 M1–M9 per-output acceptance and remaining host inventory

The C4/C5 common stage now writes and verifies the M7/M8 allocation, each
program/return, every scheduler event, SQLite state and phase receipt. History
builds record M9 selection, TRAIN subjects, DSL, original typed returns,
individual candidate/receipt files and terminal state. Disabled modules retain
ordinary-control outputs with `not_applied`; no parallel SQLite is invented.

Frozen `64d42d1` passed 39 integrated checks (693 unchanged source files).
Independent review then identified a success/failure mismatch: a coherently
sealed failed M9 terminal was accepted by a successful outer history stage.
The actual stage regression at `eb7d9e4` reproduced this failure in 130.813s;
the result is retained. `348017a` now requires verified builder success, and
passed both full and ordinary-control history→target checks in 342.672s.
Those checks retained 693 unchanged source files, used actual Docker with
synthetic model peers and incurred no paid provider calls. The 39/1/2 counts
refer to distinct versions and overlapping tests, not 42 unique passing cases.

`results/modular-engineering-20260914/artifact-events-r3/` preserves 438 files:
eight check batches with exact source ZIPs, ten complete public stage folders,
978 descriptor records, failure evidence and the source-only caller inventory.
The descriptors span multiple executions, not 978 unique scientific artifacts.
Earlier helper checks remain evidence for their own source versions only.
M9 recorded cost units describe fixed builder search/attempt allocation;
they do not establish total machine usage or a paid-API settlement.

The caller inventory finds eight actual `run_phase` callers, of which C4 is the
one connected caller; seven other hosts need their actual input/selection
contracts, without inventing C4 model/retrieval parents. Three independent
restricted-builder host families also need adapters. The complete inventory
contains 128 named call sites in 49 modular source files, including replay-only
constructors. P0 custody artifacts, other host writers/readers, cross-catalogue
TRAIN configuration edges, generic resource attribution and audit overhead
remain open. This is not a claim of universal module output coverage.

A separate one-shot Grok 1.0.30 authless initialize probe timed out after 60.171s
with no stdout/stderr, no response and no model/session/authentication/billing
RPC. Four synthetic helper checks passed first; the owned Job and retained
handle closed, and no new auth path appeared. It shows the stall can occur
without supplied cached credentials, not its root cause or model readiness.
Twenty public source/receipt files are archived at
`results/modular-engineering-20260914/grok130-authless-initialize-r1/`;
raw streams stay private and billing settlement remains unknown. Earlier
authenticated successes/timeouts retain their original interpretation.

Main integration remains frozen at `98eae28` for the active C5 r3 engineering
run. No new module/combination efficacy, real calibration or VAL acceptance is
claimed. All 48 questions, singleton/pair/triple/full/LOO/C5/Q6.3 experiments
and TRAIN-only optimization remain required.

# 2026-09-14 Seven additional phase host writers and readers

`cd12b9b` connects the actual exploration/scheduling, state/exploration,
state/scheduling, mechanism/exploration, mechanism/scheduling,
admission/prediction/exploration and execution/improvement hosts. Their
`execution_phase_inputs` records bind the exact material, cell, objective,
public paths, image, timeout and requested selection. These hosts do not invent
C4 model or retrieval parents when execution precedes a model call. The original
trace anchors the completed descriptor prefix; readers check both actual inputs
and original output bytes. Invented zero costs, optimizer visibility, extra
metadata and foreign task bindings are rejected.

The first frozen check at `1d0dc06` passed 27 of 28 tests: its failure exposed an
existing mismatch between opaque early-failure bindings and the panel reader.
The repaired reader accepts either exact original binding representation and
rejects a foreign cell digest. At `cd12b9b`, all 39 checks passed in 608.141s,
with 695 unchanged source files. The cases include six host families in enabled,
disabled and failed-Docker modes, eight phase-artifact regressions, two C4 actual
history/target paths and the complete 32-target execution/improvement grid.
These use actual Docker and synthetic model peers, with zero paid provider calls.
The overlapping 28- and 39-test batches belong to their respective versions.

`results/modular-engineering-20260914/phase-host-artifacts-r1/` retains both
attempts, exact source ZIPs and 51 public runtime witnesses: 1,717 files and
2,120 descriptors. This includes the original rejected failure and all 32
execution/improvement targets. Archive integrity is distinct from replay in the
original execution environment. Six sampled host families do not establish
complete scientific grids. Low-level interrupted-phase host acceptance,
standalone M9 builders, cross-catalogue configuration edges and audit overhead
remain open. No scientific effectiveness or VAL acceptance is inferred.

# 2026-09-14 Closed proposal builder hosts and control attribution

State-improvement builds and the shared metaprogram training host now register
the actual closed proposal, selection inputs, original parent TRAIN manifest,
selected DSL, raw returned components, each durable candidate/receipt file and
terminal state. The model session remains terminal. Its catalogue seals after
local build bookkeeping; the original success readers require a successful
verified build. Restricted interpreter output checks remain separate from each
host's selection policy. A proposal task is not silently added to the parent's
manifest. Model/provider accounting and study success criteria are unchanged.

The shared writer preserves the original return before invoking the host's
return observer or writing individual outputs. Interpreter errors, observer
errors and writes that fail after creating bytes retain their original error
and existing outputs. A failure while sealing adds a note rather than replacing
the original exception. C4 retains its own proposal/revision selection contract
and projection check; the new hosts do not fabricate C4 invocation parents.

Frozen `35d2209` passed 50 checks in 760.765s with 697 unchanged source files.
These cover 19 existing builder cases, 10 label-isolation cases, 10 direct closed
proposal cases, the 11-build/22-target state grid, an 8-cell Q6.3 run, two C4
history/target paths, retained foreign builder returns, Q6.1/6.5/6.6 operation
grids and three complete 12-cell Q6.2 normal/failure runs. Actual Docker and
synthetic model peers were used, with no paid provider calls. Earlier attempts
at `8515688` and `a3a636d` each stopped at test 30 after fixture-construction
errors (missing M9 prerequisites, then a required instruction); both are retained.

Read-only review then found eight actual closed Q6.5 controls whose shared
proposed builder had incorrectly marked disabled M9 as applied. This did not
change the selected builder but invalidated that attribution field. `782772f`
checks the disabled arm before the shared-proposal case. All 11 targeted checks
passed in 63.735s, including the full 16-cell Q6.5 grid and label isolation.
The original response and selected DSL remain shared by those controls; the
corrected status does not estimate the builder's causal contribution or audit
the separate downstream guard. The earlier 50-check pass retains this known
limitation and is not presented as covering the later correction.

`results/modular-engineering-20260914/proposal-builder-artifacts-r1/` preserves
four check versions, source ZIPs, the review/reproduction, and selected public
builder files plus proposal catalogues and host receipts: 1,626 files, 131 build
witnesses and 1,707 descriptors. These are selected output witnesses, not complete
host directory archives or execution in the original environment. An initial
archive allowlist omitted two existing public journal filenames; its error and
helper are retained, and the reviewed seven-name allowlist was used to finish.

The separate scenario fixture builder, other candidate optimizers, downstream
activation/rollback artifacts, cross-catalogue TRAIN configuration edges and
audit overhead remain open. The complete C5 run still owns frozen integration
`98eae28`; these changes reside in the artifact worktree. All original questions
and combination studies remain required. No real module efficacy, scientific
calibration, VAL acceptance or production promotion is claimed.

# 2026-09-14 Independent Q6.3 fixture builder and registry outputs

The actual `run_improvement_scenario` Q6.3 branch now records immutable task and
control inputs, callback requests before dispatch, original typed callback
returns, selected DSL, meta package, fixture acceptance request/return and local
registry state. Initial and activated SQLite bytes have separate immutable
content-addressed copies. The existing restricted output writer retains its
two-unit search allocation, original builder return, candidate/receipt files and
failure terminal. Fixed controls retain their ignored callback and fixed DSL;
their M9 records are `not_applied`. Overall result bookkeeping belongs to P0.

`verify_q63_fixture_artifacts` compares the original returned result and callback
records, rederives fixed/proposed selection, checks the fixture acceptance
binding, reads registry byte copies in an in-memory SQLite connection, verifies
the actual final registry, and requires successful inner builder output for a
successful result. It does not dispatch callbacks or initialize/activate a
registry. The original result, full owned file inventory, catalogue seal and
closure are checked together. Missing originals are never recreated.

`inspect_q63_fixture_failure` reads a failed attempt's retained storage and
original error, and explicitly reports `stage_semantics_verified=false` and
`acceptance_eligible=false`. Its scope is storage integrity, not execution
acceptance. A failure after the real registry commit retains both the initial
byte snapshot and the changed original database; the observer does not roll
back or hide the side effect. Unrecordable callback object types are identified
without fabricating their raw contents.

Frozen `9786bd0` passed 84 checks in 61.609s. The public failure inspection and
truncated-catalogue contract checks at `a240f8c` passed 86 checks in 64.156s.
Both retained 699 unchanged source files and incurred no paid provider calls.
The latest set consists of 17 fixture artifact cases, 40 existing M9 scenario
cases, 19 existing builder cases and 10 label-isolation cases. It covers actual
fixed/proposed/rejected fixtures, partial writes, callback/interpreter failures,
the post-commit registry failure and coherently rehashed control/candidate
selection or terminal substitutions. These use the real local restricted DSL,
SQLite and filesystem with synthetic callbacks; they do not execute Docker or
model APIs. The overlapping 84/86 batches are version-specific evidence.

`results/modular-engineering-20260914/fixture-builder-artifacts-r1/` preserves
167 files: both exact source ZIPs and check reports, plus 19 complete selected
public fixture directories containing 191 descriptors. These are repeated
engineering executions, not unique benchmark subjects. Historical byte
integrity is distinct from replaying the original execution environment.

The other fixture optimizer and activation/rollback outputs, P0 custody,
cross-catalogue TRAIN configuration edges, generic lifecycle and resource
attribution, audit overhead and all original scientific experiments remain
open. Existing C5 integration is still frozen for its original live run. This
fixture uses only synthetic acceptance material; no real VAL acceptance or
production authorization is created.
