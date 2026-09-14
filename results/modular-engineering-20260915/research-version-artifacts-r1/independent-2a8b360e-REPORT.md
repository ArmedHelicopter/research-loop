# Independent 2a8b360e provenance reproduction

Probe: `probe.py`; output: `results.json`. It imports the preserved worker at
`E:\_ryanDev\AI\research-loop-modular\research-version-artifacts` and asserts
its HEAD before operating only below this directory.

Baseline frozen evidence `q86-frozen-r4-closed.json` is commit `2a8b360e`, exit
0, eight passing tests, unchanged source, and zero paid calls.

## Reproduced failures

1. `pause_and_freeze` accepts a frozen authorization with schema
`anything-goes`, unrelated subject/receipt, and a valid prior artifact hash.
The independent freezer receives the malformed authorization in its subject;
child bytes persist and the boundary becomes `paused`. The production consumer
would later reject it, but producer publication already occurred.
2. A failure while recording `research_version_child_persisted` occurs after
child publication. It leaves a parent and child on disk, `child_memory=true`,
state `running`, `terminal=false`; `assert_immutable()` succeeds, so the
in-memory boundary is still usable despite the untraced child.
3. A catalogue append failure during parent registration leaves the parent on
disk with a nonterminal session; construction raises, so no boundary object is
returned, but the partial output survives.
4. On this host `Path.is_junction` exists, while 2a8b360e does not call it.
Its stat-based check can follow a junction target before inspecting attributes.
No real junction was created: Windows link creation would alter host state and
is unnecessary to establish the missing API guard.

## Not constructed

A fully coherent, rehashed rewrite of trace/catalogue/event descriptors was not
implemented. Such a reproduction needs deterministic reconstruction of all
artifact-catalogue descriptors and runtime trace sequences from a copied
sidecar; the frozen suite’s catalogue also validates live producer source pins.
Likewise, rewrites of child schema/state, conflict transition fields, origin
visible IDs/source bundle/receipt, catalogue run ID/producer source, and
reordered refusal events were not individually exercised with every mechanical
hash remapped. The semantic gaps above are independently reproducible and do
not depend on stale checksums.
