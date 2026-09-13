# AIRS controlled acquisition and adapter boundary

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

The acquisition uses repository revision
`72a629ce14309ed5bcfb42ebbc944028dd4b9542`. It seals an intent before the first
network request, then streams the tree and archive into the private store.
Per-fetch start/completion events form a hash chain. Partial bytes and failed
events remain private; a failed directory cannot be reused. Archive members are
never executed, imported, or extracted as filesystem paths. The public receipt
is validated before its first write. Its schema has fixed field names, fixed
status values, bounded integer counts, SHA-256 values, and opaque tokens only.
It cannot emit a schema diagnostic or arbitrary error text.

The repository declares CC BY-NC 4.0. The acquired LICENSE is hashed and its Git
blob verified. This code-level declaration does not settle underlying dataset,
third-party task, or redistribution terms. The actual upstream task datasets are
not acquired by this command. Per-dataset licensing and artifact pins remain
separate qualification work. PyYAML is used only with `safe_load`; the local
runtime was observed as Python 3.12 with PyYAML 6.0.3. No dependency installation
or paid model call is involved.

Metadata components merge exact equalities from a predeclared set of lineage-like
fields. Their names and values remain private; only hashes and component counts
are exported. These components are not scientifically independent families.
The available legacy baseline contains source/revision/member-bound component
tokens, whose hash domains cannot establish cross-source lineage equality.
Its denominator is retained, comparable factor count is reported separately,
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
