# Retrospective and frontier execution

`ModularWorkflow.retrospective` consumes two frozen model slots. With M5 enabled,
the first request exposes raw root evidence and the frozen objective, excluding
claim summaries and learned memory/prompt content. It seals the actual review
response in M5 before revealing the history summary to the second request.
The M5-off control consumes the same two slots and sees the summary first.
Both paths verify the deployed package digest when a deployment is configured.
The independent audit role's memory mask is fixed across these comparisons.

`frontier_audit` performs an actual frozen model call using current claim,
observation, failed-check, prediction-plan and objective references. Its output
must cite available origins and name an observable with two declared different
predictions. Exact syntax and source binding do not establish semantic novelty,
scientific relevance or true discriminability; independent review is still needed.

The result is a proposal artifact. Neither method adds evaluation tasks or
admits a follow-up into a benchmark. Training follow-up export rejects validation
provenance. Empty proposals require an explanation and never complete the overall
programme. Validation outputs remain within acceptance-side handling.

Stage coverage only accepts the trace of that exact executed stage; a lock event,
scheduler operation, failed stage or unrelated model call cannot stand in for it.
Integration tests exercise both public benchmark adapters and capture the actual
model callback inputs. These fixtures have no model efficacy or scientific score.
