# Q6.3 restricted metaprogram training phase

This train-only phase connects an actual model builder proposal to the existing
RestrictedBuilderPort interpreter and an actual successor benchmark solve. It
never calls BuilderRegistry, grants acceptance, reads validation, invokes a
scorer, creates a task or selects a new evaluation problem. The API is separate
from run_train_cell: a proposal is a typed phase terminal, and the successor
solver owns its own single ordinary RunSession.finish.

## Caller-frozen inputs

Use FrozenTrainHistory.freeze(task, trace_path, expected_sha256=..., source_notes=...)
for an existing completed training journal, and FrozenMetaTarget.freeze(task,
public_inputs=..., objective=...) for each caller-selected public train target.
The history API reads the actual journal; arbitrary metadata or a callback
summary cannot substitute for it. It checks full file SHA, hash chaining,
original solver lock, task/domain/package/objective, paired original model
requests and responses, program/execution binding, and a real terminal. It
supports the existing analysis_program/final_answer solver trace contract.
Completed failures are eligible history; running or truncated traces are not.
A response rejected by the original driver remains a failed historical
observation, with its raw response bound in the journal and unavailable public
fields projected as null. Changing source notes cannot duplicate one actual
journal path in the whitelist.
Source notes retain caller provenance and known limitations without qualifying
them as scientific facts. These checks authenticate caller-frozen journal
structure, not provider authenticity, scientific truth or source independence.

The phase does not acquire or generate history. The caller must freeze its full
historical whitelist before observing this phase. It does not filter histories
for success. Historical acquisition costs are inherited and retained separately;
ordinary runtime journals do not establish those prior provider costs. In
particular, recorded synthetic fixture journals demonstrate this API but are
not a substitute for a real scientific training history. Prior exposed or
context-contaminated train histories must retain that qualification; they cannot
be reported as clean module effects. An active run must never optimize itself.

FrozenMetaTrainingPlan.freeze takes those targets/histories, the actual parent
CandidatePackage, a fixed FrozenBuilderVersion, baseline_digest, p0_control,
pinned Docker image, timeout and model_configuration(real_codex_port). The parent
manifest must exactly cover the frozen train subjects. Input paths are host-only
references; their complete named artifact set, SHA and byte count are frozen.
Every source is checked again before the phase and at stage boundaries.

## Exact matched design and consumption

The design uses the existing Q6.3 variants fixed/train_proposed and compatibility
M9 off/on arms. Both benchmark adapters are required. One target from each makes
eight cells. Every cell has one model builder-proposal opportunity, one
RestrictedBuilderPort execution, one analysis_program call, one Docker attempt
and one final_answer call. All proposals are validated, including proposals
whose selection is disabled. Proposal failure stops that cell, with no retry.
Only train_proposed with M9 enabled selects the proposed builder; the other
three variant/arm combinations execute the preregistered fixed builder. Thus
fixed is a negative control for module activation.

The DSL is the existing emit_literal_change_v1 interpreter, further restricted
to prompt/instructions or memory/lesson with a nonempty value of at most 16000
UTF-8 bytes. It emits a literal CandidatePackage change, not Python or a host
callback. The phase records the original returned package and BuilderRunReceipt
before validating their exact DSL, parent and train-manifest relationship.

The generated instruction or memory lesson is inserted as its actual text in
the successor's public predecessor_context. Both successor model requests must
contain exactly that projection and lock the generated package digest. The
independent phase verifier checks the real model response against the provider
ledger output hash, the generated package and builder receipt, actual successor
requests, literal program bytes, Docker program artifact and complete input set.
Host paths, full packages, variant/arm labels, authority keys and controller
selection decisions stay outside model context. The memory lesson is per-solve
public context; this does not activate a persistent global memory or builder.

This establishes that changes reached the real model input. It cannot guarantee
that an arbitrary model obeyed them or that changed answers are scientifically
better. Synthetic mocked transports deliberately read the actual text and
produce differing real Docker calculations to test causal wiring, not quality.

## Execution, costs and failures

run_metaprogram_training(plan, run_root=..., model=..., audit_verifier=...) requires
a fresh real CodexModelPort with the frozen reviewed context, schemas and Luna/low
budget. The caller configures authority keys outside the public plan; no audit
admission is performed by this phase. The internal Docker broker permits only
the frozen public input directories and fresh phase root. Roots exclude links
and label-containing ancestors, and used phase roots cannot be overwritten.

A fsynced phase journal reserves every model call and builder attempt before
I/O. Model ledger call IDs, request digests and output digests are distinct
bindings: identical negative-control requests may legitimately occur multiple
times. Receipts distinguish model requests, provider calls, reported-token
subtotal, unknown cost, builder attempts and Docker attempts. Missing provider
usage remains unknown. A failed provider can close its ledger; remaining cells
stay in the denominator with requested-but-not-started slots, rather than being
retried or reported as paid calls. Invalid builder returns and all failure stages
remain archived. No cell is scored and none is pruned.

verify_metaprogram_training(result, plan=...) is read-only. It rereads the actual
phase, proposal and solver journals, immutable sidecars, generated artifacts and
frozen provider ledger. It verifies the full cell denominator and actual cost
coverage. Any failed cell yields engineering_incomplete; successful synthetic
execution yields engineering_complete with scientific_effect=not_measured.
Filesystem loss or source drift that prevents independent reconstruction fails
verification; the already written attempts are retained for operational review.

## Verification scope

Tests create prior source journals by executing the existing solver with public
synthetic custody exports, real CodexModelPort and a mocked local process, and
real pinned Docker. The eight-cell phase then uses a fresh matched port. Tests
cover prompt and memory consumption, fixed negative controls, failed historical
executions, invalid DSL, foreign builder outputs, source/input/schema/budget
preflight rejection, provider usage unknown, Docker failure and independently
rebound ledger/source tampering. There are no paid calls, private references or
validation inputs. Scoring, meta improvement, transfer, provider authenticity
and scientific validity remain unmeasured.
