# Review scenario artifacts

`run_review_scenario(..., artifact_root=...)` requires a new directory without
linked path components. Before the first callback it durably records a unique
attempt ID, frozen TRAIN task, cell identity, controls, variant, complete
callback allocation, and caller-supplied reviewer identities. It pins seven
known source files: the review runner and artifact implementation, contracts,
artifact catalogue, M5 review engine, M4 prediction registry, and ontology.

The v3 journal retains every reservation, exact callback payload, raw returned
JSON value before conversion, typed response and candidate, actual M5 event,
revealed submission, M4 freeze event, and actual frozen M4 payload. A separate
`previous` hash records chronological order. Each record also names its consumed
input records through `parents` digest references with `parent_relation` set to
`consumes`. For example, a revision payload consumes the reveal record, a typed
response consumes its raw return, and a candidate consumes its typed response, and an M4 freeze consumes
the retained candidate records. These engineering dependencies do not assert
scientific causal support. The input record itself is the parent of audit open.

The producer checks its original source snapshots and retained input/journal
prefix before every next callback. It retains the full output and mechanism
trace, closes the literal file inventory, and requires the actual offline
consumer to accept the artifacts before returning a result.

`verify_review_artifacts()` reconstructs the full deterministic review execution
from independently supplied task, controls, variant and reviewer identities,
using retained raw callback values. It compares every allocation, payload,
response conversion, M5/M4 event, consumed-record reference, metric, budget,
trace and output. Its registries remain in memory; it invokes no user callback,
opens no registry log file, and writes or repairs no artifact. It pins the exact
known original source paths and current bytes. Relocating artifacts alone is
supported; a relocated or changed source tree requires the original source
context or a separate archive-aware verification path.

An optional external `review_log_path` must be fresh, outside the artifact root,
and free of linked path components. Actual M5 event delivery writes this log,
checks its prefix at subsequent event/callback boundaries, and archives its
bytes at closure. The consumer checks the archived bytes against reconstructed
M5 events without reopening or creating the original external path.

Failure handling preserves raw invalid JSON values, callback exceptions and
the complete persisted prefix. A successfully checked failed attempt establishes
only that the retained prefix matches permitted operations; it does not attest
the origin or truth of an external exception message. Unsupported Python values
without canonical JSON bytes retain their type and a failed boundary, not an
invented textual representation. Partial storage writes are preserved and
refused as incomplete; a delivery rejection cannot be reported as success.

The retained response is producer-observed evidence, not cryptographic proof
of an external provider's authorship, independence, or faithful behavior. These
are offline engineering fixtures. They dispatch no benchmark and establish no
benchmark efficacy or scientific validity. Earlier v2 evidence is preserved;
it is not promoted into the stronger v3 contract.

The integrated source `cd38ab96` passed 135 frozen checks, with zero failures,
errors or skips and 747 source/document files unchanged. This includes all 15
registered variants on both synthetic benchmark identities, complete consumed
parent references, recomputed-hash modifications, raw invalid responses,
partial storage, actual return refusal, shared M4/M5 readers and label isolation.
The coherent-copy helper remaps ordinary parent hashes as well as chronological
hashes, so stale parent hashes alone do not explain content-modification rejection.

The original runtime archive is
`results/modular-engineering-20260915/review-scenario-artifacts-r1/`: 87 selected
directories comprise 49 completed fixtures, five failed prefixes and 33 refused
byte sets. It retains all 30 matrix cells and 30 coherently modified copies,
independent pre-producer inputs for the matrix and sequential-copy tests,
historical failed review findings, frozen sources and JUnit reports. Its 132
original files plus attributes, manifest and verification total 135 files.
Read-back preserved every selected runtime file's bytes and modification time.

The root's first integrated check was interrupted because its launcher omitted
explicit E-drive TEMP/TMP; it has no completed JUnit or passing closure. The
corrected run used a new prefix. An older worker label-isolation run has five
failures out of ten because that sparse worker omitted the required fixtures;
those failures remain archived. The root's integrated label checks used its
existing engineering fixtures. No model service, Docker or real VAL was used.
