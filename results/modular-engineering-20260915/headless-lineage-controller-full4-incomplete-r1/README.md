# Four-panel lineage run: incomplete evidence

The original synthetic integration invocation used source `051b6a82a2f0b61d17b88a419a190652a71b424a`.
Its last persisted controller state contains all 34 planned cells: 32 succeeded,
one running, and one not started, with 32 scorer calls. No final evaluator gate,
JUnit, or original-process exit receipt was produced. This is not a passing full-grid test.

PID 54260 was observed live at 11:16 on 2026-09-15 (+08), then absent at the next
inspection; the native observer session was also unavailable. The reason and exit
code are unknown. The first observer's timeout and code 259 mean the process was
still active at that earlier observation. They do not describe the test's exit.
No run was restarted or terminated for this archival step.

`public-metadata.zip` preserves the original controller prefix, available earlier
failure reports, observer scripts and original observation receipt. The initial
interruption audit scoped its file count incorrectly; the additive `audit-r2`
file records the existing empty top-level log and the earlier observer timeout.
Both audits are retained without rewriting the original evidence.

`source-exact.zip` contains 776 tracked Python/Markdown files as read after the
interruption. There is no pre-run source manifest; unchanged source throughout
the original run is not claimed. The manifest identifies the source version,
every archive member and original path, and before/after byte and mtime checks.

The private archive retains 6,188 non-credential files at
`E:/_ryanDev/AI/research-loop-modular/retained-private-evidence/headless-lineage-controller-full4-incomplete-r1/retained-private.zip`.
Credential-shaped files and reparse paths are excluded and listed. Published
read-back checks verify archive membership, CRC, per-member bytes, and unchanged
original bytes/mtime. This is preservation evidence, not a semantic replay of
the unfinished controller or proof of scientific validity.

The separately closed 20-check lineage gate suite remains valid within its
reported scope. Full four-panel completion, real benchmark effects, and VAL
acceptance remain unestablished by this invocation. The planned module,
single-module and combination coverage is unchanged.
