# Q2.7 production protocol driver v2

This driver tests structural P0 fault rejection using a real, caller-frozen
source run. It does not establish scientific validity, evaluator independence,
source truth, OS isolation or calibration. The v1 document is preserved verbatim
in `Q27-PRODUCTION-PROTOCOL-DRIVER-V1-ARCHIVE.md`; its old passing checks do not
validate the repaired bindings described here.

## Frozen source and audit API

`freeze_protocol_bundle(task, execution=..., p0_fixed_control=...,
measurement_contract=...)` returns `q27-protocol-panel-bundle-v2`.
`protocol_panel_injection` returns `q27-protocol-controller-v2`.
Measurement contract has exact source_id, contract_id, method, output_key fields,
with source_id equal to the prepared task group. The task is train-only.
Execution material has program, csv_bytes_hex, csv_sha256, image and
 timeout_seconds; optional caller program_sha256, program_byte_count and
csv_byte_count are checked against the actual literal bytes. Returned canonical
material includes all three calculated fields. Program source uses LF; frozen
execution bytes follow the existing RunSession host text translation (CRLF on
Windows). The pinned-image grammar is validated before I/O.

Every variant freezes one Docker attempt, one batch audit call, two registered
authorities, two material receipts, two runtime receipts, and one final-model
call. These are separate counts: two authorities or receipts do not imply two
RPC calls. The bundle includes this allocation. The audit call is journaled and
fsynced before I/O, with initially unknown cost. Original responses are stored
before validation. Partial response, transport failure, schema failure and
signature failure retain the spent attempt and reported cost; verified cost is
unknown, never silently zero. A successful cost is `{unit:"audit_units",
units:nonnegative_integer_or_null}`. The driver enforces call allocations, not
a monetary ceiling when the transport cannot report cost. No failures retry.

The actual ExecutionReceipt must match task identity, program SHA and byte
count, and the complete input_artifacts collection including CSV SHA and size,
before an audit or model request. A changed execution artifact cannot inherit
the preflight declaration.

`ProtocolAuditPort` is a callable taking a frozen
`q27-runtime-audit-subject-v2` and returning one frozen `q27-audit-batch-v2`.
The subject contains prepared public task, objective, bundle binding, full actual
execution receipt, exact checked public program/CSV bytes and measurement
contract. This supplies the material needed for the caller's independent
measurement checks; a digest-only undefined resolver is not assumed.

The batch has exact schema, subject_digest, material_receipts,
runtime_receipts and cost fields. Each of the same two configured authorities
uses existing `AuditAuthority.issue_material` to sign the full subject digest,
and `AuditAuthority.issue` to sign the actual execution/objective. The driver
uses existing `AuditVerifier.verify_material` and `verify_evidence`; authority
sets, state, outcome and audit checklist must agree, and claimed execution
success must equal the actual receipt. Only then does RunSession.admit apply its
existing admission rules. The caller must perform genuine registered checks
before issuing either signature. The signatures authenticate the observations;
they cannot make unsupported scientific statements true.

The final model receives the public task/objective, opaque cell/P0 bindings,
actual execution feedback and public artifact digests. It receives no variant,
controller bundle or signing material. The standard candidate is returned
verbatim and RunSession.finish remains the only source terminal writer.

## Immutable post-finish hook

After the real finish, invoke:

```python
verify_after_finish(
    cell=cell, scenario=scenario, session=session, candidate=candidate,
    terminal=terminal, replay_authority=authority,
    expected_p0_control_digest=trusted_p0_digest,
)
```

The hook compares complete candidate/terminal objects with the actual last
model response and journal tail, compares disk events with the completed live
session, verifies the source protocol, reauthenticates the source's material and
runtime audit pair, and checks cell/scenario/lock/package/P0/request bindings.
It also rechecks actual execution artifacts. Passing two selected digests is
insufficient. Source bytes must remain unchanged.

All four faults use the same frozen eligibility rule: a succeeded execution,
a qualifying admitted source and an actual proceed/closed_negative terminal.
An unknown/blocked source is retained as signed `status="ineligible"`,
`inconclusive=true`, with its actual usage and no fault replay. It does not become
a P0 false negative and is not retried to obtain a positive source.

