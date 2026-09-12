# Extended source inventory importer

`evaluation.modular.extended_ingestion.ExtendedInventoryImporter` is a
controller-side reader for the two fixed source snapshots registered in
`research_loop.modular.source_ingestion`: SciCode and ScienceAgentBench. It
first verifies the exact seven-field acquisition artifact receipt
(`source_path`, size, Git SHA-1 and its kind, LFS SHA-256, local SHA-256 and
its kind), static source/revision, artifact list, file size, and fixed
Git-blob SHA-1 (non-LFS) or LFS SHA-256 (LFS payload). It rejects
symlink/reparse roots and every path segment, then
uses `CustodyStore.inventory()` for the durable manifest. It does not call
attestation, qualification, splitting, leasing, or model APIs.

The importer only accepts a new empty `CustodyStore`: an existing inventory is
immutable and is never deduplicated, appended to, or overwritten. Its receipt
records `parent_inventory_digest: null` and the resulting inventory digest.
In particular, a live custody manifest must remain separate until an explicit
merge protocol exists.

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
projection. Projection receipts distinguish that a public projection was
written and returned from the fact that `raw_private_payload_returned` is
false; `access_isolation: not_verified` remains because the module cannot
prove OS isolation or prior non-exposure.

The importer also ran against the two actual pinned snapshots on 2026-09-13,
creating 80 SciCode and 102 ScienceAgentBench inventory items. All remain
unknown-exposure and unsplit; no raw private payload was returned to the model.
The original custody state remained byte-identical. Acquisition receipts and the
metadata-only import summary are retained in
`results/modular-engineering-20260912/live-training-20260913/extended-sources/`.
An initial reporting-script field-name error occurred after successful import;
the summary was recovered from existing metadata without repeating the import.
Neither a test result nor inventory creation is a scientific or qualification
result. See [MODULAR-CHECKPOINT-20260913.md](MODULAR-CHECKPOINT-20260913.md).
