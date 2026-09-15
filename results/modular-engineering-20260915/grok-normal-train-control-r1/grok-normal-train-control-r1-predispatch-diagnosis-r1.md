# Closed normal headless TRAIN control r1: pre-dispatch diagnosis

Read-only review; no rerun, modification, native call, or credential/account value output.

Closure SHA-256: `9158ce1633213dc34894ea95ab60c4ee3c2a3db3044a0e22ce48901e493e412f`.
Ledger SHA-256: `700a862da324fc751a8ec05f7532be9343e716b80b38848f998c2474f6c844b4`.

One reservation and one internal port opportunity were created. The local `inspect --json` child launched, exited 0, did not time out, and its owned tree closed. The prompt process was never launched: `prompt_process_launched` is false; native process, stream inspection, response, and known MAIN usage are absent. Title/all-opportunity totals remain unknown.

The sole observer fault is `account_preflight_failed`. The copied credential passed non-secret structural checks: one expected OIDC record, key/user-id shape, and parseable expiry. Its expiry was not more than 120 seconds in the future at the closed attempt. Recovery retained one terminal `ContractError`, with no request journal and no route. This pins failure before the first account GET and before model dispatch. It is not a network response, account value, model result, or prompt failure. Global auth metadata and source pins remained unchanged.

`_account_once` validates copied OIDC expiry before the first request record at `actual-m4m5-headless-runtime-r1/research_loop/modular/grok_headless_transport.py:240-248`. `_account_recovered` treats this `ContractError` as terminal without retry at lines 255-263. `run_headless_diagnostic` records `account_preflight_failed` before prompt processing at lines 440-450.

No source or safe-config correction is warranted. Do not weaken the 120-second rule, bypass account preflight, or reuse this reservation. The cheapest prospective correction is a legitimate credential refresh that makes a newly copied OIDC record pass the existing predicate, then a newly frozen and authorized control. It is not a retry of terminal r1.

## Correction to the earlier ACP/headless wording

The prior report correctly distinguished r2 ACP stdio wire framing from this CLI stream, but should not imply wholly separate implementations. The frozen normal transport imports `ProcessTree`, `diagnostic_config`, and `profile` from `grok_acp_transport.py` at lines 22-24. Its external command is a streaming-JSON CLI invocation with `--prompt-file`, `--json-schema`, one turn, and a session id at lines 298-307; it has no host-side ACP stdio `initialize` write. Source cannot show whether the binary internally shares initialization code. Thus r2 is relevant startup evidence, but neither r2 nor this pre-dispatch expiry failure proves the internal relationship.
