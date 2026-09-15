# Grok next discriminating diagnostic r1

## Scope and answer

This is a read-only review of closed evidence.  No Grok process, account,
network service, model, Docker operation, credential, or retry was used.

There is **one** materially different initialize-only observation worth doing
if native troubleshooting resumes: run the existing single-`initialize` ACP
request with the frozen M4/M5 isolation and no-tools controls, while adding the
documented `GROK_LOG_FILE` diagnostic sink in a new private root.  It tests the
specific hypothesis that the observed post-catalogue wait is inside an
unrecorded native startup operation, rather than merely repeating a
configuration, cached-auth, completion-cap, or stdin experiment.  It is an
instrumentation probe, not a repair and not a substitute for a direct headless
MAIN run.

The saved 1.0.30 README documents `grok agent stdio`, `GROK_LOG_FILE`, and
`RUST_LOG`; `GROK_LOG_FILE` is a literal path and its file log honors
`RUST_LOG`.  Thus this proposal adds no guessed flag or unsupported mode.  The
source/readme is not an attestation that the installed binary's internals are
identical, so the retained executable hash and a pre-launch `--help` receipt
must still be pinned.

## Already executed observations

| Evidence | Intervention and outcome | What it rules in or out |
| --- | --- | --- |
| `grok-initialize-wct-archive-r1` | One 1.0.30 ACP `initialize` produced a protocol-1 response after 29.844 s; later notifications made the unchanged strict engine reject the diagnostic.  No session, prompt, auth, billing, or top-up RPC was sent. | A response is possible with this pinned executable, but the changing time/path/cache context means it is not a causal control. |
| `grok-130-initialize-safe-archive-r1` | Two authenticated one-shot runs, including a completion-cap 128 variant, each timed out at about 60 s with no frame. | Completion-cap change did not produce a response; it was not a controlled explanation. |
| `grok130-authless-initialize-r1` | A fresh home without a supplied auth file also timed out at 60.171 s; exactly one initialize and a joined owned process tree were retained. | Cached-auth presence is not required for the stall.  It does not prove anything about account state or billing settlement. |
| `grok130-initialize-config-ab-r2` | Both 918-byte and 2,719-byte frozen config variants timed out at about 60 s after auth/catalogue/enrichment milestones; both owned process trees were joined and closed. | The tested config shape does not explain the absence of a response. |
| `grok130-initialize-stdin-ab-public-r1` | Holding stdin open and closing it immediately after the one initialize write both timed out at about 60 s, with no stdout/stderr.  The synthetic peer confirmed that the harness distinguished the two modes. | The simple EOF/held-stdin hypothesis is not supported. |
| original initialize-only r1 | Its nested native-session return was not retained.  The original incomplete receipt is historical evidence only. | It must not be treated as a completed/cleanly closed trial, and its missing join does **not** show that the tool failed to return a session.  A yield boundary does not terminate a child. |

The closed M4/M5 call and the successful review-r2 call used the same retained
option-name set and environment-key set, yet diverged inside ACP initialization
before prompt receipt.  M4/M5 recorded `agent initialized` then an open
`acp_initialize`; the later config A/B runs reached model-catalog notifications
and auth enrichment but still emitted no ACP response.  The current production
headless transport is a direct prompt-file/streaming-JSON transport, not an ACP
initialize-only transport.  Therefore an ACP result can localize startup only;
it cannot prove that a direct MAIN prompt will succeed.

## The only proposed native probe

Use a fresh diagnostic-owned root and the pinned 1.0.30 executable.  Preserve
the fixed 261-byte JSON-RPC `initialize` line, `agent stdio`, frozen M4/M5
cwd/home/profile/no-tools configuration, one write, held stdin, and the prior
60-second cap.  Change only this diagnostic output:

```text
GROK_LOG_FILE=<fresh-private-root>\\native-startup.log
RUST_LOG=debug
```

Keep the log private: it can contain account-adjacent implementation details.
Publish only an allowlisted phase table (first/last timestamp and line count
per subsystem), byte/hash/mtime, response presence, process identity/creation
time, exit code, and the exact joined-session receipt.  Never publish raw log
text, auth data, prompts, or environment values.  The harness must retain the
full `exec_command` result; if it receives a `session_id`, it must join it with
`write_stdin` before recording closure.  `yield_time_ms` is only a yield
boundary, never an execution-timeout inference.

**Discriminating result.**  A final log event following catalogue notification
with no response identifies the named native suboperation as the next
source/local target.  A response with the same sequence isolates missing
observability as the difference.  A timeout with no additional phase does not
justify another configuration/auth/stdin rerun; it leaves the specific inner
operation unknown.  All three outcomes keep usage and settlement `unknown`.

This probe creates no `session/new`, `session/prompt`, scoring, evaluator, or
model call.  It must reject any unexpected outbound method, additional launch,
or uncontrolled child and stop without retry.

## Why no other initialize-only retry is recommended

The existing trials already cover cached-auth absence, two frozen configs,
completion cap, and stdin EOF.  Repeating any of those merely adds another
time/path/account-state sample.  Changing to `-p`, `models`, `inspect`, a
different auth route, or an API key would no longer be this bounded ACP
initialization experiment and cannot be presented as a recovery of the main
subscription-gated transport.

If the private logging probe is not acceptable, the next implementable action
is local-only: extract an ordered, allowlisted event timeline around the old
successful `model catalog: notifying clients` events and the M4/M5 pre-prompt
gap from their closed logs.  That analysis has not identified an inner awaited
operation and should precede any duplicate native launch.

## Read inputs and pins

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `WORK/grok-success-failure-context-comparison-r1.md` | 5,912 | `c6a0c52ab2ec86c07fee7e8b9ffbcbe467882eead3200ac4d5b37e75687d3f54` |
| `WORK/grok130-initialize-config-ab-r2/closure.json` | 8,015 | `03720a6f01e76d81b6bbbd6720ced5e32f076070fb64804abbd5088f504f8df8` |
| `WORK/grok130-initialize-stdin-ab-public-r1/closure.json` | 2,587 | `da8444a4f357cbf5e0a2a9c90fc805b4bc43e4d1769ac2f8a7dc9eb239b85e30` |
| `WORK/grok130-authless-initialize-r1/closure.json` | 1,459 | `bcf04278f8309b6d012fe28eedf1f503491aae107b2fb933647ebd3435ae7ddd` |
| `WORK/grok-initialize-wct-archive-r1/public-verification.json` | 541 | `e3b5822ebb874f0ecb4c8da0edf7c4917c8fb2310a1d4910eebc8130447a722c` |
| `WORK/grok-post-auth-initialize-readonly-r1.md` | 2,803 | `a043a91ba7f0b773d68cff704bb27cd0aa934832be649358d11f3df68d20d697` |
| `artifact-evidence-provenance/research_loop/modular/grok_headless_transport.py` | 44,885 | `11d385aad11eb8772cbdebfda8fdba8bb189b34fb7f010ea4c3dcda610ec9f34` |

The first six retained files were read without opening credential payloads or
raw private protocol frames.  The transport source was read only to establish
the direct-headless/ACP boundary.  Source and input mtimes were not modified.