The hook exclusively creates `q27-replay/` inside this source cell and fsyncs an
attempt manifest before writing a replay. A repeated hook or preexisting replay
directory is rejected; earlier bytes are never overwritten. The registered
fault produces an exact rechained copy: omit lock, omit execution events, omit
audit/admission events, or change terminal decision to illegal_state. A refused
eligible replay gets `status="refused"`; unexpected acceptance is signed and
saved as `status="unexpected_acceptance"` before the hook raises. The finding
binds full source/replay byte SHA-256 as well as journal-tail hashes, actual
candidate/decision, cell, scenario, eligibility, usage and refusal. The original
journal is not modified. Partial files remain available after I/O failures.

## Independent read-only verification and controller integration

```python
finding = verify_protocol_replay_receipt(
    receipt, cell=cell, scenario=scenario, source_trace_path=source_trace,
    replay_authority=authority, expected_p0_control_digest=trusted_p0_digest,
)
```

This function never creates a replay. It verifies the configured host receipt
signature, exact finding schema, real source byte hash/protocol/candidate and
cell/P0 bindings, actual usage, immutable stored attempt/receipt, fixed replay
path with link/alias exclusions, exact registered event transformation, complete
replay byte hash and reproducible refusal. Ineligible findings are authenticated
as incomplete experiments, not successful checks. A caller must require
`finding.data()["status"] == "refused"` to qualify success. Authentication by the
configured replay issuer establishes host provenance; it does not independently
reauthenticate the scientific auditors' keys or prove their science.

The production registry and `run_train_panel` now compile this typed scenario
against the actual P0 grid. The Python entry point requires caller-owned
`protocol_audit_port` and `protocol_replay_authority`, and allocates an internal
Docker broker constrained to the new run root. Dependencies, reviewed model
schema equality, exact one-Docker/one-audit/one-model per-cell budget, total model
capacity and separate paths are checked before export/model execution. Broker
construction occurs after the controller attempt record exists and before export.
Authority keys and host paths remain outside the frozen public configuration.
The generic CLI cannot manufacture an audit authority and fails closed for Q2.7.

The controller compares every bundle CSV with the actual custody-exported path,
identity/packet metadata, complete named input set (`public_csv`), SHA-256 and
byte count. Inline CSV is only the frozen byte commitment to that same export,
not an alternate data source. The driver separately checks actual Docker receipt
artifacts. A pre-execution cell/P0 journal binding supports real failures before
any model request; it cannot replace the ordinary successful model binding.

Only after the genuine source finish does the runner call the replay hook. It
exclusively persists `protocol-post-runtime.json` and `call-plan.json`, whose
protocol record binds the actual replay receipt path and digest. The controller's
`protocol_post_runtime_verifier(compiled, authority)` closure independently rereads
these sidecars and the actual signed receipt, verifies cell/scenario/source/P0
bindings and calls the strict read-only material verifier. A Q2.7 succeeded
receipt passed to `PanelReceiptVerifier` without a trusted callback is rejected.
A callback returning only a status flag is also rejected.

Source unknown/blocked, hook exceptions, malformed verification and sidecar
persistence failure retain the original final journal and output digest as an
unscored cell with a bounded reason code. If a sidecar cannot be persisted, the
returned call plan is retained in the controller attempt record; it cannot
qualify success. Source execution/audit/model failures retain their real failure
terminal and allocation. No failure retries. All allocated cells remain in the
denominator, and any such cell yields `engineering_incomplete` with the controller
receipt `execution_incomplete`. A total failure of controller storage itself may
still interrupt execution and requires operational recovery; this code does not
claim filesystem durability across a lost storage device.

## Tests and limits

The fixture uses both public benchmark adapters, one synthetic CSV, an actual
mean computation in pinned Docker, and an independent fixture audit function
that checks literal artifact hashes, input rows, output and registered public
mean contract before signing. Both audit signatures bind the full material and
runtime execution. This is a deterministic synthetic measurement check, not a
benchmark scientific evaluator. Production integration uses actual custody export, reviewed-context CodexModelPort
with a mocked local process transport, real pinned Docker execution and a host
fixture audit. There are no paid providers, private references or validation data.

The eight source/fault cells are complemented by source unknown/blocked,
transport/partial/signature/nonboolean audit failures, actual program/CSV drift,
forged terminal/candidate/scenario/P0 inputs, replay reuse, byte tampering and
path alias counterexamples. Existing original commits/reports and failed local
verification attempts remain preserved. The full eight-cell custody/CodexModelPort/Docker/finish/replay/controller path is
covered, including unknown/blocked sources, audit failures and unknown costs,
preflight refusal, post-hook storage failures and actual sidecar tampering.
Independent benchmark scoring, scientific validation, source-lineage
qualification and OS authority isolation remain outside these synthetic
engineering checks.
