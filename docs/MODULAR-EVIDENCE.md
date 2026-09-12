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

`ContextBuilder(identity, budget_bytes=...)` provides `baseline` and `candidate`
paths. The candidate path rebuilds from active roots and current claim relations;
baseline summaries are explicitly `untrusted_summary` entries with no evidence
roots. `ContextCache` keys every bundle by identity and ledger versions. Validation
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
