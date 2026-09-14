# Atomic joint deployment boundary

`JointDeploymentBundle` identifies every enabled module separately: source-file
hashes, frozen configuration, frozen state, and TRAIN provenance contribute to
each `JointComponentVersion` digest. The bundle also pins its parent, baseline,
P0 and resource schedule. M3 and M9 require M2. This differs from the older
M4/M5 handoff's whole-arm package projections; neither object upgrades the other.

`JointDeploymentStore` publishes its entire component snapshot, active pointer
and used approval receipt in one SQLite transaction. Failure while staging any
component leaves the previous bundle active and the grant unused. A competing
writer must match the active parent. Rollback needs a separate signed grant and
can restore only the exact stored parent, including all previous state views.
Reopening the store does not forget consumed grants. P0 and baseline cannot be
replaced by a joint candidate.

Each task reads one immutable bundle and passes that bundle to its executor.
An activation during that task applies to later tasks; it cannot replace some
of the running task's components. The concrete `run_task` seam rechecks all
source bytes before and after execution. The integration fixture dispatches
all nine configuration/state payloads through an actual `RunSession` request,
then exercises activation and rollback. Source roots must retain the pinned
files for both current and previous versions. Source digests identify bytes;
the store neither loads arbitrary source code nor certifies executable builds.

The deployment grant is an **upstream independent acceptance service contract**:
schema `c5-joint-deployment-grant-v1`, stage C5, allocation V_final, one target
bundle, its expected parent, selection/panel/acceptance digests, and approved
decision. The trusted acceptance key must not be given to optimizers. The store
has no method to mint this grant, read validation labels or select a winner.
It verifies the authority and bindings; it does not itself re-evaluate the
upstream statistical acceptance receipt. Tests use explicitly synthetic grants.
Q6.3 cannot be substituted for the C5 stage.

This implements the local snapshot deployment port. It does not atomically
update external services, establish final TRAIN selection, calibrate a scorer,
complete V_final allocation, or connect every benchmark controller to C5.
Those remaining callers must use the fixed selected target and independent
acceptance result; a successful storage test is not a scientific acceptance.
