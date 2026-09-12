# M1--M3 evidence, claims, and context

This implementation supplies runtime-callable, provenance-bound M1--M3 modules.
It is engineering infrastructure for the registered scenarios; it does not claim
that any of the 48 research experiments or external benchmark evaluations ran.

`ScientificState` keeps validity, claim support, novelty, and investment separate.
`EvidenceAdmission.decide` accepts explicit host validation facts and a complete
literal-boolean audit checklist. Positive and qualified-negative observations have
the same admission gate. `ExplorationPolicy.admit` is intentionally separate: a
safe, budgeted unknown may be explored without becoming admitted evidence.

`EvidenceLedger(identity, storage_path=...)` writes canonical append-only JSONL
events for immutable evidence representations and withdrawals. A raw observation,
report, and summary with the same root material deduplicate to one root; a summary
cannot create a root. `ClaimLedger` records revision-CAS support/refutation edges
against active, admitted roots with matching data identity, group, and subject
bindings. Call `refresh_after_withdrawal()` after an evidence revocation to record
affected claim revisions in its sidecar.

Claims can also persist explicit `link_dependencies()` edges. A changed or
withdrawn upstream revision marks downstream interpretations `needs_review` while
preserving their own still-active roots. `mark_unattributed_summary()` records a
review requirement only: an unknown-origin string cannot become support. Replay
checks identity, bindings, continuous CAS revisions, active-root filtering, and
dependency structure for propagation records. The JSONL log is audit storage, not
a signature authority; custody still owns writer permissions and trust.

`ContextBuilder(identity, budget_bytes=...)` provides `baseline` and `candidate`
paths. The candidate path rebuilds from active roots and current claim relations;
baseline summaries are explicitly `untrusted_summary` entries with no evidence
roots. Candidate entries include `needs_review` and their dependency IDs.
`ContextCache` keys every bundle by its full derived content hash. Validation
bundles are ephemeral and never enter its retained cache.

Typical runtime construction:

```python
identity = DataIdentity("discovery", "task-7", "source-3", "v1", "train-a", "train")
evidence = EvidenceLedger(identity, storage_path=sidecar / "evidence.jsonl")
claims = ClaimLedger(evidence, storage_path=sidecar / "claims.jsonl")
context = ContextBuilder(identity, budget_bytes=12_000).build(question, evidence, claims)
```

The caller is responsible for custody, trusted-validator authorization, task leasing,
and ensuring that sidecar locations obey the train/validation isolation protocol.
