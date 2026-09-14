# Scenario semantic reader verification evidence

Recorded: 2026-09-15T00:19:49+08:00
Worktree: E:/_ryanDev/AI/research-loop-modular/grok-headless-transport
Starting HEAD: 59cfae45a96fddddc3adec2be5a1fc35203a8821
Scope: research_loop/modular/scenario_artifacts.py and tests/test_scenario_artifacts.py only.
All executions were offline synthetic fixture tests. No model, Docker, real dataset,
network request or actual validation evaluation was run. The producer fixtures do
exercise their real local runtime/deployment interfaces; the readers do not replay
those producers or activate a runtime. The result is engineering evidence only.

## Attempts, including failures

1. `python -m pytest tests/test_scenario_artifacts.py tests/test_modular_improvement_scenarios.py -q --basetemp work/scenario-semantic-tests`
   Exit 1. The work parent directory was absent. 49 tmp_path-dependent cases had
   setup errors; the registry-only test passed. Representative original output:

   ```text
   self = WindowsPath('E:/_ryanDev/AI/research-loop-modular/grok-headless-transport/work/scenario-semantic-tests')
   os.mkdir(self, mode)
   FileNotFoundError: [WinError 3]
   ```

   Repair: create this worktree's work directory. No application change for this
   environment failure.

2. Same two files, `--basetemp work/scenario-semantic-tests-2 -x`.
   Exit 1, first test failed, remaining cases not run. A patch had inserted
   `files = _files(root)` into `_expected_requests`, where root is undefined.

   ```text
   research_loop/modular/scenario_artifacts.py:247: NameError
   NameError: name 'root' is not defined
   FAILED tests/test_scenario_artifacts.py::test_actual_offline_scenario_outputs_are_sealed_and_read_without_rerun[Q6.1-self_activate-sidecars0]
   !!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!
   ```

   Repair: move that inventory read into `_semantic_files`.

3. Same two files, `--basetemp work/scenario-semantic-tests-3 -x`.
   All 50 then-existing tests completed, exit 0. Exec session 50876 was awaited
   to actual completion using write_stdin. This is the baseline verification,
   not the final adversarial verification.

4. First extended suite, `--basetemp work/scenario-semantic-tests-4 -x`.
   Exit 1. 21 tests passed before the first new runtime-tampering test failed
   inside the test's reseal helper. The 86-case suite stopped there; 64 cases
   were not run. These counts follow the emitted dots and collection order;
   the configured quiet pytest output did not print a numeric summary.
   Relevant original output retained from exec session 61497:

   ```text
   _ test_rehashed_runtime_state_cannot_change_registered_operation[receipt_missing] _
   tests/test_scenario_artifacts.py:234: in test_rehashed_runtime_state_cannot_change_registered_operation
       _reseal(root)
   tests/test_scenario_artifacts.py:203: in _reseal
       ArtifactCatalogue(path, identity=DataIdentity.parse(first["identity"]), **first["binding"],
   research_loop/modular/artifact_catalogue.py:26: in __init__
       self.verify()
   research_loop/modular/artifact_catalogue.py:145: in verify
       raise ContractError('catalogue seal does not bind current journal')
   E research_loop.ontology.ContractError: catalogue seal does not bind current journal
   FAILED tests/test_scenario_artifacts.py::test_rehashed_runtime_state_cannot_change_registered_operation[receipt_missing]
   !!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!
   ```

   Reason: the test helper used Path.write_text with a newline, which Windows
   translated to CRLF; the existing strict catalogue seal expects canonical LF
   bytes. The semantic reader had not been reached. Repair: `_write_record`
   writes explicitly encoded bytes. The helper now independently verifies the
   real catalogue seal before each semantic rejection assertion. This failed
   attempt is not counted as a passing adversarial test.

5. Final frozen run:

   ```text
   python -m pytest tests/test_scenario_artifacts.py tests/test_modular_improvement_scenarios.py -q --basetemp work/scenario-semantic-tests-5 -x -W ignore::DeprecationWarning
   ```

   Exec session 38336, awaited with write_stdin through actual completion.
   Exit code: 0. All 90 tests passed; no source/test edits occurred during this
   run. Output reached [80%], then [100%] without any failure/error section.
   Exact final tool completion output:

   ```text
   .                                                       [100%]
   ```

   The configured quiet pytest output suppresses numeric summaries. Independent
   collection using `--collect-only -q -o addopts='' -W ignore::DeprecationWarning`
   returned exactly `90 tests collected in 0.04s`. The complete run emitted 90
   passing dots. Earlier yielded output was continuation, not timeout/failure.

## Frozen files and final checks

- scenario_artifacts.py SHA256: 0ec1759ed1d173d44e0477c83f7819b1ed58c63ac2cae62eb9c26f2bf5ebe49e
- test_scenario_artifacts.py SHA256: 571416f1802802e9f83ea5f76065fb97120638604a29c2e5058110cfb1541362
- `git diff --check`: exit 0; Git warned about configured future LF-to-CRLF
  checkout conversion, without reporting whitespace errors.
- Only the two owned source/test files are staged for the delivery commit.

The 40 added cases include all remaining non-Q6.3 variant readers, coherently
rehashed runtime receipt/package/state tampering, full deployment package/memory
pairs, exact result flags and metadata, omitted descriptors, malformed callback
outcomes and failed blob inventories, coherent optimizer/result candidate
substitution, coherent baseline/result/runtime/deployment substitution, and
same-count shadow receipt substitution. Previously retained malformed failed
SQLite bytes remain inspectable as storage only.
