# Controlled source acquisition

`python -m evaluation.modular.controlled_source_custodian` acquires a fixed
official CORE-Bench revision into a new private directory. It streams the
license and the fixed training artifact directly to private storage, verifies
the recorded Git blob SHA-1 and byte size, and then emits an immutable receipt
outside custody. The receipt contains only source pin, official URLs, license
and artifact SHA-256 values, fetch-event digests, record count, schema digest,
opaque family tokens, and overlap results. It cannot export task text, answers,
gold material, source code, or record identifiers.

The run is bound by
`data-source-metadata/corebench-controlled-acquisition.json` to the actual
receipt. Its artifact and family fingerprints were compared with the available
opaque SciCode/ScienceAgentBench receipt fingerprints. No available equality
was found. This only rules out equality in that limited fingerprint set; it
does not establish independent publication, dataset, or scientific provenance.

The acquisition process itself made no payload available to a solver or runtime
optimizer. It cannot establish that any model was never pretrained on, cached,
or historically exposed to a record. In this task a subsequent overbroad local
diagnostic exposed dynamic result-key text to the current agent context. The
immutable failure record is outside the repository at
`E:/_ryanDev/AI/research-loop-modular/work/corebench-controlled-acquisition-r1/exposure-failure.json`.
CORE-Bench therefore remains ineligible for an unseen-data claim in this
context, and its catalog status remains quarantine.

No public CORE-Bench adapter, private evaluator boundary, independent exposure
attestation, or calibration lease exists here. The source cannot enter a
train/validation split or an optimization/validation run. A future fresh,
independently isolated custodian must first review its full artifact lineage
and third-party terms, establish group evidence, and produce an independently
authenticated exposure attestation.
