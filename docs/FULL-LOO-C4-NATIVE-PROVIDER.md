# C4 native Grok provider route

`c4-full-loo-native-provider-plan-v2` is a separate, versioned execution
attachment to the frozen C4 v1 runtime plan.  It leaves
`run_full_loo_train` and its Codex model contract unchanged.  The native route
requires an actual closed `GrokTrainProvider` whose configuration fixes
`grok-4.6`, `run_native_train`, an included subscription route, no API-key
route, a 60-second native lifetime, and zero retries.

The plan permits exactly 169 MAIN opportunities: 45 for the nine canonical
history builds and 124 for the 22 target cells.  It sets every prompt limit to
262144 bytes, requests 2048 output tokens for every slot except the 8192-token
analysis program, and retains the observed 131072-token MAIN bound.  A possible
initial-title opportunity is recorded alongside each MAIN request.  Its usage
and the all-opportunity settlement are deliberately unknown and never folded
into known MAIN accounting.

One `PhaseProviderSession` owns the whole run.  It writes a disjoint,
ordered global scope for every history build and target cell.  The history seal
is an original-prefix seal: later targets may append but cannot replace its
calls.  Candidate construction completes and the native candidate barrier is
verified before any target model or solver request.  Target cells then seal the
entire provider session before the independent scorer starts.  The scorer sees
only original, scoped native responses that pass exact request, response, usage
and provenance replay.

The native receipt preserves all 22 target rows and both `without-M2`
structural rows on failure.  Unknown MAIN usage, a failed call, or a provenance
fault uses the terminal phase-abort record: it keeps only durable lower-bound
accounting, records title uncertainty, blocks later work and scoring, and does
not invent an eligible original seal.  After the final scorer call, the target
seal is replayed again.  A later provenance fault retains historical score
artifacts but marks every result ineligible and prevents a complete receipt.
It does not activate a candidate, open validation material, establish P0
qualification, or claim a scientific effect.

`tests/test_full_loo_native_provider.py` runs the complete 22-cell grid with a
synthetic ACP subprocess replacing only OS spawn.  The test uses the default
native entry point, a closed Grok provider, the real restricted builder port,
the existing Docker broker, and the independent C4 scorer process.  It also
checks an unknown-MAIN prefix and target-seal provenance substitution.  No real
model, API, validation, or benchmark reference is opened.
