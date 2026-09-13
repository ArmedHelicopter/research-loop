# Q2.7 production protocol driver

`research_loop.modular.protocol_panel_driver` is the production-facing Q2.7
seam. It is not the older `scenarios_protocol` fixture: no fixture keys,
program, synthetic authority, or variant instruction is accepted by this API.

The caller freezes a `q27-protocol-panel-bundle-v1` for its prepared public
task. The bundle binds literal UTF-8 CSV bytes and their SHA-256, the program,
a digest-pinned image, timeout, task payload, and the actual P0 fixed-control
grid. `protocol_panel_injection` reconstructs that bundle and rejects a grid,
task, payload, or byte-hash mismatch before Docker or model work begins.

`Q27ProtocolDriver` requires a caller-owned `DockerExecutionBroker`, two
runtime audit receipts returned by a caller-owned audit port, and the trusted
digest of the compiled P0 control. Every variant has one Docker allocation,
two audit receipt opportunities, and one final-model slot. The model receives
the task, frozen objective, opaque cell binding, execution feedback, and public
execution digests. It does not receive an arm, variant, controller material,
or CSV byte payload. A zero exit code is only execution evidence; the signed
audits still supply the admission decision and scientific correctness remains
an independent-review question.

After `RunSession.finish(candidate)`, the caller invokes `verify_after_finish`.
It first verifies the untouched source trace, creates a separately rechained
offline replay with exactly one controlled omission or invalid terminal state,
and requires `verify_protocol_trace` to refuse it. A caller-configured
`ProtocolReplayAuthority` signs the typed receipt. The receipt binds source and
replay trace digests, candidate, cell, scenario, budget, and refusal. An
unexpected replay acceptance, a changed source trace, missing receipt, or bad
receipt signature must fail the cell closed when the runner integration hook is
installed.

This is engineering provenance for a source run plus controlled structural
replay. It does not claim scientific validation, audit independence beyond the
configured ports, OS isolation, or calibration.
