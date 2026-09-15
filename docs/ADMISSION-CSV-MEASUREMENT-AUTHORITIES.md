# Deterministic CSV measurement authorities (v2)

`research_loop.modular.csv_measurement_authorities` is an opt-in producer for
admission qualification. It accepts only public TRAIN CSV aggregates: row
count, nonempty count and exact decimal sum. Two validators may share the
same explicitly frozen CSV parent, while their `source_group` values identify
validator implementations rather than independent datasets.

A v2 receipt must bind the CSV SHA-256, measurement-spec digest and the local
validator process result. The admission consumer replays both raw receipts
before accepting ordinary signed qualification. A matching result establishes
only reproducible descriptive measurement for that CSV; it does not establish
causal validity, independent data, or scientific utility. Existing v1
material/verifiers remain unchanged.
