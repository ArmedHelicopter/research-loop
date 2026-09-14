# Bounded Grok initialization observation, 2026-09-14

The isolated official-download Grok1.0.30 executable returned an ACP protocol1
initialize response after29.844 seconds; shutdown completed at30.0 seconds.
There was exactly one initialize and no session, authenticate, billing, top-up
or prompt RPC. The native process68668 exited and the numeric observer closed.
Global login-file metadata stayed unchanged; the isolated opaque copy refreshed.
Neither credential contents nor credential hashes were inspected or archived.

The immutable initialize-only engine rejected subsequent notifications, so its
original accepted_initialize=false and unexpected_notification/extra_captured_frame
faults remain unchanged. Four model updates, two settings updates and two
announcement updates followed the response. Scoped read-back showed current
model grok-4.6, allow_access=true, consent_gate=null and no gate label/message.
These facts establish a returned initialization response in this attempt. They
do not establish working generation, tool isolation, billing settlement or a
scientific result. Earlier timeouts remain valid observations; changing time,
paths/account/cache state means no startup cause or corrective effect is proved.

One numeric Windows wait-chain snapshot was captured at10 seconds (the native
process closed before the scheduled30/50 second snapshots). No memory, lock
names, native log bodies or credential files were collected. Single-node wait
chains do not exclude unsupported synchronization waits. Windows documents the
API and its limitations at https://learn.microsoft.com/en-us/windows/win32/api/wct/nf-wct-getthreadwaitchain
and https://learn.microsoft.com/en-us/windows/win32/api/wct/ns-wct-waitchain_node_info .

Independent reviewer grok_provider_independent_review found two observer cleanup
defects before launch: startup could lose ownership, and shutdown used an error
type the unchanged engine did not catch. Both were repaired; two injected cleanup
checks passed without a native launch. Re-review approved exactly one60s launch,
with at most three observations each bounded by4s. The envelope pins both new
files, cleanup test, unchanged engine and transport, config and executable.

The archive preserves original public closure, exact reviewed source snapshots,
numeric OS metadata and frame hashes/structure. Native stdout remains private
at the original path and is not copied here. No old protocol was relaxed and no
additional probe is authorized by this receipt. Normal transport handling and
the versioned native deployment/readiness path remain the next integration work.
