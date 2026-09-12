# Modular experiment registry

`research_loop.modular.experiments.registry()` contains the 48 Q1–Q8 coverage
IDs as typed `ExperimentSpec` values. Each has explicit modules, scenario kind,
variants, required mechanism endpoint, combination flag, and the requirement for
one DiscoveryBench and one BLADE receipt. It intentionally exposes interface
metadata only; combination assembly belongs to the integration owner.

`scenario()` creates an immutable, controlled public injection with same-task,
same-evidence, and same-budget controls. It cannot construct a benchmark prompt,
read labels, or turn a generic prompt into an unimplemented manipulation. Runtime
endpoints remain explicitly unimplemented until an `implementation_ref` is entered.

`ExperimentLedger` begins every row at `designed`. Measurement transitions require
a frozen scenario plus exactly both benchmark receipts, distinct task groups,
matching data domain, scenario hash, registered arms, package, scorer, and run
digests. A module score cannot populate other rows. Validation measurement is
required before an accepted/rejected/inconclusive decision; unavailable coverage
stays `blocked` with a required precise reason such as
`blocked_endpoint_unimplemented:claim_revision_context`.
