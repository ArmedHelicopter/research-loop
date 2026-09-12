# Train-only public packet export

`TrainPacketExporter.export(item_ids)` consumes an explicit nonempty allowlist
which must be a subset of `CustodyStore.export_train()`, plus the frozen
custody state. It refuses manually supplied domains, unknown identities, split
or source-group drift, unsafe relative paths, links/reparse points, and hashes
not present in frozen inventory before parsing public metadata.

Discovery packets extract only the selected public query and dataset/column
descriptors; BLADE packets extract only `research_question`, `data_desc`, and
the public CSV header. Each output directory contains one copied public CSV and
one `public.json` containing the `PublicTask` and receipt. Raw metadata,
annotations, answer keys, references, scorers, and labels are never exported.

This is a train-only engineering export. It does not create validation packets
or establish scientific benchmark performance.
