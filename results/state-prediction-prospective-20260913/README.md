# Prospective state prediction engineering evidence

The bounded M1×M4, M2×M4 and M3×M4 TRAIN integration is exercised on two synthetic primary benchmark tasks. M3 keeps M2 enabled in all four cells. All 24 registered cells use primary prospective custody, the actual `CodexModelPort` with a fixture process runner, a pinned Docker execution, and an independent stdio scorer worker. The legacy fixture files are made unusable before execution and the legacy export method is forbidden.

Tested source: `1cfee61e33b70de8ec15f095ae9351affb27dfe3`. The frozen run passed **45 tests**, with no failures, errors or skips; all 498 tracked Python/Markdown source files remained unchanged. Closure time: 175.797 seconds. The JUnit SHA256 is `099e29660c88d77b554ef15e69c2e37d30776ea3906e9ee9d79963f895338ab8`.

| Fixture | Planned rows | Scored | Failed / blocked | Model calls | Docker / scorer calls | Source calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete grid | 24 | 24 | 0 / 0 | 72 | 24 / 24 | 48 |
| M1 qualification differs between arms | 24 | 24 | 0 / 0 | 72 | 24 / 24 | 48 |
| M1 source outage | 24 | 16 | 8 / 0 | 48 | 16 / 16 | 48 |
| First model call has unknown usage | 24 | 0 | 1 / 23 | 1 | 0 / 0 | 2 |

The complete grid freezes all three panels before the first model response, consumes the actual transitioned state and proposal in solver context, and records three model slots, one Docker attempt and one scorer call per cell. Two source authorities reserve and record each qualification opportunity. The Docker image is `research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349`.

M1 qualification drift retains all 24 scores and makes its contrast inconclusive. Source outages and unknown model usage retain every planned row and unused opportunity; no cells are pruned. Ten source/configuration/receipt faults stop before model, Docker or scoring calls. Eleven replay attacks cover original proposals, public context, actual model responses, solver joint context, module selection, literal programs, prediction/evidence/claim journals and event ordering. All are rejected by both replay and score issuance across the three pairs and both M4-off/on cells. The original evidence is restored and successfully replayed after every mutation.

Two initial failures are retained. The first run encountered Windows `WinError 5` replacing the controller journal after 27 fixture model calls; concurrent read-sharing interference was plausible but not established. The second run exposed an incorrect fixture assumption that the first model call must occur in cell zero. After eight intended source failures that assertion poisoned the model ledger: all nine failed and fifteen blocked rows remain in its receipt. The repaired fixture checks cells after the actual running cell.

`checks/` contains every frozen source manifest, closure and JUnit report. `summary.json` records observed counts. `complete-grid/` preserves public task exports, controller/scorer receipts and the original public runtime journals/programs. Other case directories retain denominator and process receipts. `archive-integrity.json` hashes the archived evidence. Git attributes preserve literal file bytes. Authority keys, private scorer stores and server configurations are excluded; private sentinel bodies are absent from the archive. Original absolute paths remain as historical bindings, so use the tests to create fresh executable fixtures.

Reproduction from a clean committed source, with the pinned Docker image available:

```powershell
python -m pytest tests/test_label_isolation.py tests/test_state_prediction_train_controller.py tests/test_state_prediction_scorer_process.py tests/test_state_prediction_combination_driver.py --basetemp E:/path/to/unused-state-prediction-run -q
```

This is synthetic engineering evidence. The model responses are scripted and the independent scorer uses fixed synthetic rubric outputs. There are zero paid model calls, no real private reference bodies and no validation access. Estimated fixture contrasts establish arithmetic and custody wiring only; scientific effectiveness, production readiness and model quality are not established.
