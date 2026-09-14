# Headless diagnostic receipt contract

`run_headless_diagnostic` receives the exclusive path
`directory/native-reservation.json`, creates it before I/O, and creates the
session UUID itself. It creates `grok-headless-diagnostic-receipt-v1`; it is
not an ACP receipt.  It binds the frozen prompt, schema, source manifest,
reservation, exact command, private raw stream and private account observations.
It reserves one main turn.  An initial title opportunity and all-opportunity
usage remain `null`; server-reported cost is retained only inside the stream
inspection and does not establish billing settlement.

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
