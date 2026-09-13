# Primary prospective training export

`PrimaryProspectiveTrainExporter` exports only exact train members of
`prospective-primary-observed-family-split-v1`. It accepts the frozen process
configuration, canonical split/audit digests, the raw SHA-256 of both seal files,
an explicitly pinned eligibility record, separate output/audit roots, and typed
`PrimaryTrainExportItem(source, token, group_sha256, input_bindings_digest)`
requests. It has no validation exporter or lease method. Unknown schemas,
disabled training eligibility, held groups/members, foreign or validation tokens,
wrong groups, stale input bindings, and changed source bytes fail closed.

The eligibility record schema is `primary-train-export-eligibility-v1` with
`split_sha256`, `audit_sha256`, `train_export_enabled`, `held_group_sha256`,
`held_member_tokens`, `review_evidence_sha256`, and `validation_access_enabled`.
The last field must be false. The trusted broker owner supplies and maintains
this current eligibility view, including applicable hold/revocation evidence.
This local pinned record is not authenticated OS isolation or permission to
ignore a newer eligibility hold. A changed record invalidates the configured pin.

Validation and metadata eligibility checks precede source reads and any exposure
reservation. Every input path and source file has its ancestors checked for
symlinks/reparse points. The audit is recomputed with its original end boundary,
and the primary inventory and canonical aggregate source bindings are checked
again before publication. Selected metadata/CSV bytes must match both the old
inventory and their exact path-bound SHA from the process audit; the same buffers
are used to prepare the task and write the CSV. A post-check substitution cannot
be admitted merely because another inventory file has the same allowed hash.
These checks constrain observed local I/O; they do not establish OS isolation.

The shared pure `prepare_primary_public_task` function invokes the existing
DiscoveryBench/BLADE adapters. The legacy `TrainPacketExporter` uses the same
function and retains its original custody/identity protocol. The new exporter
returns standard `PublicTrainPacket`s: typed public task, public CSV, packet
envelope, and source-bound receipt. Discovery metadata/query selectors remain
available to a separately controlled scorer. Private reference, answer, label,
annotation, and scorer files cannot be selected as public source files; arbitrary
upstream metadata fields do not enter the adapter allowlist.

The existing prospective exporter supplies the common durable journal, local
cost receipts, staging, exposure reservations, atomic publication, and partial
failure retention through small preparation/materialization hooks. The primary
broker checks current eligibility again before each exposure reservation and
rechecks its audit before publication. A failed publication retains the already
reserved possible exposures and staged bytes. Its own model/network call counts
are zero and do not reset historical model costs.

`run_train_panel` now accepts an explicit `prospective_exporter` parameter.
Exactly one mode is allowed: legacy `CustodyStore`, or the typed primary exporter
with `custody=None`. Snapshot/output roots must match the broker. The new mode
uses opaque tokens in the frozen controller `item_ids`; the returned packet
receipts must match that exact allowlist. The controller consumes the same typed
tasks/CSV interface without creating a fake legacy split or clean attestation.
The old 81-task protocol remains available through the unchanged legacy mode.

This delivery uses synthetic sources and a real `CodexModelPort` with a mocked,
zero-cost transport to exercise the production controller and complete Q3.1
grid. Reference markers remain outside solver tasks and traces; no scientific
scoring or efficacy is asserted. No actual primary train or validation payload
is exported by this implementation/test task. Real training export remains a
separate, explicitly scheduled bounded operation.

The implementation frozen at `e57b1dd` passed 127 related checks with no failures
or skips, including the old controller and custody paths. The complete synthetic
Q3.1 grid executed 12 cells and 24 mocked model calls. Four controller rejection
cases (validation member, eligibility hold, wrong roots, and simultaneous legacy
and prospective ports) made zero model calls. An actual same-byte symlink fixture
was rejected. Source hashes remained equal to the frozen commit throughout the
final verification.

The first test run retained a RED case where canonical digests alone accepted
whitespace drift in a sealed file. Explicit raw split/audit file SHA pins repaired
that gap. A subsequent archive-only directory-prefix mismatch was also retained;
it did not change the completed test result or production source. Exact JUnit,
source hashes, synthetic controller receipts and ledgers, and preserved failures
are listed in
[`primary-prospective-export-verification.json`](primary-prospective-export-verification.json).
