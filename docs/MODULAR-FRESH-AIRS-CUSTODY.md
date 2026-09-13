# AIRS controlled acquisition and adapter boundary

The official Hugging Face AIRS release was acquired through controlled storage:
20 records in one 393360-byte CSV, pinned to
`d74029d593351927ba65d5a00e8ad186ab186b79`. Its content hash is
`13f3c6326154a2ce6e35c141e09efee552d10c735000d954cd67a9b50425f559`.
The strictly validated receipt is
`data-source-metadata/airsbench-hf-controlled-receipt.json`; the qualification
summary is `data-source-metadata/airsbench-hf-controlled-acquisition.json`.
There are still zero validation-eligible records. This is additional data;
it does not fill the two primary benchmarks' independent-family requirements.

The earlier GitHub attempt is preserved separately. It received the pinned
Git tree (100306 bytes), but its archive failed before receiving bytes. Bounded
follow-up GET probes for the official raw LICENSE and official Git blob LICENSE
also failed without returning contents. That GitHub task parser never ran.
`data-source-metadata/airsbench-controlled-acquisition-attempt.json` records
`blocked_github_content_fetch`; it does not imply an outage of the HF release.

The behavior is to acquire a previously unimported official AIRS repository
revision directly into a new private directory, verify every archive blob against
the pinned official Git tree, and export only a recursively validated metadata
receipt. Verification includes a synthetic archive containing private text,
code, gold markers, and nested dynamic keys; it exercises the real CLI boundary,
tampered blobs, exception/diagnostic suppression, and overlap-domain limitations.
The safety invariant is that no task content, source code, arbitrary upstream
mapping keys, parser error, or private locator enters optimizer output. The
deliverable is the custodian implementation, tests, immutable acquisition receipt,
and this minimal adapter plan. No split or validation lease is created.

