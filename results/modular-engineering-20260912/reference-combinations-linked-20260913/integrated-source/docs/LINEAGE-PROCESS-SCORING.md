# Lineage process scoring v1: train-only engineering contract

The new entry point is `evaluation.modular.lineage_scorer_process`. It adds a
separate scorer process for each of the four frozen lineage panels and a
`LineageScorerProcessPool` accepted by `run_lineage_train_panels`. The exact
compiled panel must match its worker before any solver call. The old linked
and M4/M5 server schemas and default primary evaluator mode retain their
original behavior. Existing scored runs are neither migrated nor rescored.

`CodexEvaluatorModelPort(..., rubric_mode="lineage_v1")` uses
`FrozenLineageRubricEndpoint` for an exact frozen prompt/template/schema. One
provider call produces the existing benchmark primary dimensions plus
`root_attribution`, `withdrawal_awareness`, `context_currency`, and
`review_responsiveness` in {0, 0.5, 1}. All dimensions share the same actual
output/prompt/schema/reference evidence. The public joint describes what the
solver saw; it is never the endpoint answer key. The evaluator projection
omits the opaque cell marker and excludes controller labels. The solver does
not receive the references, scorer keys, scorer prompt, or evaluator ledger.

The separate `qualified-lineage-train-reference-v1` contract binds a full train
identity, task digest, lineage material digest, and the exact primary reference
digest. Every endpoint has an explicit expected criterion and citations into
`lineage-train-annotation-source-v1` files. Every citation must exactly match
its source assertion; each source has the same identity/task/material and an
explicit `caller_qualified_train_annotation` qualification. Each file is plain,
canonical UTF-8 with an exact byte-count/hash descriptor. A pinned manifest
covers the exact task set; all source files are checked at startup and again
before each provider call. Foreign tasks/material/versions, missing citations,
unqualified sources, changed bytes, and unknown reference contracts fail closed.
No private benchmark data or validation reference is needed by the synthetic
contract tests. The real deployment must provision genuinely qualified train
annotations; putting the qualification string in a file is not evidence that
its scientific assertions are correct.

The train config's `lineage_reference_binding` freezes the manifest/reference
hashes, identity-to-task/material subjects, and scorer model/effort, token
allocation and timeout. Each worker has exactly its panel's cell count as its
call limit and that count times the per-cell token allocation as its total
token limit. This is an aggregate budget allocation, not a provider-enforced
per-request token cap. A startup handshake checks these values plus the full
panel, task-handle hashes and distinct execution/scorer key hashes. Reference
contents and keys are only configured on the scorer side.

Client and server persist a reservation before submission/provider work, use
UTF-8 even under Windows GBK stdio defaults, and do not retry unresolved cells.
The protected evaluator persists the original invalid output, errors and
known usage before returning a failure. Later calls are blocked when usage is
incomplete. The controller retains every source/solver/scorer failure in the
original grid and returns inconclusive rather than pruning it. Each scoring
attempt also saves a signed, nonce-bound cumulative evaluator usage snapshot;
unavailable snapshots remain explicitly unknown. A scoring submission count
is not an actual evaluator-provider call count. An unknown cost is not zero.

Process separation, signed receipts and source hashes provide engineering
provenance. HMAC keys are symmetric and the launcher/controller shares the
host account in the fixture tests. This code does not implement OS accounts,
ACLs, inaccessible mounts, sandbox escape protection, or independent authority
attestation. Deployment must supply those boundaries separately. An enabled
Codex tool flag is not itself an OS isolation guarantee; the reviewed context,
no-tools event checks and protected model contract remain required.

Tests use public synthetic custody/tasks, real Docker solver executions, real
Python child scorer processes, and an actual CodexEvaluatorModelPort with an
explicit fixture ProcessRunner. They make no paid provider calls. Fixture
scores verify transport, schema, signing, binding and accounting only. They do
not establish endpoint accuracy, benchmark calibration, module benefit,
scientific independence or production promotion/validation acceptance.
