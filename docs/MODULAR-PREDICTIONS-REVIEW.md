# M4 competing predictions and M5 independent review

These modules are engineering seams for the frozen Q3/Q4 mechanisms. They do not claim that a model call, a review, or a synthetic test establishes a scientific effect. The two benchmark experiments remain separately required.

`PredictionRegistry` freezes branches with explicit `mechanism_key`, intervention, elimination condition, and one or more operational predictions. Each prediction names an observable, exactly one directional or numerical-range expectation, a failure condition, and a discriminator. A valid competing plan needs a shared discriminator with a distinct declared prediction for every branch. The module rejects duplicate declared mechanism keys and identical discriminator signatures; it never guesses semantic diversity from titles or text.

```python
registry = PredictionRegistry(identity, storage_path=sidecar / "predictions.jsonl")
plan = registry.freeze(question, branches, budget_units=3)
registry.record_outcome(
    plan.plan_id, "shared-discriminator", "observation-hash",
    {"mechanism": "consistent", "measurement": "failed"},
    {"trusted_evaluator": "execution-broker", "verified": True},
)
```

`ReviewEngine` opens a task- and identity-bound review session with a concrete question for every role. A reviewer may use one role once, total submitted cost cannot exceed the session budget, and submissions remain unavailable until every assigned role has submitted. Revisions are only possible after that barrier and retain a before/after receipt. Responses permit `accept`, `concern`, and `unknown`, so reviewers receive no incentive to invent a counterexample.

```python
engine = ReviewEngine(identity, storage_path=sidecar / "reviews.jsonl")
session = engine.open(task_binding=identity.task_id, evidence_snapshot=evidence.version,
                      roles=roles, budget_units=12)
engine.submit(session.review_id, role_id="measurement", reviewer_id="sample-2",
              response=response, cost_units=3)
# only after all roles submit:
submissions = engine.reveal(session.review_id)
engine.record_score(session.review_id, changes=changes,
                    scorer_receipt={"trusted_scorer": "sealed-scorer", "verified": True})
```

Both JSONL sidecars are append-only canonical event logs with `fsync`; custody must provide a single writer or locking for multi-process operation. `trusted_evaluator` and `trusted_scorer` are integration ports: these modules verify receipt shape and identity, but host isolation must establish authority. They never access benchmark labels or let a reviewer self-declare correctness.
