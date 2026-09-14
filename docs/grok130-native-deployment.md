# Isolated Grok 1.0.30 deployment

`FrozenNativeDeployment.create(executable)` describes only the pinned official
1.0.30 Windows download (local SHA256 `ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266`,
reported build `04b7ffed98c6`). It admits the observed `--cwd … agent stdio`
command with `GROK_DISABLE_AUTOUPDATER=1`. It does not establish exact public
source/binary equivalence or accept a caller-selected hash, version or command.

Passing this exact typed descriptor as `deployment=` to `run_native` or
`run_native_diagnostic` selects the new path. Omitting it preserves the 1.0.13
binary pin, `--no-auto-update` command, configuration and receipt schemas.
The public TRAIN provider is not upgraded by this change. No global CLI or
login configuration is modified.

Both paths retain fresh isolated home/profile/cwd, API-environment exclusion,
Grok 4.6 session binding, an actual empty runtime tool inventory, same-process
fresh included-subscription billing and no-topup gates before a prompt, 60-second
maximum lifetime and no retry. Standard model/settings/announcement notifications
already have handlers; advisory access metadata is not a billing or tool gate.
The main/possible-initial-title allocation and unknown title/all-settlement
accounting are unchanged. The billing snapshot is not an atomic spending lock.

The new launch requires pins for both the deployment implementation and transport
source, executable and configuration. Each prompt reservation uses v2 and binds
the deployment digest. The smoke receipt uses v3; diagnostic receipt/binding v2
also binds the descriptor to original request, response, reservation and source
manifest bytes. The original-byte reader rejects mismatched or omitted deployment
identity. The new deployment replays executable and source pins after process closure; a failure rejects eligibility while retaining observed known MAIN usage. The protocol engine alone remains a synthetic seam, not an executable
provenance attestation.

`provision_native(..., deployment=descriptor)` creates new material config,
native deployment, authoring envelope and outcomes v2. It preserves four MAIN
and four possible initial TITLE opportunities, output cap 8192, input byte cap
262144, observed MAIN cap 131072, and the separate 180-opportunity review allocation.
It copies only an explicitly supplied login opaquely; login bodies never enter
source hashes. The old failed envelopes remain spent and cannot be reused.

Diagnostic subscription worker config v2 requires deployment v2; worker config v1 rejects that deployment. The signed observation v2 includes the native deployment digest and the immutable outer deployment/config descriptors. Diagnostic subscription deployment v2 adds `native: descriptor.record.data()`
to the old executable/slot/source inventory. Its immutable outer descriptor and
config hashes join the per-call source manifest after loading, avoiding a
self-referential hash. Existing manifest budgets and frozen request inventories
remain unchanged; the typed native result carries the exact deployment to the
accounting reader. A v1 deployment never silently admits the v2 executable.

Tests use non-executable synthetic binary bytes with a test-local identity pin
and replace only the final process launch with the existing Python ACP peer.
They exercise the actual native preflight, notification handling, account/tool
gates, original reader, material envelope and diagnostic subscription path.
No real initialize, session, prompt, billing RPC, API fee or validation is part
of this implementation's verification. A real readiness probe requires its own
separately frozen reservation; source support does not itself prove readiness.
