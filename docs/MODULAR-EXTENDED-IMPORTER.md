# Extended source inventory importer

`evaluation.modular.extended_ingestion.ExtendedInventoryImporter` is a
controller-side reader for the two fixed source snapshots registered in
`research_loop.modular.source_ingestion`: SciCode and ScienceAgentBench. It
first verifies the acquisition receipt and its pinned source/revision, then
uses `CustodyStore.inventory()` for the durable manifest. It does not call
attestation, qualification, splitting, leasing, or model APIs.

The importer always writes `exposure="unknown"`. A successful download,
receipt, or inventory digest therefore does not establish process isolation,
unexposed history, data licensing, independent provenance, or eligibility for
training or validation. With no independent custody attestation,
`CustodyStore.split()` assigns these members to quarantine.

SciCode has one inventory item per official `problem_id`. Its full `sub_steps`
list is retained as one controller record and assigned one opaque group token,
so substeps cannot split across domains. The source schema establishes no
higher dataset, paper, or artifact lineage; this importer does not infer one.

For ScienceAgentBench, the task identifier and grouping values are opaque
SHA-256 tokens derived in the controller. Its minimum grouping is the root
parsed from the source formatter's first `dataset_folder_tree` line. A missing
or malformed root receives an isolated `unknown` group token. A shared folder
root is only a minimum artifact constraint; it is not evidence of a shared
paper or complete lineage, so higher grouping remains unknown and quarantined.

`ExtendedTrainProjectionExporter` accepts an exact item allowlist only after
the real `CustodyStore.export_train()` returns matching frozen identities. It
re-reads source records in the controller and emits only the two adapter
allowlists:

* SciCode: `problem_id`, `required_dependencies`, and each substep's public
  prompt, function header, return line, and optional background.
* ScienceAgentBench: task instruction, dataset tree, preview, output filename,
  and optional domain knowledge.

It never emits source record extras such as solutions, expected outputs, test
cases, annotations, gold programs, evaluator scripts, references, or private
artifact locators. The on-disk public packet is the authorized solver-facing
projection; return receipts say `payload_returned: false` only about this API,
and `access_isolation: not_verified` because it cannot prove OS isolation or
prior non-exposure.

The importer has synthetic tests only. A custodian running it against a
received snapshot must retain the controller log and receipt separately; this
module does not treat a test result or inventory creation as a scientific or
data-qualification result.
