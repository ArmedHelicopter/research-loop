# Shared-session M4+M5 combination benchmark driver

`combination_benchmark_driver.py` is the first actual combination executor. It
accepts only the existing `pair:M4+M5` catalogue panel and its frozen `00`,
`10`, `01`, and `11` arms. The other 35 pairs, five triples, and full/LOO
design remain registered as planned obligations; this executor rejects them
before model I/O instead of representing a package-binding prompt as execution.

Every train cell creates one `RunSession` with five fixed model slots:
`m4_plan`, two sealed review roles, `analysis_program`, and `final_answer`.
Each arm therefore has five calls and one restricted Docker execution. M4-on
freezes its plan in `PredictionRegistry`; M5-on opens, submits, and reveals
both `ReviewEngine` roles. Their off arms retain the matched calls but create no
plan or review artifact. All four cells remain in the frozen grid regardless of
individual-cell behavior.

The final two solver calls run through `run_benchmark_solve_in_session`, so they
share the same lock, trace, execution budget, and module state. They receive a
frozen joint record containing only actual public M4/M5 artifacts or `null`.
The public record binds opaque cell identity, the task digest, and an opaque
digest of the full joint record. It includes the actual prediction plan and
review response bodies or same-shaped null values. Scenario/design identifiers,
review registry identities, and the frozen contrast coefficient remain controller trace material and
does not enter either model request. The public record contains no arm
identifier, enabled-module list, truth label, scorer result, package record, or
controller trace label. Public input metadata includes the broker-defined read-only path
`/input/<artifact_id>`.

`verify_m4_m5_combination_benchmark_cell` replays the one session trace and
reloads both module logs. It verifies the joint plan and review records from
their registries, checks that the second sealed role did not receive the first
response, and requires both solver requests to carry the same frozen joint
record. This is engineering provenance. Numerical four-arm interaction remains
the existing independent-scorer contrast path and rejects incomplete grids.
