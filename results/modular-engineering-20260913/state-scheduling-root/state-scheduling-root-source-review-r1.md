# State/scheduling root source review

Reviewed source: `7ddf8d0` in `state-scheduling-combos`; review is read-only while
the agent's final frozen tests run. This is not a new execution closure.

The three exact M1/M2/M3 x M8 designs share the unchanged FIFO phase and solver.
The conditional design fixes M2 behind M3 and does not enable M7. Selection
therefore uses the same two literal jobs and two cost units in all arms. M8
changes lease/snapshot/barrier execution through the actual scheduler; worker
threads own separate bounded Docker executions. Public solver context contains
the reconstructed state and phase outputs, with both inputs reconstructed for
score issuance.

The prospective controller checks all task/CSV/material bindings and compiles
all 24 denominators before source/model/scorer dispatch. Failed and blocked rows
remain present. M1 qualification drift blocks its contrast even if every row
was scored. Unknown model usage prevents subsequent model calls; auxiliary
unknown attempts and unknown scorer usage are separately retained.

Family replay binds original source qualification, state journals, original
literal programs, selection, SQLite scheduler state, lease and merge order,
phase output, request schemas/instructions, solver files and complete bounded
Docker argv/mounts. Independent primary score issuance requires this replay;
the process client uses an explicit mutually exclusive family scope.

No concrete blocking source defect was found in this review. Its limits are
selected adversarial cases, trusted local filesystem/authority ownership, and
scripted solver and rubric outputs. Host dispatch interval overlap alone is
not proof of simultaneous container computation; the agent's separate
container-timestamp case is pending at review time. Neither timing fixture
demonstrates throughput on real scientific workloads or an efficacy gain.
