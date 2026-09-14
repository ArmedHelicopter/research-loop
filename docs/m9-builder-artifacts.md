# M9 builder artifact seam

`begin_builder_artifacts(catalogue, root=..., builder=selected, parent=package,
response=response, recipe=recipe, fixed_builder=plan.fixed_builder)` records the
selected DSL and immutable parent/TRAIN manifest before execution. It resolves
the actual request and response trace descriptors in the same catalogue and
checks their request hash, response, public subject, slot, instruction, run lock,
parent package and M9 activation. A caller-supplied substitute response cannot
serve as invocation provenance.

Call the returned bridge's `execute()` in place of the original restricted build
and three file writes. It writes `builder.json`, invokes the existing local
`RestrictedBuilderPort.execute`, writes `builder-receipt.json`, then writes
`candidate.json`. Each fsynced file immediately receives a descriptor; candidate
parentage includes the preceding receipt and transitively the selected builder.
The three files preserve their original canonical bytes and names. Their order
now ensures that the builder is durable before execution and the receipt is
registered before the candidate. A separate `m9-build-terminal.json` binds the
output inventory, cost, phase and success/failure.

Original returned records are retained before `_checked_build` rejects semantic
drift. Interrupted partial files are retained by byte count and SHA-256 even when
they are not canonical JSON. The original exception escapes unchanged. If an
intervening caller operation fails before execution, call `bridge.fail(exc)`;
after an existing terminal this does not overwrite the build outcome. The caller
must retain a distinct failed stage receipt when a later trace operation fails,
or when the artifact journal itself is unavailable.

`verify_builder_artifacts` takes the same arguments, reads only original files,
checks every descriptor and causal edge, and for successful builds replays
`select_builder`, `RestrictedBuilderPort.execute`, and `_checked_build`. This
literal DSL replay performs no filesystem writes, model calls, network requests,
task generation, or acceptance. Missing files are rejected, never recreated.
Failure replay verifies retained evidence; it does not claim to reproduce an
external filesystem failure or make the failed candidate eligible.

M9-disabled ordinary revision runs retain `not_applied` descriptors and the fixed
builder control. Failed terminals use `failed` while retaining that activation.
All optimization subjects must belong to the frozen TRAIN manifest. VAL
acceptance, production activation, rollback and scientific validation remain
separate existing mechanisms; this bridge grants none of them. Existing studies
and module behavior are retained. The enclosing C4 run/verify seam must explicitly
call these APIs; this module alone does not prove that production wiring.
