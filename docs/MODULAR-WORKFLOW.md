# Modular workflow driver

`ModularWorkflow` is the activation-aware adapter over an already frozen `RunSession`.
It invokes M4 through `PredictionRegistry.freeze`, seals all M5 role submissions before revealing them to the following slot, calls M6's frozen provider before the following slot, issues M7 permits before restricted broker execution, and drives M8 SQLite enqueue/claim/complete/merge. `record_stages` requires an explicit executed or blocked reason for stage 0.5, 1, 3, 7, 9 and frontier; missing hooks are blocked trace records. M9 accepts only an explicit package policy hook.

All model calls still go through `RunSession.invoke`, so fixed slots, context budget, existing M1--M3 context refresh, execution allocation, HMAC audit and final gate remain authoritative. The driver has no scorer or label access.
