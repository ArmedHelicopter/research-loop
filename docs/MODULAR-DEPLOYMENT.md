# M9 modular deployment boundary

`FileDeploymentPort` persists a complete immutable `CandidatePackage` and the
derived memory view in one canonical state file.  A cross-process directory
lock covers initialization and the full read/compare/archive/write activation
transaction, so two callers using the same expected active digest cannot both
activate.  It writes a SHA-256 companion file after fsyncing temporary files,
then atomically replaces the state file and its hash.  `current()` recomputes
the real file hash and reconstructs the package, so a torn write, edit, missing
companion file, package digest mismatch, or memory-view mismatch reports offline
and blocks execution.

Before replacing a valid active state, the port stores the prior complete,
hash-verified snapshot as `*.previous` plus its hash.  `previous()` is
read-only; it exists for an authorized operator or signed rollback workflow to
inspect.  The port never auto-restores it.  A lock left by a crashed process or
an incomplete/tampered state requires explicit operator recovery after the
process and artifact provenance are checked; initialization never resets it to
the supplied initial package.

`ExecutionRuntime` remains the authority for activation.  It accepts only an
independently signed validation receipt bound to the candidate and expected
active digest, consumes that receipt once, invokes the deployment port, and
checks the returned package and memory digests.  Rollback is separately signed,
single-use, and limited to the active package's direct parent.

`ModularWorkflow.m9_policy()` activates only when M9 is enabled and the
candidate digest equals the frozen `RunSession` package digest.  Its common
`invoke_model()` wrapper verifies the deployed package before every M4, M5,
M6, or final model call and adds a frozen deployment payload containing only
the package's allowlisted prompt, memory, and config changes.  The run's locked
objective, slots, and execution allocation are never rewritten.  Supported
config fields have explicit model-request effects: `max_steps` and
`revision_limit` are supplied as limits, and `temperature` is supplied as a
sampling parameter.  Values outside the allowlist are rejected when the
candidate package is constructed.

This fixture-level seam contains no model, network, scorer, validation input,
or scientific-performance claim.  Passing its tests demonstrates deployment
wiring only.
