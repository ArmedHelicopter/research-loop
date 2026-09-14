# Freeze the TRAIN-selected joint snapshot

`freeze_selected_joint_snapshot` calls the complete original TRAIN controller
verifier and frozen selection rule, then derives all nine component versions
from that one choice. Callers cannot supply a substitute recipe or package.
Each slot records its imported consumer template, history and target activation
levels, the selected history package, and selection/build receipt bindings.
M9's history optimization remains distinct from its disabled target stage.

The component TRAIN manifests include both the history task and all target
tasks used for selection. The inner learned package remains history-only;
omitting the selection targets from deployment provenance would conceal their
influence. The original baseline and P0 remain fixed, and the target bundle
pins the expected preceding snapshot for the atomic store's concurrency check.

The result is a frozen candidate for independent V_final acceptance. It neither
opens validation nor issues an acceptance/deployment grant. Individual components
must not be dispatched as separate store snapshots. The existing atomic store
still needs an independently authorized acceptance result to activate the bundle.

Projection tests use explicitly synthetic selection records and do not establish
authentication. The complete controller test connects the real controller,
independent scorer process, authenticated selection and snapshot factory in the
same run. Its completion must be inspected before claiming that boundary works.
Future live/validation consumers still need to consume these fixed component
versions through their execution adapters; constructing the bundle alone does
not establish that consumer integration or scientific effect.