The official [repository](https://github.com/facebookresearch/airs-bench) describes
20 end-to-end machine-learning research tasks and task definitions with separate
preparation, evaluation preparation, and evaluation scripts. Its
[official dataset card](https://huggingface.co/datasets/facebook/airs-bench)
describes the release as task specifications. This establishes relevance to
research-agent execution, not scientific validity or coverage of every programme
question. DiscoveryBench and BLADE remain the required primary benchmarks.

The GitHub acquisition implementation uses repository revision
`72a629ce14309ed5bcfb42ebbc944028dd4b9542`. It seals an intent before the first
network request, then streams the tree and archive into the private store.
Per-fetch start/completion events form a hash chain. Partial bytes and failed
events remain private; a failed directory cannot be reused. Archive members are
never executed, imported, or extracted as filesystem paths. The public receipt
is validated before its first write. Its schema has fixed field names, fixed
status values, bounded integer counts, SHA-256 values, and opaque tokens only.
It cannot emit a schema diagnostic or arbitrary error text.

The successful alternate command is
`evaluation.modular.fresh_airs_hf_custodian`. A metadata-only call first seals
the official API response, release pin, source-level license metadata hash,
artifact hash/size contract, and counts by fixed file types. No task filename
is exported. The payload call requires this exact revision and contract digest;
it rejects drift before receiving task content. Received bytes stream straight
into private files and must match the declared Git/LFS hash and size before
the parser runs. Its CSV path was exercised with synthetic dynamic keys and
large private fields before the actual download. No package installation was
needed. Every public success receipt is recursively allowlisted; failures have
only a fixed stage, error category, HTTP status or null, and timeout/TLS booleans.
The executable parser surface is restricted to the tested CSV and JSONL paths;
metadata may count other formats, but they are refused before payload fetching.

The existing official repository metadata declares CC BY-NC 4.0. The successful
HF API metadata independently declares `cc-by-nc-4.0`; its license value is
committed as SHA-256
`3d0827822d88798ea3dd97a2cfb4953e17d6e51fa6cea712a8b37f411bdf4dee`.
That is a hash of canonical license metadata, not a downloaded LICENSE body.
The GitHub LICENSE download did not succeed. These declarations do not settle underlying dataset,
third-party task, or redistribution terms. The actual upstream task datasets are
not acquired by this command. Per-dataset licensing and artifact pins remain
separate qualification work. PyYAML is used only with `safe_load`; the local
runtime was observed as Python 3.12 with PyYAML 6.0.3. No dependency installation
or paid model call is involved.

The received records yield 28 opaque metadata factors and 14 connected
components: eleven singleton components and components of size two, three and
four. Metadata components merge exact equalities from a predeclared set of lineage-like
fields. Their names and values remain private; only hashes and component counts
are exported. These components are not scientifically independent families.
The available legacy baseline contains source/revision/member-bound component
tokens, whose hash domains cannot establish cross-source lineage equality.
Its denominator is retained (30 source-bound component tokens, 4 artifact
fingerprints, 0 publication fingerprints), with 0 cross-source-comparable
family fingerprints. The artifact exact-hash intersection is zero over those
four available hashes only. No family-overlap conclusion follows from the
incomparable token domains. Comparable factor count is reported separately,
and publication overlap remains unknown. Artifact hash equality is only exact
byte equality over the limited available artifacts. Absence of equality does
not exclude shared data, related publications, or transformed duplicates.
DiscoveryBench/BLADE publication and artifact-lineage coverage is still missing.

The process-level statement is deliberately narrow: this acquisition exported
no payload to this optimization process. The general official documentation was
consulted before acquisition. Neither this statement nor a new directory or new
agent context proves absence of model pretraining, prior access, caches, or
historical exposure. This host's optimizer has broad filesystem tools; authenticated
OS/process isolation has not been verified. All exposure and eligibility
requirements therefore remain unresolved, with zero validation-eligible items.
No earlier SciCode, ScienceAgentBench, CORE-Bench, train, or quarantine state is
read as payload or modified. The recorded CORE-Bench exposure failure remains.

The minimum future adapter sequence is:

1. An independent custodian verifies each underlying dataset version, terms,
   artifact/publication lineage and cross-benchmark overlap, then binds the
   private manifest to authenticated access controls. Freeze whole-family
   train-only declarations before projecting any task for optimization.
2. A train projection service returns only the declared task input and permitted
   training features to the solver. Private evaluation preparation, test labels,
   evaluator scripts, and all future validation payloads remain outside the
   optimizer and solver mount. Upstream scripts must undergo separate trusted
   review before execution; this acquisition has run none of them.
3. A private evaluator binds a frozen candidate's prediction artifact to the
   exact task and approved dataset/evaluator pins, returning a constrained
   receipt. Integration checks must reject wrong task bindings, label exports,
   evaluation-code exports, network downloads and schema drift. Official metric,
   scientific validity, and any adapted score remain distinct. Validation stays
   disabled until independent family/exposure, calibration and panel-lease
   prerequisites are satisfied.

The custodian module is `evaluation.modular.fresh_airs_custodian`; its CLI requires
`--private-store`, `--output`, and `--overlap-baseline`. Both the private directory
and public receipt must be new. Do not inspect the private archive or metadata
to diagnose a future failure; only the validated public receipt may be read by
the optimizer.

The GitHub implementation and prefetch verification were committed as `4e4ee76`.
Its prefetch r3 JUnit has 11 passing tests, including the real CLI path with a
synthetic transport. The HF implementation was committed as `629d424`, with
the CSV seam verified and committed as `3d1b2eb` before receiving the task file;
the HF CSV prefetch JUnit has 12 passing tests. The initial test-only attempt had one missing fixture
directory failure, repaired before any network fetch; all original JUnit files
remain in the external evidence folder. Passing synthetic checks do not prove
an executable AIRS adapter, data independence,
or runtime/OS isolation.

The failed first acquisition is preserved at
`E:/_ryanDev/AI/research-loop-modular/work/custody-private/fresh-airs-20260913-638b4c2d`.
The two license-only GET failure event directories use the sibling names
`fresh-airs-license-network-638b4c2d` and `fresh-airs-api-license-638b4c2d`.
The optimizer may read only the external fixed-field receipts under
`E:/_ryanDev/AI/research-loop-modular/work/fresh-airs-custodian-live-r1/`.
The successful HF private root is the sibling
`fresh-airs-hf-20260913-638b4c2d`; its preceding metadata-only root is
`fresh-airs-hf-metadata-20260913-638b4c2d`. These are explicitly linked alternate
official-release attempts. They do not relabel GitHub failures as success or
certify historical non-exposure. No private payload was subsequently opened for
a schema diagnostic.
