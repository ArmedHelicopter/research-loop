# Grok 1.0.30 stdin-held versus EOF initialize-only A/B

The EOF hypothesis is not supported in this harness.  A held stdin open after
the one fixed `initialize` write; B closed stdin immediately after that same
write.  Both native runs timed out without a parsed response or any stdout or
stderr bytes.  This does not identify the upstream blocking point, and does
not prove that no more complex stdin/pipe interaction exists.

The synthetic EOF-dependent peer first established that the helper itself
distinguishes the planned intervention: held stdin timed out, while closed
stdin accepted the response, and both owned process trees closed cleanly.

| variant | stdin after write | elapsed seconds | response | stdout/stderr | cleanup |
| --- | --- | ---: | --- | --- | --- |
| A | held | 60.188 | none; timeout | 0 / 0 bytes | exit 0, true |
| B | closed | 60.265 | none; timeout | 0 / 0 bytes | exit 0, true |

Each native process wrote exactly one `initialize`; the recorded count for
`session/new`, `session/prompt`, authentication, billing, auto-topup and retry
paths is zero.  No model call was dispatched.  Settlement is deliberately
recorded as `unknown`, not zero.  The global auth file was opaque-copied into
fresh homes; its content was neither read nor hashed, and its public metadata
was unchanged after the pair.

The envelope was frozen before both native starts.  It pins the official exe
digest `ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266`,
driver/engine/peer, transport and isolation source files, and both factory
isolated configs.  The fixed 261-byte request digest was
`4ff2a6301d0f60b08451d890fb2bff5ee7067be81658cd46845e64bc1edac4dd` and is
also bound in each pre-launch reservation.  Both configs still matched their
frozen digests after shutdown.

Public evidence:

* `envelope.json` SHA-256 `d6cfffb41c95e8d2580d4fa41a37ac0665f9c585006bb1f6e36c03742f63c499`
* `closure.json` SHA-256 `da8444a4f357cbf5e0a2a9c90fc805b4bc43e4d1769ac2f8a7dc9eb239b85e30`
* `synthetic-helper.json` SHA-256 `7c5b7b19bd097c2e14a73d909ababa3182dfe01ba7321f817c49db1a55341818`
* `allowlisted-log-summary.json` exposes only fixed startup messages.  It saw
  `agent initialized` in A and B, and `auth update enrichment done` in A; it
  does not expose any other log fields.

Private raw protocol streams and the opaque copied auth files remain under the
variant private homes and are intentionally not included in this report.
