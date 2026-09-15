# P0 custody transition retention checks

The opt-in custody writer retains exact private snapshots after durable operations and signed receipt creation.
Capture failure is reported separately and does not falsify an already completed custody operation.
Independent replay checks state and receipt bindings, ordering, source bytes and caller-held tail anchors.

Three separate frozen generations are preserved: r3 has 20 passing tests; r4 has 10 after the
global-order and mutator-source repairs; ROOT has 17 including label isolation. r3 is not credited with r4 repairs.
The r1/r2 historical attempts have raw files and their original reports, but no original native start/join;
their process completion and in-flight source identity are not inferred from the later runs.

Private snapshots and test-run originals remain outside public packet and optimizer roots. Only source,
test reports and retention metadata are published here. This is synthetic engineering evidence, not
complete custody history, external authority authentication, operating-system isolation, or scientific validation.
