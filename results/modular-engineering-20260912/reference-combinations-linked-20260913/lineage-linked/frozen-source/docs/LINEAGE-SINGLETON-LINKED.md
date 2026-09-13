# Q1.1–Q1.4 linked train execution contract

This extension uses the existing `run_train_panel` → `run_benchmark_cell` →
`run_train_cell` and `run_benchmark_solve` path. Each cell keeps its existing
three mechanism slots and receives the same two solver slots and one Docker
opportunity. No parallel runtime or second finalization is introduced.

Two frozen controller configurations preserve the existing exact source bundle
contracts: history (`Q1.1`, `Q1.2`) and support (`Q1.3`, `Q1.4`). Both use the same
caller-prepared train tasks and candidate package. Existing compatibility gives
12 + 18 + 16 + 12 = 58 cells across both core benchmarks. Q1.2 retains its three
legal arms, including its dependency-constrained grid; no invalid cell is invented.

`history_admission_port` passes unchanged through the linked wrapper to the
registered driver. The caller remains responsible for verifying the two source
authorities and exact record subject before returning an admission receipt.
Fixture tests perform actual signed material-audit verification. That verifies
configured provenance, not scientific correctness or authority independence.

The linked public projection must be rebuilt from the actual verified mechanism
events, frozen source bundle, ledger operations, context material, and matching
model requests. It exposes neutral public observations and claim/context results;
Q IDs, variants, arm labels, expected correctness, admission authorities and
inactive source bundles remain outside solver context. Source identities use
neutral opaque IDs. Public record contents are caller data, not controller truth.

The resulting material enters both actual solver requests, with the original
mechanism provenance digest retained as an opaque binding. Root deduplication,
withdrawal, dependency refresh and context rebuilding must affect the material
actually consumed by the solver. Independently recomputed stage/root/context
mismatches refuse the solver. Source and solver failures retain their original
terminal status, usage, unspent opportunities, and denominator rows.

The independent primary scorer receives the executed anonymous candidate through
the existing linked-score contract. It does not use driver outcomes as its answer
key. Synthetic fixture score success is only engineering evidence; scientific
mechanism scoring, calibrated references and actual training effects remain
not measured. No paid models, actual references or validation payloads are used.

Readonly replay constructs fresh in-memory EvidenceLedger, ClaimLedger and
ContextCache instances and invokes the registered operation implementation with
recorded responses. It does not initialize an on-disk RunSession, call a model,
call an authority or execute Docker. Every rebuilt request, full stage sequence,
final decision, and canonical fixed-path evidence/claim JSONL event must equal
the original. Reparse paths, malformed proofs and changed final output bindings
are rejected. This checks the executed engineering contract; reuse of the
operation implementation is not an independent scientific algorithm oracle.

Source-admission attempts are persisted before the caller port is invoked.
Failures retain their attempted subject, error type and unknown cost. The legacy
caller port does not supply measured tokens or money; the call plan therefore
reports the actual attempt count and `not_provided_by_caller_port`, never an
invented zero cost. The frozen source/model opportunities remain allocated to
every cell; modules may leave source operations or later solver slots unused.

The full-grid fixture model reads the actual projected active root set and uses
it in its generated CSV program; Docker stdout and the final model answer bind
that set. This demonstrates context-to-program consumption, not improvement of
the scientific estimate. Primary scoring uses the existing separate stdio worker
with a canned evaluator and synthetic-only reference store. It is not a paid
provider run, evaluator calibration, or OS-account isolation claim.

Preserved development evidence: `work/lsl-red.xml` (unsupported configuration),
`work/lsl-grid-r1.xml` (fixture nested-context error; original failed requests and
unknown usage remain), and `work/lsl-grid-r2.xml` (25 passed before final guards).
The final delivery records the committed source hash and a separate frozen run.

A separate preserved RED (`work/lsl-authority-red.xml`) demonstrates that a
caller authority named with a question/arm marker previously leaked through
mechanism contexts. Public receipt and ledger authority identifiers now use a
stable opaque digest; original identities remain in controller admission events.
No source qualification or scientific-admission rule is changed by this encoding.

Final review also preserved `work/lsl-public-field-red.xml`: recursive metadata
removal could erase a caller observation named `mode` or `ephemeral`. Projection
now strips only the two exact ledger-receipt fields at their typed location and
preserves source material and evidence content. Full-grid fixtures carry these
ordinary observation fields and compare the projected source to the actual final
mechanism request. The original frozen e94 regression remains 104 passed / 2
rejection-message failures (`work/lsl-final.xml`), with unchanged source hashes.
