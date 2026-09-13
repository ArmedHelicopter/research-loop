# Q6 train controllers: executable scope and remaining authority boundary

These controllers consume caller-frozen public train tasks, exact CSV bytes,
and actual closed solver journals. They never create evaluation tasks, open
validation or gold data, enroll BuilderRegistry, or manufacture validation
acceptance. The current tests use explicitly synthetic custody exports, mocked
Codex process transport and real pinned Docker; they do not establish scientific
improvement, transfer, calibration, provider authenticity, or production release.

## Q6.2 candidate comparisons

`freeze_candidate_training` and `run_candidate_training` use the same frozen
history, model, builder, solver, cost and read-only verifier as Q6.3. The existing
registered design supplies fixed/manual_train/automatic_train crossed with M9
and both benchmarks: twelve cells for one target per benchmark. Every cell has
one proposal opportunity, one restricted builder execution, one analysis call,
one Docker attempt and one final-answer opportunity. Actual consumption is
recorded separately, and rejected proposals or successor responses remain failed
cells without retries.

The caller freezes the manual DSL and its association with the complete history
whitelist before execution. This association does not authenticate human
authorship or prove derivation from that history. Fixed and M9-off cells use the
fixed builder. M9-on manual cells use the manual builder; M9-on automatic cells
use the actual model proposal. The selected prompt or memory change is consumed
in both downstream model requests and binds the solver lock.

## Q6.1, Q6.5 and Q6.6 host operation phases

`FrozenTrainOperationPlan.freeze`, `run_train_operations`, and
`verify_train_operations` use the registered grids and the shared Q6.3
proposal/build/solver verifier. They add an actual host operation between the
restricted candidate build and the successor solve. The generated candidate
receipt remains intact. A separate host receipt records the package actually
selected for execution, and the successor lock and both model requests must
bind that package and the public operation observation.

The host authority key and verifier source binding stay in controller-only
records. Public model context contains train observations, prompt/memory values,
bounded operation observations and opaque bindings. It contains no arm labels,
variant labels, host paths, argv, authority keys or validation receipts.

Q6.1 freezes four capability challenges. The actual model-generated bounded
literal is used as the attempted rule or forged-signature payload, while the
operation itself is fixed by the caller's challenge. Calls reach the real
candidate allowlist, train identity capability check, receipt verifier, or an
experiment-owned ExecutionRuntime. The read-validation challenge is a real
train-only identity rejection; no validation store or path is opened. Rejection
can be identical in both arms and is a boundary negative control, not an M9 gain.
These in-process shadow checks do not establish OS-level adversarial isolation.

Q6.5 freezes its criterion, initial feedback sources, two rounds and per-call
limits before execution. Both arms receive one actual host verifier opportunity
per executed round. The request includes the precise candidate/parent/cell
subject and full frozen source binding. Reservation is persisted before the
call, and original returned responses and reported/unknown costs survive errors.
Only an exact subject-bound eligible result permits guarded adoption. Unknown
or malformed results remain unknown; they cannot imply scientific calibration.
The unprotected train-shadow condition can adopt unqualified feedback. The
second round adds the previous round's actual solver journal to its history and
uses the actually retained/adopted parent, so the intervention changes subsequent
model context and execution. All original rounds remain in the denominator.

Q6.6 operates on an experiment-owned train staging deployment. It uses actual
FileDeploymentPort snapshots and SQLite active-package/token state for promote,
rollback, duplicate, drift and offline operations. Rollback feeds the old package
to the actual next solve. Drift and an absent acknowledgement file block the
successor before its model and Docker calls while retaining their allocation.
TrainStagingAuthorization uses a staging-specific signature domain and is not
valid for the production ExecutionRuntime, even if a caller mistakenly reuses a
key. No SignedValidation or approved validation metadata is created.

## Verification and costs

The read-only verifier checks original proposal/solver protocol chains, returned
candidate artifacts, actual program and input bytes, package selection, host
operation journals, immutable host files, durable staging state, callback source
bindings, exact feedback subjects, and model output hashes against the actual
provider ledger. It does not rerun the model, verifier, builder or host operation.

Model calls, reported tokens, builder attempts and Docker attempts retain the
shared verifier's rules. Feedback opportunities and reported units have a
separate denominator. A malformed source-bound contract does not erase a
reported cost; uncertain attribution is additionally marked unknown. A closed
failure may reduce actual downstream work but never its assigned budget.

Loss of required immutable source or receipt files prevents verification rather
than creating a replacement success. Existing raw attempt files remain available
for diagnosis. Host signatures attest configured engineering provenance only;
the independent scientific competence and isolation of a supplied feedback
verifier remain external qualifications.

## Production integration boundary

Train staging is a necessary executable boundary and does not complete the
production-promotion obligation. Real promotion must use an independently
issued, already qualified validation receipt and the original production
authority's verification path. These train controllers expose no function that
converts their staging or feedback receipts into such approval. Independent
benchmark scoring and validation remain separate interfaces and unmeasured here.

`check_existing_production_acceptance` is the future read-only integration seam:
it requires an already issued production receipt, the configured production
authority and a separate resolver of the original qualified source. It checks
the exact candidate/active/trial binding and performs no activation. Current
tests exercise refusal of staging receipts only; a real qualified validation
source has not been supplied or tested.
