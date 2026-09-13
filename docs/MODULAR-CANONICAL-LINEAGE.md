# Canonical lineage custody audit, 2026-09-13

The audit binds 605 received records from DiscoveryBench (388), BLADE (15),
SciCode (80), ScienceAgentBench (102), and AIRS-Bench (20). It rebuilds a shared
typed fingerprint namespace instead of comparing the previous 30 source-bound
family tokens. DiscoveryBench and BLADE remain the primary benchmarks.

Only declared source, dataset, publication, and received observation-artifact
metadata is extracted by the custodian. No upstream code is executed. Raw
metadata strings, dynamic keys, task text, and reference answers are not exported.
Every read file is checked again at completion: 1,502 files remained unchanged.
This is a claim about this audit's output, not about model pretraining, historical
exposure, or verified OS access isolation.

| Source | Records with comparable references | Unique comparable references | Received observation data coverage |
| --- | ---: | --- | ---: |
| DiscoveryBench | 387 / 388 | 396 exact-byte artifact fingerprints | 387 / 388 |
| BLADE | 15 / 15 | 15 exact-byte artifact fingerprints | 15 / 15 |
| SciCode | 0 / 80 | 0 | 0 / 80 |
| ScienceAgentBench | 99 / 102 | 29 GitHub repository fingerprints | 0 / 102 |
| AIRS-Bench | 0 / 20 | 0 globally comparable references | 0 / 20 |

Full release containers are integrity evidence, not observation-data identities.
Repository equality conservatively connects records; it does not establish that
their datasets are identical. No DOI/publication identifiers were recovered by
the fixed metadata rules. There are no observed cross-source equalities, but
coverage gaps prevent a no-overlap or scientific-independence conclusion.

A separate source-and-pin-scoped dataset declaration relation preserves AIRS's
20 records in 14 conservative components: eleven singletons and groups of 2, 3,
and 4. Its hashes cannot match across sources. The complete graph has 202
components after existing primary group constraints and exact shared references
are closed transitively. These are supported grouping constraints, not validated
independent scientific families. Established independent families and validation
eligible records remain zero; no split, custody status, or validation lease changed.

Discovery's upstream revision is unknown; inventory digest and exact content
hashes still bind the local snapshot. Eighty Discovery metadata files contain
non-UTF8 bytes: surrogate escape preserves the JSON structure and original bytes,
while non-ASCII identifiers remain unmapped. No encoding was guessed. One
Discovery record lacks a received observation artifact. SciCode and three SAB
records lack comparable references under these rules.

Source-level license declarations are separately hashed. None establishes
per-record or upstream-dataset license qualification; all five remain unresolved
at that level. In particular, AIRS's source CC BY-NC declaration is not a license
approval for each referenced dataset.

Before independence can be considered, each opaque AIRS group needs an
authoritative provider-and-dataset mapping, origin/publication and derivative
relationships, received artifact hashes with version/scope, and dataset-level
terms. The machine supplement request binds each group and its members. An
unambiguous static reference in an already received preparation script can add
provider metadata; it does not establish artifact availability, licensing,
independence, or fresh validation eligibility.

The first audit failed at primary metadata decoding; its fixed failure receipt
is retained. r2 established the baseline, r3 tested structured reference fields,
and r4 added the explicitly separate local declaration layer. These are parsing
revisions, not newly acquired or newly unexposed datasets. The attempt manifest
binds all four retained outcomes and the sealed r4 public receipt.

Verification uses the independent `work/custody-root-venv/Scripts/python.exe`
environment with pytest 8.4.2 and PyYAML 6.0.3. Dependencies were copied from local
distributions with per-file hashes; original wheel provenance is unavailable.
The earlier AIRS 28-pass run used global pytest 7.2.2 and an undeclared PyYAML
dependency; that evidence is preserved with this limitation. Project dependency
declarations are handled separately by the integration owner. Lineage's latest
synthetic suite passed 23 tests before r4, including dynamic-key/exception
suppression, five-source ingestion, frozen-byte tampering, normalization gaps,
and cross-source exclusion of local labels.
