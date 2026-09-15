# Repaired frozen timeout and complete scheduler checks

Source d672c274 repairs the TRAIN adapter's hardcoded 60-second comparison:
the adapter checks the live integer bound and its equality to the frozen port
configuration. The scheduler test reads the actual configured evaluator ledger.
No previous failed report is rewritten.

All 21 ROOT checks passed, including ten label-isolation checks, actual 240s
solver/evaluator child configuration and replay, the two primary score routes,
M4/M5 preflight drift refusal, stdin EOF, retained-capture overwrite refusal,
ACP stdout compatibility and scheduler descriptor/readback checks.

The separate full scheduler test passed its actual eight-cell stdio/Docker
execution: 16 synthetic solver calls, eight scores, exact ordered signed closure,
eight eligible cells, bound provider/configuration, 80 known MAIN tokens and
explicitly unknown title settlement. Both native sessions joined exit 0 and
each exact 809-file source generation remained unchanged.

These are synthetic engineering checks, not evidence of actual model quality,
scientific effect, or VAL acceptance. They made no real model/paid API calls.
The preceding 128/15/21 first-check reports keep their five original failures
in a separate archive and are not relabeled as passing.
