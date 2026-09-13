# Prospective state/retrieval engineering evidence

The exact M1×M6, M2×M6 and M3×M6 TRAIN families now have a frozen controller/compiler, a shared runtime driver and independently hosted primary scoring. M3 keeps M2 as fixed background. The source was tested at `607bfded811bdb972daa534ee594299b4e305c58`: **78 tests passed**, with zero failures, errors or skips, and all 504 tracked Python/Markdown source files unchanged. The tests used synthetic public primary-like packets, synthetic qualifier observations and a synthetic Codex transport; Docker and scorer child processes actually ran. No paid model calls or actual benchmark private references were used.

| Controller fixture | Planned / observed | Scored | Failed / blocked | Model calls | Docker / scorer calls | State + corpus qualification calls | Retrieval calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete grid | 24 / 24 | 24 | 0 / 0 | 48 | 24 / 24 | 96 | 72 |
| M1 qualification differs across arms | 24 / 24 | 24 | 0 / 0 | 48 | 24 / 24 | 96 | 72 |
| First model usage unknown | 24 / 24 | 0 | 1 / 23 | 1 | 0 / 0 | 4 | 3 |
| State qualification fails | 24 / 24 | 0 | 24 / 0 | 0 | 0 / 0 | 48 | 0 |
| Corpus qualification fails | 24 / 24 | 0 | 24 / 0 | 0 | 0 / 0 | 96 | 0 |
| Retrieval provider fails after one item | 24 / 24 | 0 | 24 / 0 | 0 | 0 / 0 | 96 | 24 |

The complete catalogue freezes before the first source/model/scorer request. Every cell has two solver slots, one Docker opportunity, two state qualifications, two corpus/query provenance qualifications, three matched retrieval opportunities and one primary scorer opportunity. All arms receive the same candidate package with exact TRAIN provenance, task/CSV binding, bounded context and budget. The scorer process accepts `state_retrieval=True` only as a strict, mutually exclusive family scope; the default remains the original M4×M5 scope.

The composite material binds `FrozenAdmissionMaterial` for M1 and `FrozenLineageMaterial` for M2/M3 to the literal original TRAIN corpus/query. Both state and retrieval change the executable computation in the same solver. Read-only replay reconstructs qualification, root/claim withdrawal and context state, compares persistent evidence/claim journals, replays per-item retrieval reservations and selection, and checks exact model instructions, request contexts, responses, literal program bytes and public inputs. Rehashed request attacks repair request/response references and receipt digests before family replay rejects them. Controller replay and execution-authority score issuance both reject persistent forgeries.

M1 qualification-semantic drift preserves all scores and makes the M1 contrast inconclusive. Source/provider failures and the poisoned model ledger preserve denominators and unused opportunities. Ten prospective source/port/root/receipt faults stop before downstream I/O. A separate driver fixture also preserves original model, invalid-analysis, provider and failed-Docker results. All reported effects remain synthetic engineering checks; primary rubric fixture numbers do not establish scientific gain, benchmark transfer or independent mechanism validity. Validation remains unopened, with no pruning or promotion.

## Frozen receipts and archive

`checks/` preserves five before/after source manifests and JUnit reports. The first driver run retained one early-failure binding regression; the second retained an invalid empty-input construction in an allocation validator. Their original failed reports and public evidence remain alongside repaired successful driver checks. The final controller check includes all driver regressions, existing state-prediction scorer-scope regressions and label isolation.

`checks.json` records test closures. `denominators.json` records each final controller case. ZIPs contain allowlisted public exports, source qualification receipts, model ledgers, controller journals, scorer client/worker receipts and literal runtime programs/journals. `archive-members.json` binds each ZIP member by size and SHA256; `archive-integrity.json` hashes every archive artifact. Private scorer stores, raw source snapshots, server configurations, authority key files and private sentinel bodies are excluded. Original absolute paths are historical bindings; run the tests for fresh executable fixtures rather than relocating journals and treating them as new runs.

Reproduce the final scope from a clean checkout using the supplied frozen runner, a fresh absolute output prefix and the image `research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349`:

```powershell
& E:/_ryanDev/AI/research-loop-modular/work/custody-root-venv/Scripts/python.exe E:/_ryanDev/AI/research-loop-modular/work/run_frozen_useful_checks.py E:/_ryanDev/AI/research-loop-modular/state-retrieval-combos E:/_ryanDev/AI/research-loop-modular/work/state-retrieval-new-check tests/test_state_retrieval_train_controller.py tests/test_state_retrieval_combination_driver.py tests/test_state_prediction_scorer_process.py tests/test_label_isolation.py
```
