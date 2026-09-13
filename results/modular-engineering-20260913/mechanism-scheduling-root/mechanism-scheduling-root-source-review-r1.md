# Mechanism/scheduling root source review

Reviewed source 06e88f9 and the merged explicit scorer scope at 785270a.
This follows the mechanism/exploration review; the two versions remain
separate frozen recipes. The scheduling driver keeps the same useful ordinary
M4/M5/M6 controls and original mechanism replay. It replaces the phase factor
with M8 and explicitly reserves maximum concurrency two. M7 is disabled.

The same two useful literal jobs and cost units are selected in both M8
levels. M8-on reaches the actual FIFO scheduler, immutable snapshots,
dependency/resource checks and full merge barrier. Mechanism output freezes
before phase work. Original mechanism and phase outputs enter one solver,
and original program/input/receipt replay precedes independent score issuance.

The focused checks inspect actual container-internal monotonic intervals to
establish overlap, dependency/resource serialization, reversed completion with
FIFO public ordering and timeout container removal with no residual leases.
They also mutate the persistent queue database and phase journal. This verifies
execution behavior without attributing a throughput improvement under concurrent
host workload. Failed/unknown phase outcomes retain the whole denominator.

The inherited source verifier preserves unknown realized cost while bounding
requested call opportunities; it does not certify source expenditure. This is
distinct from the hard model token ledger, whose unknown main usage blocks
later cells. No accounting contract was changed during this integration.

Root merged the added family without changing the exact history-trained panel
construction. A dedicated scope regression rejects the new flag together with
state-improvement, and rejects the wrong history scope by itself. No concrete
blocking defect was found in the reviewed scope. Synthetic solver/scorer
responses, selected adversarial cells and local authority ownership remain
limits. Frozen root execution and archive verification are recorded separately.
