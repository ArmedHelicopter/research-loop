# Legacy primary packet source/consumer verification

Worktree: E:/_ryanDev/AI/research-loop-modular/legacy-primary-artifacts
Starting HEAD: 3079c0864a6bca06535b2ff6ac9e3be28013df09
Date: 2026-09-15, Asia/Shanghai

## Scope and invariant

Owned files only: evaluation/modular/legacy_primary_packet_artifacts.py,
evaluation/modular/train_io.py, research_loop/modular/train_controller.py,
tests/test_legacy_primary_packet_artifacts.py. No root, live C5, scenario or
extended adapter files changed. PublicTrainPacket.packet_path was verified to be
an existing dataclass field; it was not invented or added by this repair.

The source object is independently derived from the caller-owned custody
allocation and exact snapshot metadata/CSV buffers, including inventory digest,
split version, the complete inventory row/content_hashes, allocation, selected
metadata/query and CSV byte hashes. All requested identities are checked as
TRAIN before any selected source content is read or any packet is written.
The actual controller independently re-reads those sources from its frozen
item_ids and compares packet task, receipt, public/CSV paths and sealed bytes.
It never obtains expected authority/anchor material from the same packet.

Successful packets require a fixed flat inventory, exact canonical public task
and receipt, exact source CSV bytes, exact full descriptors/parents/config/source
bindings, and a valid original catalogue/packet seal. Producer terminals do not
self-claim engineering verification. The producer runs the strict reader before
returning its successful packet.

Failures preserve their original exception object, error text/type/stage and all
actual partial bytes. Failure storage has an independent exact manifest/seal and
never overwrites/retries the partly finalized primary catalogue. Such directories
cannot pass the success reader. If failure storage itself cannot be completed,
the original exception is retained with a secondary-failure note; the directory
remains incomplete and neither reader returns a successful packet.

## Verification attempts, including failures

1. py_compile of all three changed production modules: exit 0.

2. Existing public TRAIN I/O tests:

   `python -m pytest tests/test_modular_train_io.py -q -o addopts='' --basetemp work/primary-io-1`

   Exact result: `2 passed in 1.40s`, exit 0.

3. Initial focused source/consumer suite:

   `python -m pytest tests/test_legacy_primary_packet_artifacts.py tests/test_modular_train_io.py -q -o addopts='' --basetemp work/primary-check-1 -x -W ignore::DeprecationWarning`

   Exec session 97264, awaited to completion. Exit 1.
   Exact result: `1 failed, 30 passed in 16.59s`. Three remaining cases were not
   executed because -x stopped the then 34-case suite.

   Original relevant traceback:

   ```text
   test_actual_controller_gate_precedes_compile_and_model_calls[False]
   tests/test_legacy_primary_packet_artifacts.py:235: model = model_port(tmp_path, monkeypatch)
   tests/test_modular_train_controller.py:59: candidate = audit_base_context(...)
   research_loop/modular/model_port.py:306: _require_empty_public_cwd(cwd)
   research_loop/modular/model_port.py:250:
       raise ContractError("frozen context cwd has a private label ancestor")
   E research_loop.ontology.ContractError: frozen context cwd has a private label ancestor
   ```

   Cause: the temporary public model-context fixture was inside the repository
   worktree; an ancestor contains data/labels. The existing guard rejected this
   before model execution. No labels were opened. Repair: move the test basetemp
   to E:/_ryanDev/AI/research-loop-modular/work, outside every repository and label
   ancestor. No context isolation guard was patched or bypassed. Two explicit
   Windows junction cases were also added, and the consumer's receipt type was
   tightened before the final frozen run.

4. Final focused source/consumer suite:

   `python -m pytest tests/test_legacy_primary_packet_artifacts.py tests/test_modular_train_io.py -q -o addopts='' --basetemp E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-check-2 -x -W ignore::DeprecationWarning`

   Exec session 84175, awaited to actual completion.
   Exact result: `36 passed in 20.53s`, exit 0. No skipped junction/symlink cases.
   No source/test edits occurred during or after this frozen run.

5. Existing complete actual controller synthetic end-to-end regression:

   `python -m pytest tests/test_modular_train_controller.py::test_actual_custody_export_port_runner_and_receipt_are_engineering_only -q -o addopts='' --basetemp E:/_ryanDev/AI/research-loop-modular/work/legacy-primary-controller-3 -W ignore::DeprecationWarning`

   Exec session 75938, awaited to actual completion.
   Exact result: `1 passed in 12.84s`, exit 0. This test uses the existing synthetic
   process transport, not a model service or real CLI execution. The two new
   controller-gate cases stop at compilation and assert zero model calls.

6. `git diff --check`: exit 0. Git reported its configured future LF-to-CRLF
   checkout conversion warnings, with no whitespace error.

Read-only reconnaissance initially searched a nonexistent
evaluation/modular/train_controller.py and unsupported Windows glob arguments;
rg returned errors. Bounded rg --files discovery found the actual controller at
research_loop/modular/train_controller.py. This did not constitute verification
or modify any file.

## Final verified source hashes (SHA256)

- legacy_primary_packet_artifacts.py: 3389ae78675087c27ea0eaf536e2ac5ff5e77ad57de250ad083a4c9ca8d9638f
- train_io.py: 1af0c6c45c0d7cba4c59d9ca7d89e822c149b3e53f701922f1a44feac461e1de
- train_controller.py: c42df94ddd9527feffa06de314b3f93d1c48d48f3ceaa05bca9a6888eaf590ce
- test_legacy_primary_packet_artifacts.py: d9143730aa90a3ba2641cd12531eeb4016117f46d0c89330313a29efec715543

## Limits and uncovered scope

- These are offline synthetic engineering checks. No real data, VAL evaluation,
  private label contents, Docker, network or paid/model service was used.
- CSV validation establishes exact selected source bytes and the registered
  public projection; it does not certify scientific data quality or infer a
  successful analysis from those bytes.
- The typed source boundary relies on caller-owned custody/snapshot material;
  it is not remote attestation, secret custody or OS/process isolation. Link and
  reparse checks reject observed links; concurrent hostile path replacement is
  not claimed to be prevented by this Python boundary.
- The primary consumer gate is wired and checked in train_controller.py; other
  unrelated controller families were not changed or exhaustively re-tested.
  Every call to the legacy exporter does receive producer-side strict
  verification before it returns.
- Failure storage attests retained raw bytes, including malformed primary
  catalogue/terminal/seal bytes. It does not validate successful operation
  semantics or upgrade an incomplete primary seal.
- Artifact archive integration and broader frozen root verification belong to
  the parent task. No whole-repository or scientific effectiveness claim is made.
