# Primary validation custody and acceptance

`evaluation.modular.primary_validation_custody.PrimaryValidationCustodian` bridges
the prospective DiscoveryBench/BLADE allocation into the existing generic
`CustodyStore` and `PanelReceiptVerifier` acceptance chain. It has no TRAIN export
or optimizer callback. It does not open the current held-out family by itself.

The independent custodian supplies the original sealed split/audit, plus a signed
`primary-validation-qualification-v1` record over their exact digests, input
bindings, source byte pins, and source/exposure/relationship evidence digests.
Its scope is `recorded_primary_split_provenance_exposure_v1`. This asserts only
the independently reviewed recorded facts, not global model-pretraining or OS
history cleanliness. The original `independence_proven=False` flags remain
unchanged. The adapter neither issues a qualification nor invents attestations.
It creates a separate deterministic opaque custody projection whose digest binds
the original split, audit, and new qualification as parents.

A separately signed `primary-validation-train-freeze-v1` receipt must bind the
actual candidate, configuration, rubric, TRAIN selection rule and complete TRAIN
receipt commitment, scorer, protocol, criteria, packages, and final panel design.
The final panel must contain only qualified validation members and both primary
benchmarks. An externally calibrated scorer remains required by the existing
generic custody API; this adapter does not create calibration evidence.

`lease` calls the existing `lease_panel`. `run` consumes that one-use lease before
calling the custodian's source provider. The real primary public projection strips
reference fields and verifies metadata/CSV byte pins and each frozen task digest.
Only the private evaluator receives task buffers. Its typed runtime, scorer and
signed acceptance receipts pass through the existing generic verifier. Failed or
incomplete attempts remain consumed, with a private failure record and retained
evidence; they cannot be retried as the same observation opportunity.

The only returned artifact is `primary-validation-aggregate-v1`: acceptance
decision, complete observed/failure/unscored/blocked counts and commitments. It
contains no task token, public question, reference, trace path, per-item score, or
optimization suggestion. `optimization_feedback_permitted` is always false.
`replay` re-reads original input evidence, custody state, sources and trace bytes,
then re-verifies the signed scorer/acceptance chain without invoking sources or
models again. Retained traces must remain available at their private pinned paths.

Trust keys, private filesystem permissions, provider authentication and actual
process/container isolation are deployment configuration. The unit integration
uses synthetic source fixtures and configured fixture authorities, real public
projection, real generic leases, hash-chained runtime journals and signatures.
It establishes that boundary's engineering behavior, not a scientific benefit,
current data qualification, scorer calibration, or OS isolation.
