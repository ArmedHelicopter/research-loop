# Primary packet final consumer/privacy/attempt follow-up

Date: 2026-09-15, Asia/Shanghai
Worktree: E:/_ryanDev/AI/research-loop-modular/legacy-primary-artifacts
Preceding candidate commit: bab953ad4532a44c71564d95e5f542d981f0810f
Final follow-up commit: ac230bde971cfdbc7053a183aba9160baceb6e4e
Earlier evidence is preserved unchanged in primary-packet-verification.md.

Parent review identified three missing boundaries in that candidate despite its
36 focused passing checks and one existing synthetic controller E2E pass:

1. The public failure storage record must not contain exception text. The final
   format retains stage, error_type and error:null, while the original exception
   object/text remain unchanged for the direct caller. A private-context sentinel
   test confirms no public failure file or reader report contains its text.
   Coherently rehashed attempts to insert that text are rejected.
2. The actual legacy CombinationTrainSource.export and run_q32_execution_panel
   callers also need independent consumption gates. Each now calls the same
   verify_primary_train_packets with its own custody/snapshot/item_ids/output
   root immediately after legacy export. Prospective branches are unchanged.
   Actual caller positive/negative tests wrap the real exporter, tamper and
   coherently re-seal after it returns, and prove rejection before returning a
   packet or reaching compilation/execution. No Docker or model was run.
3. An attempt UUID is now created before the first write, included in the
   reservation/packet/failure binding, and used as the catalogue run_id. Success
   readers require exact consistency. Failure storage checks its exact hex string
   format and every readable catalogue descriptor's matching run_id, including
   failures before reservation/catalogue construction completes.

The earlier failed-output tamper test overwrote a verified original directory.
The final test copies the original into an attack directory before tampering,
and re-verifies the untouched original. All six ordinary partial/seal failure
samples remain available for independent archive inspection.

## Follow-up executions, in order

No failed test execution occurred in this follow-up. Earlier failed attempts
(including the private-label-ancestor setup rejection) remain explicitly recorded
in primary-packet-verification.md and were not relabeled as passing.

- First follow-up, after consumer/privacy/original-retention repair:

  `python -m pytest tests/test_legacy_primary_packet_artifacts.py tests/test_modular_train_io.py -q -o addopts='' --basetemp E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-followup-4 -x -W ignore::DeprecationWarning`

  Session 91296 was awaited to actual completion. Exact result:
  `41 passed in 28.79s`, exit 0.

- Attempt-ID follow-up:

  Same test files/options with basetemp
  E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-final-5.

  Session 86050 was awaited to actual completion. Exact result:
  `48 passed in 26.01s`, exit 0.

- Final evidence-retention freeze:

  The synthetic mock Custody used by the focused fixtures was previously held in
  memory. The test setup now stores its actual state and typed exported identities
  in independent-custody.json before any packet producer runs. This file remains
  outside the public packet, alongside the original synthetic snapshot. It allows
  later source-aware readers to use the real original test inputs rather than
  reconstructing expected authority from a packet's own binding. Production code
  did not change in this last step.

  `python -m pytest tests/test_legacy_primary_packet_artifacts.py tests/test_modular_train_io.py -q -o addopts='' --basetemp E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-final-6 -x -W ignore::DeprecationWarning`

  Session 20943 was awaited to actual completion. Exact result:
  `48 passed in 27.54s`, exit 0. No skips. No source or test changes occurred
  during or after this run. Earlier 36/41/48 test directories were not overwritten.

- Final git diff --check: exit 0, only configured LF-to-CRLF warnings.

Final frozen SHA256 values:

- legacy_primary_packet_artifacts.py: 438f2d8fb2a66a26a27fc3729a1bd14fc2095f7f9331620df31d3986e91d42b0
- train_io.py: 1af0c6c45c0d7cba4c59d9ca7d89e822c149b3e53f701922f1a44feac461e1de
- train_controller.py: c42df94ddd9527feffa06de314b3f93d1c48d48f3ceaa05bca9a6888eaf590ce
- combination_train_source.py: 97b52eac0153c0cbf6e7e1965213e69659c267eeaf37f2c168e65598fbc95b5d
- q32_execution.py: 4fa73f051e8fa7fcbde7609038e0f0797fb41182f0a23f209ba5f7026d6ef168
- test_legacy_primary_packet_artifacts.py: 341cf6fe7716971e2834e1bfef2154a89cb4e08d2651f5c685370457967aee7b

## Retained final originals and read-only verification

Final root: E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-final-6

For tests using _setup, load the original independent-custody.json state and
DataIdentity objects, expose them through a read-only CustodyExportPort, and call
read_primary_train_sources with that test's existing snapshot and declared ITEMS.
Then use verify or inspect_failure on the existing packet directory. No producer
or fixture materialization function is needed. Tests using the actual CustodyStore
already retain their original custody.json next to the synthetic snapshot.

Archive candidates include the normal actual exporter outputs; the six original
test_partial_write_and_seal_failure.../packet directories; the intentionally
incomplete double-failure prefix; privacy and attempt-ID original failure packets;
and the positive actual controller/combination/Q32 caller samples. Attack copies
and coherently forged directories are rejection evidence, not successful outputs.

The independent custody/snapshot input must not be copied into the public artifact
packet. Archive provenance can bind its digest and explicitly synthetic origin.

## Limits

These remain offline engineering checks. All original earlier scope limits apply,
except the previously unpatched legacy combination and Q32 consumption paths are
now explicitly wired and checked. There is no model service, real data, VAL work,
Docker execution or scientific validation claim.

Before any readable catalogue exists, a storage-only failure reader can verify
the attempt ID's format and its retained manifest/seal, but cannot independently
authenticate a historical UUID against a nonexistent external reservation. A test
preserves this distinction: a coherently substituted, well-formed UUID in such an
early failure remains storage-only and can never pass the success reader.

Raw malformed primary catalogue/terminal/seal bytes remain preserved without
requiring them to equal a prior valid state. Incomplete failure storage remains
incomplete and does not yield a successful packet.
