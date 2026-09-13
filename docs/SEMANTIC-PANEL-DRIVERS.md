# Q2.2 and Q6.4 semantic panel drivers

`research_loop.modular.semantic_panel_drivers` provides the train-only P0
drivers for Q2.2 completion semantics and Q6.4 scorer repair. It replaces no
scorer service and does not make a calibration, validation, or scientific
completion claim.

The caller freezes one `semantic-panel-bundle-v1` per prepared `PublicTask`:

```python
bundle = freeze_semantic_panel_bundle(
    task,
    q22={
        "affirm": {"source_id": task.identity.group_id, "raw_answer": "...",
                   "public_evidence": {"public-id": "public text"}},
        # negate, quote, counterfactual, local use the same closed answer shape
    },
    q64={
        "negation": {
            "first": {"source_id": task.identity.group_id, "raw_answer": "...",
                      "public_evidence": {"public-id": "public text"}},
            "second": {"source_id": task.identity.group_id, "raw_answer": "...",
                       "public_evidence": {"public-id": "public text"}},
            "legacy_diagnostic": {"status": "legacy-unmodified", "record_digest": "..."},
        },
        # quotation and alternative have the same closed Q6.4 shape
    },
    p0_control_digest=p0_control.content_hash,
)
```

The bundle binds the task identity and public payload digest, requires every
registered variant, and rejects extra answer fields. In particular, expected
semantic labels, outcomes, arms, and historical scores cannot be inserted into
the answer material. `semantic_panel_injection()` checks the caller record
again while constructing the scenario. The exact P0 digest is carried in all
three or five model requests; the panel receipt verifier checks it against the
frozen P0 grid after execution.

Q2.2 uses the fixed schedule `semantic_judgement`, `alternative_analysis`, and
`final`. The first two model responses are validated by
`judge_completion()` and `assess_alternatives()`, then joined by
`score_completion()`. Negation, quotation, counterfactual, local, and
abstaining responses cannot become programme-completion claims through a
driver default.

Q6.4 runs the same frozen completion-semantics record on two independently
caller-provided answers: first semantic/alternative calls, second
semantic/alternative calls, then final. The legacy record digest is retained
only in the session trace as diagnostic provenance. It is excluded from all
model contexts and cannot alter either new score. Both scores must therefore
carry the same semantics digest.

All semantic and alternative model requests contain only the public task,
public evidence, raw submitted answer, frozen semantics schema, opaque cell
binding, and P0 digest. The final request also contains the validated new
semantic score records. It contains no variant identifier, arm metadata,
expected truth, controller input, or legacy diagnostic. A malformed model
response terminates that cell through the existing `RunSession` failure path;
the cell remains in the frozen panel denominator.

The included synthetic DiscoveryBench and BLADE tests exercise the entire
16-cell two-benchmark P0 grid, reconstruct the trace with
`PanelReceiptVerifier`, and verify failed output and source/label-cue
preflight paths. They use a synthetic model port only. Root integration still
owns registry installation, caller custody projection, and the real
`CodexModelPort` binding; those deployment seams need independently reviewed
scoring and calibration before any scientific use.
