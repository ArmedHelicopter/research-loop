# Headless diagnostic receipt contract

`run_headless_diagnostic` receives the exclusive path
`directory/native-reservation.json`, creates it before I/O, and creates the
session UUID itself. It creates `grok-headless-diagnostic-receipt-v1`; it is
not an ACP receipt.  It binds the frozen prompt, schema, source manifest,
reservation, exact command, private raw stream and private account observations.
It reserves one main turn.  An initial title opportunity and all-opportunity
usage remain `null`; server-reported cost is retained as an observation in the
stream inspection and consuming diagnostic ledger, not billing settlement.

`verify_headless_request_binding(result, entry, directory, spec, frozen_files)`
rereads `entry.private_request` (`{path,sha256}` with exact `{prompt,output_schema}`
contents), `directory/native`, and `directory/native-reservation.json`, rehashes
all frozen sources, re-inspects the raw stream, and verifies the private
response and account observations.  It returns `FrozenRecord` schema
`grok-headless-request-binding-v1` with:

- `identity`: requested/accounting model, reserved session ID, and terminal
  `request_id`;
- `usage.main`: the exact snake-case `inspect_grok_stream` usage object, plus
  explicit `main_model_calls` and `num_turns`;
- `usage.initial_title` and `usage.all_opportunities`, both explicitly unknown;
- `account`: safe pre/post projections and their oldest observation time.

The reader never accepts a self-attested `accepted`, usage, source list, or
billing flag.  A malformed/unknown/failed main has no response and must close
later authoring.

The reader's `spec.native_context` comes from the frozen authoring deployment:
executable, cwd, private_home and private_profile. It compares that context to
the reservation, reconstructs both commands and checks their recorded process
environments. The account client makes exactly three official CLI-proxy GETs
before and after the main call, disables ambient proxies and redirects, and
uses only the copied native OIDC login. Raw responses stay private. Reader
verification recomputes the included-pool/zero-paid-fallback projection from
all six raw responses and their ordered request logs. The oldest preflight GET
must be at most five seconds before launch; postflight starts after completion.
Those observations are not an atomic spending lock or proof of settled charges.

Before any process or account GET, the transport exclusively creates and fsyncs
its reservation. A bounded `inspect --json` must observe empty external-context
inventories and disabled API-key authentication in the same fresh home/profile/cwd.
Windows Job ownership covers inspection and generation; timeout closes the Job
before bounded reaping. A failure after reservation retains a terminal observer,
and any already-observed MAIN usage remains available to the caller even when
the response cannot be accepted. These records prove local observed execution
and byte bindings; they are not provider-signed attestations.

Material authoring selects this route only through explicit v3 config,
deployment, envelope, reservation and outcome schemas. Its prospective per-main
timeout is 240 seconds; v1/v2 ACP stays at 60. Full TRAIN task/reference inputs,
the nine-category material validator, distinct signing authorities and the
separate 180-review/evaluator allocation are unchanged. `known_headless_main_usage`
remains separate from ACP `known_main_usage`. All expected rubric targets remain
unknown, and no author assertion grants expert certification or VAL eligibility.

Diagnostic reviewers and evaluators use this producer through explicit worker
config v3 and `frozen-native-subscription-headless-deployment-v1`. Each call
freezes its full rendered request and output schema before launch. The receipt
pins that private descriptor, worker config, deployment, source files and exact
native profile. The independent reader checks those disk bytes before a reviewer
submission can be signed and consumed by the pilot. This signing identifies the
local review role; it does not certify an external model's identity or expertise.

This review policy retains its existing 60-second main timeout, output and input
caps, zero retries and separate maximum 180-main design. It explicitly requests
low reasoning effort. Missing materials remain in the 36-slot denominator and
create no callable request. A rejected binding, malformed review or source drift
closes further I/O while preserving its reservation, raw producer receipt and any
observed main usage. The headless accounting fields remain separate from ACP;
unknown launch counts, title usage and settlement remain unknown. The resulting
observation is diagnostic only and cannot grant calibration or VAL eligibility.

Review worker config v4 and headless deployment v2 explicitly opt into
`account_read_recovery={schema: headless-account-read-recovery-v1, max_attempts: 2}`.
Only this route accepts native receipt/reservation v2. The configuration is bound
to the native context, reservation, receipt and independent consumer; the budget
uses the frozen configuration to select the expected receipt version. A returned
receipt cannot select its own admission policy. Existing v3 keeps the v1 route.

Recovery applies to the read-only three-GET account snapshot, not the MAIN
generation. A transient account transport failure may start one new snapshot;
each attempt keeps its request prefix, received bytes and terminal failure.
Non-transient failures, observed policy/identity violations and stale preflight
observations do not permit a MAIN call. A postflight retry never repeats MAIN.
The reader checks the bounded attempt sequence and winning raw projection,
and the observer receipt anchors each attempt manifest. These are local
observations; they do not independently attest the upstream service's response.

Each new review batch retains previous reservations in its cumulative allocation,
including failed calls. Reduced per-role limits are reported separately from
the original study design. Reusing the same TRAIN materials in a new source
version produces correlated diagnostic observations, not independent samples.
This contract does not retroactively admit an incomplete earlier account record.

The retained startup-log comparison was refined on 2026-09-15 using the native
`ts`/`msg`/`ctx` fields. Both runs had fetched a real model catalogue and observed
an unexpired cached login. The failed material run last reported a long-running
`acp_initialize` phase; it never recorded the later eager-auth/session phases.
This narrows the logged location without identifying the blocked instruction or
proving absence of unlogged work. No new native or model request was made, and
the original timeout, unknown usage and unresolved materials are unchanged.
See the [retained observation and limits](../results/modular-engineering-20260915/headless-startup-location-r2/FINDING.md).
