# Q2.4 and Q2.5 signed-audit fixtures

`run_audit_scenario()` uses an already prepared public DiscoveryBench or BLADE task, frozen fixture controls, an injected engineering-only `DockerExecutionBroker`, and the actual `RunSession.execute`, `AuditAuthority`, `AuditVerifier`, `admit`, `invoke`, and `finish` ports. Each run executes one public fixture program and one engineering callback, regardless of admission outcome. The trace and denominator therefore retain failed preconditions as one scheduled, executed, model-called, finalized fixture run.

| Experiment | Variants | Expected engineering gate behavior |
| --- | --- | --- |
| Q2.4 | `one_fail`, `both_fail`, `disagree` | A failed or inconsistent pair cannot produce a proceed decision. |
| Q2.4 | `same_wrong` | Both authentic signed audits agree and the gate proceeds. Controller-only fixture truth marks this as an observed false admission: signatures authenticate issuers and agreement, not scientific truth. It is never placed in the model payload. |
| Q2.5 | `invalid_positive`, `invalid_negative` | Invalid evidence is blocked symmetrically for both polarities. |
| Q2.5 | `valid_negative` | A valid refuting observation can reach `closed_negative`. |

These runs are offline engineering fixtures. The broker callback is fake, the public CSV is synthetic, and all records say `fixture_only`. They do not measure either benchmark, establish a scientific effect, or provide a solver with labels, gold outputs, or the controller-only `same_wrong` fact.
