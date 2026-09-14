# Q8.6 research-version artifacts

Q8.6 publishes a parent goal lock and, only after caller-owned independent
authorization, an optional frozen child. Each file is first written to a
sidecar-local `.partial` file, fsynced, then published through an exclusive
hard-link operation that cannot replace a competing final name. A failed partial
is retained for inspection; this is a verifiable prefix, not a multi-file
atomic transaction.

Before retrieval or model calls, the actual driver also publishes
`research-version-inputs.json`: the compiled cell, complete scenario, lock,
runtime ID and behavior source snapshots. The existing runtime catalogue records
this as a P0 input artifact consumed by `research_version_parent`.
The optional `research_version_child` consumes the parent and origin-authority
trace descriptor, as well as its own persistence event.
Its payload records filename, byte count, SHA-256, canonical-record digest and
pins for the boundary, reader, runtime, workflow, contracts, catalogue, retrieval
selection, provider recorder, public projection, runner and receipt consumer.
Before later boundary I/O, literal trace and catalogue bytes are compared with
the original in-memory prefix before a catalogue reader can reload them. Source
and file snapshots are also reread. Ancestor links and Windows junctions are
rejected before boundary reads and writes.

The Q8.6 caller binds a source-request subject and its independent origin
qualification receipt and its exact trace descriptor into the child
authorization envelope. The child descriptor has exact parent, authority and
child-persistence trace edges; the existing freeze receipt binds that exact
child subject. Neither receipt establishes scientific validity or permits child
execution. The boundary rejects malformed authorization before the freeze
callback. Freeze attempts, returned frozen receipts and callback failures are
retained. Publication or audit failure makes the live session terminal, including
the reporting-only model entry; already written bytes are retained.

Before Q8.6 returns a runtime receipt, it seals the existing catalogue and
rereads parent/child bytes. `PanelReceiptVerifier` repeats this read-only check
from independent compiled cell/scenario/task/lock data. It rejects missing, extra,
partial, changed, unsealed, wrongly parented, or receipt-unlinked outputs.
Running and needs-review states require no child; paused requires one frozen,
unstarted child. The reader reconstructs actual visible sources from the retained
provider item records and frozen source bundle, including duplicate-root and
context-budget exclusions. M6 activation alone does not establish visibility.
It checks full child schema/state, transitions, refusal ordering, descriptor
sources and parent edges, and the actual public review/final input projections.
The reader never writes, calls a provider or resumes a run.

The actual runner supplies its original in-memory runtime ID. A historical caller
can supply `expected_run_id`; without that independent anchor the reader asserts
only local run-ID consistency. This is not remote-provider authentication or a
defense against rewriting every independently retained input and executable.

Post-run verification failure cannot return success. A separate failure record
binds the attempted cell, scenario and lock without rewriting the original final
decision. The panel can count that failed attempt; this does not qualify its
partial artifacts as complete. Unwritable storage can prevent a failure marker
from being retained, in which case the returned failure remains ineligible.

The original RuntimeReceipt also anchors its trace digest. PanelReceiptVerifier
checks that digest before the input-file snapshot, so a coherent run-ID rewrite
which changes the trace cannot reuse the original receipt. A failure marker binds
the original run ID, trace digest and retained catalogue byte hash; accepting it
only accounts for an unsuccessful attempt.

Validation on 2026-09-15: the isolated repair at `59f8e6a8` passed 85 checks;
the integrated tree at `9d23e7b9` passed 47 checks, including label isolation.
Each run preserved all 754 source/document files byte-for-byte. Both include
the actual 24-cell Q8.6 controller matrix (two synthetic benchmark identities,
three variants, four module arms), failure cases and coherent-copy rejection.
The copied specimens pass catalogue and file-snapshot checks before the Q8.6
semantic consumer rejects them. These are engineering checks with synthetic
ports, not measured benchmark improvement or external provider authentication.

Original frozen sources, JUnit records, failed development checks, old-version
failure reproductions, runtime files and coherent copies are retained in
[the evidence archive](../results/modular-engineering-20260915/research-version-artifacts-r1/README.md).
