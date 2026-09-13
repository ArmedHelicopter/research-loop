# Q5.5 causal resource-closure driver

`q55_causal_driver.py` is a train-only driver for the four declared missing
prerequisites: data, method, budget, and negative control.  A caller freezes a
`q55-causal-bundle-v1` for the exact public task.  Each item binds canonical-LF
program text, its canonical and host-byte hashes, a digest-pinned image, every
public input's SHA-256 and byte count, two distinct authority identities, and
two distinct opaque source selections in the same retrieval lane.

The caller supplies a local `Resolver`, `Provider`, and `Authority` port.  The
resolver's literal bytes are verified before provider or model I/O.  The driver
then makes the same three bounded provider calls in every M6/M7 arm against the
same frozen source pool.  M6 selects the caller-declared closure document after
those calls; its control selects the corresponding ordinary document.  Only the
selected public lane/text reaches the model.  Source IDs, roots, variant names,
runtime arms, policy names, authority subjects, host paths, and Docker argv do
not.

The authority receives the full caller material: task binding, selected and
retrieved records, program representations, verified literal input bytes, and
its two-authority contract. The driver receives the matching two authority
keys separately from the bundle and verifies each HMAC over the exact
observation binding. It must return exactly two signed-origin observations, a
matching aggregate status, and literal resolution values. A
failed or unknown aggregate cannot resolve anything.  The raw authority
response, typed partial response, request reservation, reported cost, and
failure are retained in the session trace before a failure is propagated.

P0 still blocks Docker whenever the named prerequisite is unresolved.  When it
is qualified, M7 obtains a real bounded `admit_exploration` permit; its control
performs an explicit ordinary prerequisite check and cannot bypass P0.  Both
may consume the one frozen Docker opportunity.  The receipt must bind the
actual host program bytes and every input artifact.  The final model receives
only sanitized stdout/stderr/status and public closure state.

The synthetic test grid covers two public benchmark task shapes, four missing
prerequisites, and all four M6/M7 arms.  It also covers an inconsistent dual
authority receipt, input-byte drift before provider/model calls, and a provider
exception whose partial response and reported cost remain ordered in the
journal.  These are engineering trace checks.  They do not establish authority
independence, calibration, scientific validity, or an effect of retrieval or
resource closure.

The registered `run_train_panel` entry now supplies the frozen provider,
authority, keys and Docker broker directly. It verifies the exported CSV against
every fault row before any provider, model or authority request. Source
`a0beade8b3bc60eec6e4d1c5166bc1bd01bafa99` passed 52 independent checks,
including the complete 32-cell custody/controller grid. The formal grid checks
64 model calls, 96 bounded lane requests, 32 dual-signature authority requests,
and 16 actual Docker executions in the resource-resolved arms. Every cell has
the same one-execution opportunity; unresolved prerequisites remain blocked.
The model transport and scientific authorities in this test are public fixtures.
