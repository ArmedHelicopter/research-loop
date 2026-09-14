# Grok 1.0.30 initialization evidence

Both one-shot, 60-second initialize-only runs timed out with zero received
frames. Each wrote one initialize request and no session, authentication,
account or model-prompt request. Original public closures and post-run pin
verification are retained. Cleanup completed and the global executable stayed
unchanged. No model readiness, successful research run or settled zero-charge
claim follows from these observations.

The second run changed both recorded completion caps from 8192 to 128 while
retaining the reviewed protocol engine and executable. Initialization still
timed out. Time, paths, network and account/cache state were not controlled;
this observation does not establish causal independence from the cap. The
private auth copy's metadata changed during that run; global auth metadata did
not. Neither auth bodies nor auth hashes were inspected or archived.

Passive diagnostics and original source/config pins are included by explicit
allowlist. Auth files, memtrace contents, raw runtime logs, credentials and the
150 MB executable are excluded. Its locally measured hash identifies the
download; it is not an official release checksum. The installed global CLI
was not upgraded.

The original safe index contains a legacy field named
historical_success_command_envelope pointing to a HEADLESS subscription smoke.
That original field is retained as provenance, not ACP readiness evidence.
The earlier successful ACP run is the separately preserved
grok-acp-two-opportunity-smoke-r3. The passive correlation finding identifies
the ACP run it actually compares. No new startup cause is established.
