# Linked scorer process

`evaluation.modular.scorer_process` provides a train-only stdio boundary for
linked adapted scoring.  The trusted server configuration contains the full
serialized `FrozenPanel` and its digest, the frozen scorer config, pinned train
reference-store manifest, identity-to-handle map, execution-key files,
scorer-key file, and reviewed evaluator-model configuration.  The production
entry point constructs `CodexEvaluatorModelPort`.  The canned evaluator lives
under `tests/helpers/` and is not imported by the production module.

The client sends an exact declared `cell_key` and one signed linked input.  It
receives only a bound `ScientificScorerReceipt`; references, prompts, keys, and
exception text are not sent over stdout or written to the client journal.
Before evaluator use, the worker reconstructs the typed panel, verifies its
digest, checks train identities, scorer bindings, store manifest and every
configured identity-to-handle reference binding.

Both client and worker append and fsync a per-cell reservation.  A completed
identical request can return its saved receipt.  A different request for that
cell, or an interrupted/unknown reservation, is refused rather than retried.
This keeps scoring bounded and avoids silently double-scoring an interrupted
cell.  It is process wiring only; the existing HMAC authorities remain
configured components and this code does not claim OS-user isolation,
asymmetric trust, calibration, or scientific validity.

The worker command requires an absolute `--config`, its exact
`--config-sha256`, and an absolute `--journal`; it refuses a replaced
configuration before loading keys or references.  `LinkedScorerProcessClient`
accepts the same reviewed environment mapping used to start the worker and
does not record it.  Its bounded response wait defaults to 240 seconds; a
timeout or lost pipe records an unknown reservation, terminates and reaps that
worker, and never retries the cell.
