# Q5.4 causal repair

`q54_causal_driver.py` replaces the earlier causal path for future Q5.4
integration.  A caller freezes public diagnostics, literal program and input
hashes, competing prediction branches, a shared measurement contract, and two
authority identities.

The run first validates actual input bytes, obtains a complete model ranking,
and derives the subjective selection score from that ranking.  The
preregistered-cost path uses the frozen uncertainty-per-cost criterion.  M4
freezes the caller's real competing plan and records the authority's
classification through `PredictionRegistry.record_outcome`.  Every M7 arm
executes one selected program under the same Docker allocation; M7 determines
whether the verified gate disposition is applied to the following diagnostic
decision.

The authority receives the complete execution receipt and hash-verified public
program/input bytes.  The final model receives only a public projection without
host paths, argv, authority contract, bundle, arm, or policy labels.  Signature
and source binding establish provenance only; they do not establish scientific
correctness, independence, or calibration.
