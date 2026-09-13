# Train-only projection from the prospective partition

`ProspectiveTrainExporter` consumes a broker-owned process configuration and
sealed partition pinned by both expected partition and audit digests. The caller
supplies an exact list of `TrainExportItem(source, token, group_sha256,
source_receipt_digest)`. A caller cannot switch a token's source, group, receipt,
or domain. Validation tokens and duplicate/unknown identities are rejected from
sealed metadata before reading source snapshots or invoking a projection adapter.

The broker recomputes the original bounded process audit, preserving its original
end boundary, and requires all observations and input pins to match. It checks
the original acquisition receipts against every private snapshot artifact's
fixed byte count and Git/LFS/SHA binding. It then hashes the exact byte buffers
used to select the requested records and rechecks original pins before writing.
The 182-record denominator and frozen group allocation remain unchanged.

The public projection functions in `extended_ingestion.py` are shared with the
legacy exporter and call the existing SciCode/SAB adapters. JSONL records outside
the exact allowlist are counted without JSON decoding. CSV framing must be
consumed to locate records, but unselected rows are not mapped to field names or
projected. Selected SAB rows map only the existing public field allowlist. No
validation task field is inspected by a projection function. Hashing an opaque
snapshot container is not a projection of its validation contents.

Every call first appends and fsyncs a reservation to `exports.jsonl`. Each task's
possible exposure is reserved before its first materialized byte. Events carry
sequence, previous hash, self hash, seal binding, request digest, fixed phase,
opaque exposure tokens, and source receipt digests. This exporter has no network
or model interface, so its own model calls and known model cost are zero; this
does not reset historical provider usage. Exceptions contain no raw source
values. Failures retain the previous reservation, phase, and possibly exposed
tokens. Failed staging files are retained. An inability to append the failure
leaves the earlier reservation visibly incomplete and stops the call.

All tasks and adapters must prepare successfully before staging begins. The
complete staged directory is atomically published to an unused output root.
Outputs cannot overlap the original private snapshots, sealed validation
directory, or audit store. Existing outputs are not overwritten. The exporter
returns typed train `PublicTask`s and a metadata receipt; the actual invocation
tool emits only counts, hashes, and the caller-owned public output path.

The first fixed four-item export exposed two adapter-shape gaps before any task
was materialized: SciCode uses empty strings for some optional backgrounds, and
SAB declares safe nested relative output paths. Empty optional SciCode background
is now represented as missing (`None`). SAB preserves a canonical relative POSIX
output path without stripping directory components. Absolute paths, traversal,
drive/colon syntax, backslashes, control characters, repeated separators, dot
components, and trailing separators remain rejected. These shape repairs do not
alter the selected token list or any source snapshot, process audit, or split.

The new exporter does not call or alter `CustodyStore`, create a legacy clean
attestation, grant a validation lease, or provide a validation export API. These
projections establish only that selected public train tasks were exported.
Upstream scientific datasets, execution dependencies, evaluator contracts, and
artifact-specific licenses remain separate requirements. No runnable benchmark
or scientific qualification is claimed by a successful export.

The actual request is frozen to the lexicographically first two **train** tokens
from each source, four records total, before any task projection. Selection uses
only the sealed allocation and never task text or export outcomes. Failed first
attempts and all test reports remain in the verification archive.
