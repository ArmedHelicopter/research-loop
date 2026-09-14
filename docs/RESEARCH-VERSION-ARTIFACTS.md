# Q8.6 research-version artefacts

Q8.6 publishes a parent goal lock and, only after caller-owned independent
authorization, an optional frozen child. Each file is first written to a
sidecar-local `.partial` file, fsynced, then published through an exclusive
hard-link operation that cannot replace a competing final name. A failed partial
is retained for inspection; this is a verifiable prefix, not a multi-file
atomic transaction.

The existing runtime catalogue records the two files as `research_version_parent`
and `research_version_child`; the child has the exact parent descriptor edge.
Its payload records filename, byte count, SHA-256, canonical-record digest and
pins for the boundary, runtime, workflow, contracts and Q8.6 driver sources.
Those pins and the catalogue are reread before later boundary I/O. This is not a
generic second journal.

The Q8.6 caller binds a source-request subject and its independent origin
qualification receipt and its exact trace descriptor into the child
authorization envelope. The child descriptor has exact parent, authority and
child-persistence trace edges; the existing freeze receipt binds that exact
child subject. Neither receipt establishes scientific validity or permits child
execution.

Before Q8.6 returns a runtime receipt, it seals the existing catalogue and
rereads parent/child bytes. `PanelReceiptVerifier` repeats this read-only check
from independent expected cell/task/lock data. It rejects missing, extra,
partial, changed, unsealed, wrongly parented, or receipt-unlinked outputs.
Running and needs-review states require no child; paused requires one frozen,
unstarted child. The reader never writes or resumes a run.
