# Admission combinations in one train session

The closed controller executes the registered conditional factorials M1+M2,
M1+M3 with fixed M2 background, and M1+M5 without additional background.
Two caller-selected core benchmark tasks yield 24 cells. Every cell reserves
two public review model slots, analysis, final answer, one Docker attempt,
two source authority calls, and one independent primary scorer call. Failure
does not remove a cell or authorize a retry. Negative singleton results do not
prune these panels.

The caller freezes exact custody task/CSV bindings, candidate, scientific
check subjects and before/after source observations before execution. Two
configured authorities independently return signed, exact-subject assessments.
Their agreement authorizes host facts; distinct keys and source groups alone
do not establish scientific independence. M1 actually calls EvidenceAdmission
on these facts before and after requalification. Failed or unknown validity
cannot admit evidence. A valid negative result passes the same gate as a valid
positive one. Requalification can revoke earlier eligibility.

M2 records actual admitted and unadmitted observations and claim relations,
deduplicates actual roots, and withdraws newly ineligible roots. Without M2,
the session uses an ordinary observation buffer and writes no ledger events.
Without M1, this buffer does not filter by scientific eligibility, and M2 may
record provenance but cannot claim scientific admission. M3 rebuilds context
from the actual ledger. M5 reveals two actual sealed reviews after both finish.
The solver consumes the resulting public observations/context/reviews in that
same session and executes its returned program. No arm, authority or expected
outcome labels belong in the public material or requests.

Independent replay checks the original signed assessments, precise subjects,
actual ledger/review events, requests, program bytes, CSV artifacts and original
terminal failure. The existing primary scorer runs in a separate stdio process
with a signed input from this replay, not from caller-provided driver truth.
The engineering fixtures use synthetic source checks, model transport and
reference material with actual Docker and scorer subprocesses. This does not
measure scientific admission accuracy, mechanism calibration or real training
gain. Production source lineage qualification, OS authority isolation and
independent mechanism reference/rubric validation remain separate obligations.

## Closed API

`FrozenAdmissionTrainConfig`, `compile_admission_train_panels` and
`run_admission_train_panels` reuse the existing lineage controller and runtime
verification kernel. The configuration schema is
`admission-combination-train-config-v1`; exactly two tasks and one replicate
are accepted. Caller-supplied `scoring_service` maps each of the three exact
obligation IDs to its own `CombinationScorerProcessClient`. Each client uses
`admission=True`; default process scope remains M4+M5. Its server configuration
uses `admission-combination-scorer-process-config-v1` and the frozen primary
rubric digest. Other combination families require their own explicit scope.

`FrozenAdmissionMaterial` adds `qualification_observations` with exactly
`before` and `after` mappings covering every original observation. Literal
scripted withdrawals are forbidden. `subjects()` freezes identity, task,
complete custody CSV artifacts, original observation, phase and its submitted
qualification observation. `AdmissionMaterialVerifier` requests two signed
`admission-material-response-v1` responses. Each contains exact subject-bound
state/outcome/strict execution bool/measurement audit for every phase and root,
plus verdict and actual or unknown cost. Both authorities must agree; unknown
source provenance stops the cell, whereas agreed unknown scientific validity
remains a legitimate M1 rejection. Before each call, its reservation and limits
are persisted. Known and unknown costs survive malformed or failed responses.

Only initially eligible observations enter the M1 working set. The second
phase can revoke these records; becoming newly eligible does not create a new
observation or retry within this frozen budget. M2-off retains representations
in its ordinary buffer, while M2-on deduplicates real roots. In M1-off arms,
the source-qualified buffer remains scientifically unadmitted, so M2 does not
fabricate support edges from unqualified observations. Gate decisions and
source truth remain in controller evidence. Public evidence uses opaque
subject digests instead of host validator names.

The fixture primary evaluator intentionally returns equal scores, yielding
estimated zero interactions, not structural non-identifiability. Actual solver
programs consume changed observation counts, current claims and available
reviews. This verifies causal plumbing without measuring scientific utility.
