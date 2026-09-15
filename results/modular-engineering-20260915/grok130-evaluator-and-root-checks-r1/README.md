# Grok 1.0.30 evaluator and merged provider checks

The explicit normal-CLI deployment now binds private evaluator configuration, pure factory descriptors,
actual native request context and independent replay. Successful synthetic factory calls verify the
outgoing account client headers; invalid deployment records are rejected before allocation. Legacy
declarations retain their prior fields and behavior. ACP is a separate interface.

r1 preserves 23 passes and one source-tamper fixture signature failure at source 02420d75.
After the legacy single-argument source-pin call was restored, r2 passed 25 checks at 6ec1a720.
Merged ROOT f9a53d34 passed 53 checks spanning TRAIN port, evaluator factory/port and label isolation.
Each generation preserves its own original native completion, exact source bytes and runtime files.
No real model/API/VAL call was made by these synthetic checks; live controls are separate evidence.
