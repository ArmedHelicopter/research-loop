# Grok profile lifecycle: read-only comparison r1

## Conclusion

The stale-copied-auth hypothesis is **contradicted for the recorded credential
file and recorded expiry state**, but it remains **possible only for unrecorded
external or in-memory lifecycle state**.  It is not a supported root cause for
the M4/M5 initialize stall.  No token value, user id, key suffix, refresh token,
or auth payload was emitted in this study.

## Credential-file and topology evidence

The source profile, the successful review-r2 slot, actual M4/M5 solver home,
initialize-only opaque input copy, and initialize-only runtime copy all have
the same `auth.json` SHA-256:
`19c1362081cc4f38eb589aec23e72b8101945d3b7abf74e29951f297c42d4988`.
Each is 1,768 bytes.  Their mtimes differ consistently with topology:

* review-r2 preparation creates a fresh per-slot `private_home` and uses
  `shutil.copyfile(source_auth, private_home/auth.json)`;
* actual M4/M5 preparation creates fresh `solver-home` and `evaluator-home`
  and likewise uses `shutil.copyfile`;
* initialize-only r1 copied the actual solver home into an opaque input and
  used `copytree(..., copy2)` from that input into a fresh runtime home.

Thus all three launches consumed byte-identical auth files.  Mtime is not an
auth freshness signal: `copyfile` creates a new destination timestamp, while
the opaque `copy2` diagnostic preserves the copied source timestamp.  The
actual M4/M5 runner did not reuse an earlier full Grok home; it built a fresh
role home and copied only auth before launch.  Review-r2 did the same per slot.

## Safe retained auth-state observations

For successful review-r2 at `2026-09-14T23:29:42.048Z`, actual M4/M5 at
`2026-09-15T02:00:33.389Z`, and initialize-only r1 at
`2026-09-15T02:24:42.723Z`, retained unified-log projections all say:

* disk reload `changed: false`;
* `has_current: true`, `is_expired: false`, and OIDC mode;
* cached-token presence true and two advertised methods.

Review-r2 then reached `startup complete` and `prompt received`.  Actual M4/M5
and initialize-only r1 stopped after auth-method selection.  This discriminates
the observed prefix despite identical copied auth bytes and safe state; it does
not identify a later unlogged operation.

## Saved source behavior and limits

The pinned public `acp_agent.rs` calls `force_reload_from_disk` during
initialize.  It awaits `silent_refresh()` only when there is no current auth
and that auth is expired.  The retained safe state has current auth and is not
expired, so this saved-source branch would not run.  It does not prove the
installed executable matches that source, nor does it establish that an
external service, machine-local cache, or process-global state was healthy.

The evidence therefore contradicts claims that an expired token, changed
on-disk auth, or a stale whole-home copy explains the observed stall.  A
one-time refresh state remains merely possible because its value and any remote
interaction were deliberately not read; timing alone is not evidence for it.

## One concrete supported-CLI repair path to prepare

Do not retry the closed M4/M5 allocation.  For any separately authorized future
diagnostic, use the supported direct CLI route with a **new per-attempt
`GROK_HOME` containing only a fresh opaque `copyfile` of the source `auth.json`
and the pinned config**, rather than copying a post-failure runtime home.  The
helper should record source/copy byte hashes, sizes, mtimes, safe post-init
flags, and durable launch/final process receipts; it must retain and join any
native execution session id.  It should stop at initialization or a fixed
constant request before creating an M4/M5 session or prompt.

This is a narrow profile-isolation diagnostic, not a user-approval or Daybreak
prerequisite, and it makes no claim that a refresh is required.  Its value is
to distinguish post-failure runtime-home contamination from the already
contradicted auth-file hypothesis without a blind full run.
