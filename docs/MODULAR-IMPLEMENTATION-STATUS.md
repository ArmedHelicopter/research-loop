# Modular implementation ledger

Goal: implement all 48 research scenarios, M1–M9 including the separate meta-program
stage, and C1–C5 combination experiments defined in the design documents.

## Working state

- Integration branch: `codex/modular-integration`, based on `dfaebe554d8bae0191ece2251a812682054a2169`.
- The existing study protocols, results, production pause, and historical worktrees remain intact.
- Shared interface v1: `research_loop/modular/contracts.py` provides immutable JSON records,
  explicit task/source/split identity, public task envelopes and strict primitive validation.
- Modules import these contracts; evaluation and benchmark adapters own their respective schemas.
- Wave 1: custody/splitting, benchmark adapters/execution, M1–M3 research state and memory.
- Root: coverage/compatibility manifests, combination panels, integration CLI and verification.

## Completion evidence

No new module or scientific experiment is complete yet. Engineering results, training
measurements, independent validation, and deployment qualification are tracked separately.
Insufficient BLADE source groups cannot be replaced by repeated samples or renamed tasks.
Docker engine was unavailable at initial inspection; generated code execution is blocked
until the restricted execution backend is running and its boundary is verified.
