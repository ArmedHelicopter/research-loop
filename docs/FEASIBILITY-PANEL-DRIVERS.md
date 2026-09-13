# Q5.1 and Q5.2 feasibility drivers

`research_loop.modular.feasibility_panel_drivers` supplies train-only drivers
for Q5.1 and Q5.2. A caller freezes one source-bound bundle per public task
with every registered variant, a literal program and its Windows execution-byte
SHA-256, pinned image, CSV artifact SHA-256 and byte count, resource closure,
stage contracts, measurement contract, and Q5.2 competing prediction branches.

`install_drivers()` requires a Docker broker restricted to caller-designated
public roots, an input resolver, and a `FeasibilityAuthorityPort`. The resolver
paths are never trusted from the frozen bundle: the broker preflights their
actual literal bytes, and `RunSession.execute()` records the program artifact
and Docker receipt. The driver compares both receipts with the frozen hashes
before a model request.

The authority port must verify signatures itself and return only a frozen,
exact `verified-feasibility-stage-v1` record with a matching stage subject,
two distinct authority IDs, literal `signature_verified`, status, independent
source group, and optional per-hypothesis classifications. Ordinary mappings,
status strings, and source-group assertions are rejected. Signature and
subject binding establish provenance only. They do not establish scientific
correctness, independence, calibration, or a completion claim.

Both Q5.1 M7 arms make the same two model calls and one host-safe Docker call
for each variant. M7-on alone asks the authority port for all four actual
feasibility gates after the subjective assessment; M7-off retains the same
execution and subjective response without applying a gate. A successful exit
never advances a later stage itself, and a failed execution cannot qualify a
minimal-run or measurement stage.

Every Q5.2 arm executes its own frozen program once. M4-on freezes the
caller-provided branches through `PredictionRegistry`; a same-prediction plan
is retained as an unidentifiable rejection while its matched Docker execution
still occurs. M4-off creates no substitute plan. M7-on may use the shared,
caller-pre-registered measurement contract with no runtime M4 plan, and only
the authority's actual observation can qualify the stages. The final model
sees public material and actual artifacts, never arm, variant, expected truth,
or gate-success fields.

The synthetic test runs all 36 cells across BLADE and DiscoveryBench through a
real local Docker broker. It is engineering evidence for bindings and bounded
execution, not a scientific result or a calibrated feasibility estimate.
