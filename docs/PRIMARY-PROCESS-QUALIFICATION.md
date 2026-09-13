# Primary observed-family process qualification

This protocol adds a metadata-only audit and a new prospective primary split.
It never modifies the original 403-item inventory, its split, its 81 training
members, any legacy `independent_clean` attestation, or an existing supplemental
split. It grants no payload reader, exporter, or validation lease.

`audit_primary_process(config)` verifies caller-pinned historical metadata and
returns opaque identities and observed family groups. `seal_primary_process`
reconstructs the audit and groups, rechecks source bytes, and writes a new audit,
split, and metadata receipt. A failed attempt retains an intent and fixed safe
failure receipt. No upstream runner is imported or executed. Source metadata,
CSV, and reference files are hashed as opaque inventory bytes, never decoded;
history parsing accesses only fixed identity, selection, cost, and pin fields.

The access scope starts at the explicitly listed initial 2026-09-12 manifests
and runner bytes, includes the fixed legacy call receipts and budget files, and
the five later solver controller/ledger pairs. Historical selection is potential
exposure; a call receipt proves attempted model I/O independently of its exit
or score. Original train membership, documented exposure, historical selection,
or an observed call forces the entire connected family to train. Absence in this
finite metadata scope does not establish absence of OS or unlogged access.

Scientific DOI, repository, dataset declaration, exact data-artifact, and legacy
family constraints reuse the archived canonical graph. Components are retained
even when their connection passes through a nonprimary source. Shared storage
containers are not added as scientific factors. Entirely unmapped components
share a fallback per primary benchmark and remain connected to all known family
constraints. Primary inventory file multisets and canonical metadata/data hash
sets and counts must match. When the complete canonical read manifest is missing,
the audit reports that gap and only claims reverified primary aggregate bindings;
it does not claim reconstruction or revalidation of all 605 graph source inputs.

The immutable seed is
`research-loop-primary-observed-family-split-20260913-v1`. Candidate connected
groups without any training exposure are stratified by the set of benchmarks in
the group (DiscoveryBench, BLADE, or both). Each stratum is sorted by raw SHA-256
of `seed:group_digest`. Its first `ceil(0.30 * group_count)` groups become sealed
validation; remaining groups become train. Known training families always stay
train. No seed search, outcome-dependent selection, task-level random splitting,
or replacement sampling is allowed. The schema is
`prospective-primary-observed-family-split-v1`; its qualification scope is bounded
process access and observed relationships, not absolute independence or model
pretraining cleanliness. The two primary endpoint obligations remain separate.

An earlier SAB pilot was discovered during this primary audit. The separate
`supplement_sab_eligibility` entry first persists an eligibility hold for every
existing SAB validation family, then checks fixed earlier identity/call metadata.
Earlier `instance_id` values are not presumed to equal received CSV ordinals.
Without a revision-bound explicit identity bridge, all 18 existing SAB validation
records stay sealed and ineligible. The original split remains byte-for-byte
unchanged; no replacement split, resampling, or lease is issued. This hold is a
deny record that any future acceptance broker must honor, not an OS access control.

Passing synthetic tests or writing these metadata receipts establishes the
implemented custody boundary only. Scientific data licensing, evaluator fitness,
artifact completeness, scientific validity, and unobserved relationships remain
separate qualifications. No paid model or network call is made by this protocol.

## Actual bounded audit and seal

The frozen implementation at `1d737b1` passed 76 checks, including the synthetic
source-to-history-to-seal seam and label isolation. Its unchanged declared input
set produced 308 train and 95 sealed records in 76 observed families. Discovery
has 294 train records in 46 groups and 94 sealed records in 15 groups. BLADE has
14 train groups/records and one sealed group/record. The original BLADE four
unknown records became three train and one sealed; one of those train records
was selected by an earlier runner and is conservatively treated as potential
exposure. The one Discovery fallback member remains train.

The first actual attempt failed on a file-classification mismatch: recursive
enumeration included one nested same-byte metadata copy that the original
canonical direct-child contract omitted. Complete inventory bytes and every
unique primary metadata/data hash already matched. A synthetic counterexample
reproduced the failure; the corrected classification retained full recursive
inventory hashing and matched the original direct-child metadata rule. The
original failed seal, diagnostic counts, RED test, and unchanged-seed retry are
preserved. Neither the archived canonical receipt nor any source was rewritten.

The scope includes 85 initial Discovery calls with 1,431,917 known tokens, 64
BLADE v2 calls with 1,493,232 known tokens, two separate BLADE v1 call receipts
with 31,752 known tokens, and 159 later solver calls with 1,743,025 known tokens.
Aggregate old budgets do not provide a per-call success/failure breakdown; these
are separate observed ledgers, not an assertion of complete historical usage.
The later task identities include two Discovery and one BLADE identity, all
already in the original train allocation. All 24 declared input hashes and the
implementation hashes matched after the successful seal.

The SAB supplement independently found 12 selected legacy identities and three
identities with three observed successful calls, using 75,272 known tokens. The
remaining nine are selection-only potential exposure. No shared revision-bound
identity bridge was established. All eight existing SAB validation groups,
containing 18 records, therefore remain on hold with zero eligible records.
Their original audit and split bytes remain unchanged. This does not claim that
each held record was exposed, and does not authorize replacement sampling.

Exact metadata-only evidence paths, raw SHA-256 values, canonical digests,
source/group counts, preserved failures, and frozen JUnit results are archived in
[`primary-process-qualification-verification.json`](primary-process-qualification-verification.json).
The original primary inventory and old 81-train allocation remain unchanged;
the new primary seal grants no payload access or validation lease.
