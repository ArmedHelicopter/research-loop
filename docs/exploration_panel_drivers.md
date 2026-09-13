# Q7.1 / Q7.2 production panel drivers

`research_loop.modular.exploration_panel_drivers` supplies caller-bound drivers
for exploration permission/evidence qualification and feasibility-veto appeals.
Q7.3–Q7.6 remain distinct research obligations; this implementation does not
claim their completion or scientific effectiveness on real benchmark tasks.

The integration owner installs the two drivers with an explicit Docker broker,
public-input resolver, and trusted `ExplorationAuthorityPort`. The module does
not mutate the common registry or controller. `freeze_exploration_panel_bundle`
requires a train `PublicTask`, all five Q7.1 and three Q7.2 typed variants, and a
`FrozenRecord` equal to `BUDGET`. `exploration_panel_injection` reconstructs and
checks task, data version, source, public payload, material and budget bindings.

Every variant carries two actual public Python diagnostics, exact byte hashes,
a digest-pinned image, public CSV artifact hashes/sizes, measurement and negative
control contracts, original resource requirements and smaller diagnostic
requirements. Missing authorization/resources are typed `hard_constraint`
values and verified host facts, not malformed configurations. They remain
observable cells. Path/hash/source/schema errors are configuration failures.

The fixed schedule is `prospective` → `diagnostic` → `final`, with three model
opportunities, one restricted execution opportunity and two verification
opportunities. `prospective` freezes the model's choice and judgement before
any verifier result or execution. It contains no expected fixture observations,
authority documents, variant label, enabled-module flag or declared scientific
qualification. Public executable plans and their prospective estimates are
available equally to both arms.

Both available candidate input sets are validated against their frozen actual
hashes and sizes before any model/verifier I/O. Explicit resource/authorization
missing cases bypass those reads and retain a blocked, nonexecuting denominator.
The chosen inputs are revalidated at execution and again before observation
verification to catch drift after the first preflight.

M7 executes the existing bounded diagnostic selector and exploration policy;
Q7.2 also executes `review_appeal`. The selected literal diagnostic is the one
actually sent to Docker. The control executes its model-selected diagnostic
under the identical fixed host safety boundary. No diagnostic can consume more
resources than the original plan, and its summed resource request must be
strictly smaller. The trusted port checks actual source/program/input hashes
and the original-versus-diagnostic resource requests.

The original veto kind, evidence digest and resource request remain in the
transition record together with the selected request, preflight binding,
actual observation binding and prior/resulting block status. A deterministic
contract objection can become `repair` only after a completed diagnostic and
trusted `cleared` plus `repair_supported` observation. A value objection may
remain eligible for exploration without acquiring scientific validity. Missing
authorization/resources remain blocked in both arms; an appeal is not authority
to bypass them. Diagnosing a repaired plan never promotes the original
prerequisite or revives old findings.

M1 applies `EvidenceAdmission` to verified actual execution evidence and adds
the resulting disposition to the next request. Exploration admission concerns
the small safe diagnostic only; original scientific data and measurement status
remain separate. The fixed P0 audit/admission boundary runs in both arms, and
the final model candidate is passed unchanged to `RunSession.finish`. Incorrect
model judgements are retained for measurement; the driver does not replace them
with expected labels, force every candidate to unknown, or infer scientific
validity from Docker exit zero.

`verify_preflight(subject)` and `verify_observation(subject)` return closed
frozen receipts binding the exact task/source/version, selected diagnostic,
measurement contract, original resource requirements and prospective judgement.
Two distinct external observation sources and signatures are checked by the
caller-owned verifier; these establish provenance, not scientific truth.
Observation receipts additionally carry the two signed P0 scientific audits.
An actual implementation must perform the scientific/measurement checks before
issuing them. The synthetic test authority compares actual Docker stdout with
two frozen observation documents, including numeric mean and negative control,
and separately verifies program/input/source/version contracts.

The trusted observation subject additionally includes the complete
`ExecutionReceipt.data()`, actual program bytes, and actual public CSV bytes,
encoded losslessly as base64 and rechecked for exact frozen SHA-256/size. The
fixture verifier reconstructs the full execution receipt, checks its digest,
matches the bytes to both the received execution artifacts and frozen measurement
contracts, and computes the public CSV statistic independently. None of these
host paths, full receipts, or byte payloads enters the final-model whitelist.

Scientific status preserves `unknown`, `data_unknown`, `measurement_repair`,
`qualified_negative`, `qualified_positive`, and `conflict`. Qualified statuses
must agree with the verified scientific state/outcome; unresolved or conflicting
statuses cannot claim valid admission.

The controller durably records allocations and each verifier request with
unknown cost before I/O, followed by every raw response, measured-or-unknown cost,
failure and selected execution reservation. RunSession independently reserves
model slots and execution attempts before their I/O. Blocked opportunities remain
reserved in the denominator; unused calls are not represented as executions.
There are no paid providers, network-enabled containers, validation reads,
deployments, or changes to old custody state in this bounded verification.

Transport exceptions may carry a typed `partial_response: FrozenRecord` and a
typed `cost` record/mapping. Partial responses are persisted before failure;
returned/exception-reported costs remain separate from unknown verified cost.
Unknown cost is never converted to zero, and an unvalidated partial response is
never used as an observation. Returned and exception-reported costs refer to
the same attempt and must not be added as separate charges.

The prospective synthetic grid is 52 cells: two benchmark adapter types × five
Q7.1 variants × four M1/M7 combinations, plus two adapters × three Q7.2 variants
× two M7 arms. Results only test causal controller wiring on public synthetic
data; they do not estimate benchmark-level scientific effectiveness.

## Frozen verification

Source commit `b55c170` passed 20 final driver tests under the existing isolated
`work/custody-root-venv/Scripts/python.exe` environment. The frozen Git blob and
post-run source bytes are identical, SHA-256
`36f52471d1493b8625a1be9a7433efada0334b164f5b31874854d80dba17a0f6`.
The complete main grid has 52 real Docker executions, 156 model requests and
104 trusted-verifier requests/results (104 measured fixture verifier units).
All 52 trace chains verify. Terminal outcomes are 8 closed negatives under the
synthetic scientific audit, 22 invalid and 22 unknown; this is not an all-unknown
substitute for execution and is not a real benchmark effectiveness estimate.

The final suite also checks both candidates before I/O, bad actual sources at
zero model/verifier calls, post-Docker program/CSV drift, foreign source/subject,
bad signatures, inconsistent scientific-audit subject, typed hard resource and
authorization absence, unresolved deterministic blocks, partial transport
responses with measured and unknown costs, and unchanged overclaim candidates
being rejected by fixed P0. Fault cases are bounded synthetic counterexamples,
separate from the 52-cell main grid denominator.

`docs/exploration_panel_verification.json` binds the per-cell traces and five
retained JUnit reports. The earlier source revisions' suites remain separately
recorded (10, 48 and 14 tests); the final preflight has 10 tests and final
post-review driver suite has 20. None is silently replaced by a later run.
