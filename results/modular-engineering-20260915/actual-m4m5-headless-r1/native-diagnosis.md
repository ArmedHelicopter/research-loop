# Actual M4/M5 headless native diagnosis r1

Date: 2026-09-15. This is a read-only diagnosis of the closed
`actual-m4m5-headless-run-r1` attempt. It did not retry a command, start a
model, perform a network request, or alter any runtime/original artifact.

## Observed failure chain

The first solver reservation launched `grok.exe` PID 44884 at
`2026-09-15T02:00:31.652938Z`. Its process record says `timed_out: true`,
`failure: process_tree_shutdown_failed`, `owned_tree_closed: true`, and final
exit code 0. Both captured process streams are empty. This is not a successful
native return: `_process_ok` also requires no timeout and no failure.

The transport source makes the ordering clear. `process_tree_shutdown_failed`
is set only *after* the initial `communicate(timeout=60)` has timed out and
the follow-up post-job-close `communicate(timeout=5)` also times out, or its
finally cleanup raises. It is therefore cleanup evidence following the stalled
call, not evidence that the job/pipe guard caused the initial stall. The live
PID did not exit immediately; it was still being waited on until the timeout
path. Its exit code 0 was observed after closure and cannot promote the call.

The native Grok log narrows the stall. Bootstrap completed: model fetch and
settings fetch completed in under one second, the model catalog worker was
spawned, and `agent initialized` was logged. The last state is
`startup phase running long` with phase `acp_initialize` open for 10.08s.
There is no later `auth started`, `connect finished`, `session created`,
`startup complete`, `prompt received`, or inference event. The 60-second
watchdog then terminated/closed the tree. The two-line memtrace contains only
the start/sample pair.

The closest successful review-r2 native call used the same executable, the
same-sized/hash-equal `config.toml`, an empty `active_sessions.json`, and an
empty `active_sessions.lock`. In that call, after `agent initialized`, the
log advanced through auth start/connect, session creation, startup complete,
prompt reception, inference start/done, and normal exit in about 20.6 seconds.
The failed call never reaches the first of those post-initialization entries.
Its `worktrees.db` was created/updated, so this is later than basic private
home creation but before a session is created.

## Diagnosis boundary

The evidence supports a native process stalled in Grok's ACP initialization,
after local bootstrap and before authenticated connect/session/prompt work.
It does **not** identify a precise internal ACP sub-operation: the retained
log ends at the watchdog warning and has no stack/error/terminal event.
It also does **not** establish zero external network/model activity. There is
no model inference or native usage record, and pre/post account observations
did not supply a settled per-call model usage; that leaves external activity
unknown rather than zero.

The job/pipe result is a secondary symptom: a parent process retained an open
pipe or otherwise failed to finish within the post-termination grace period.
The available evidence cannot distinguish a child retaining the inherited
pipe from another shutdown delay, and it does not show a pre-timeout job
assignment failure.

## Preservation and raw evidence

* Runtime checkout: `E:/_ryanDev/AI/research-loop-modular/actual-m4m5-headless-runtime-r1`,
  commit `2113371268b30411712273623371cbcf49e0ccc8`.
* Failed process record: `.../solver-model/calls/0001-m4_plan/native/process.json`,
  SHA-256 `9231A95D95B20C8F214DDA832884F893924F564C1EB5EE6FD8D3E05AAEF68C6D`.
* Private observer receipt and mirrored native receipt: SHA-256
  `8EA9301365DDEF2C71247F584A5E67720078F4A5593C8453D69F1DE28999BC2F`.
* Failed native unified log: `.../native-home/logs/unified.jsonl`, SHA-256
  `F48C1A82E83E1B3714366D2CCD579126CE0434D514F5C2CD83E1A98B93B4326B`.
* Failed memtrace: `.../native-home/memtrace/1789437632-44884.jsonl`, SHA-256
  `3832622E89AD6F470FFE4309E62722B88DB4C2A236C0DB69FFFBA8CCCD93C624`.
* Transport source hashes: `grok_headless_transport.py`
  `11D385AAD11EB8772CBDEBFDA8FDBA8BB189B34FB7F010EA4C3DCDA610EC9F34`;
  `grok_acp_transport.py`
  `F736D68218E49BF90FA6EAD447097D8366D3827932BEA5565C854E71D07AA855`.
* Successful comparison process: `work/headless-review-run-r2/review.private.jsonl.headless/0758dc2a5487a274516af9cb33bcc86d829c9eb9bb2f06337e0f3eefccdc4bf6/native/process.json`,
  PID 52912, no timeout/failure; its corresponding private-home unified log
  SHA-256 is `9D6A6071FF7B28C6FE1C0F35F8AA670B7AB63D53407854E7E4E0CF04A5BB41E3`.
