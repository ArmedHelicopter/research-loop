# Headless process capture and frozen time limits

Headless children write stdout and stderr directly to owned evidence files.
The parent supplies stdin EOF, waits for the configured duration, closes the
owned process tree, then records the final observed exit code. Timeout output
is retained even when no accepted completion response exists. A capture path
that already contains evidence cannot be reused. ACP keeps its PIPE interface.

TRAIN solver and evaluator ports accept an integer timeout from 1 to 240 seconds,
with the existing 60-second default. This uses the diagnostic transport's existing
maximum; it does not add retries or relax account, token, label or paid-route rules.
The chosen value is frozen in port configuration, evaluator descriptors, child
records and replay specifications. M4/M5 controller declarations must agree with
the live solver timeout before dispatch. A prospective batch uses the same frozen
value across its arms. Changing it requires a new batch, never a mid-run update.

The earlier M4/M5 r3 timeout and null-exit-code record remain unchanged evidence.
This repair does not recover a missing response, establish zero consumption or
show module effectiveness. Synthetic checks exercise actual local children,
inherited handles, stdin EOF, both primary scorer routes and independent replay.
Actual check outcomes are recorded separately after execution.
