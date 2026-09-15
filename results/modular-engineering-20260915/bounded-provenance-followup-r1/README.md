# Bounded provenance follow-up checks

Merged account-freshness ROOT source a989a785 passed twelve checks: ten label
isolation checks, one actual synthetic producer/reader check, and a genuinely
delayed synthetic GET that still independently replayed. This is separate from
the earlier isolated 66-pass/one-timeout batch and its successful focused recheck.

Isolated C5 registration source bdbc01a6 passed fourteen checks. It retains the
exact authenticated selected-registration bytes and a task-neutral source-bound
sidecar. Registration reads back before returning; later verification reauthenticates
and rechecks originals. Missing sidecars can be completed only after fresh
authentication reconstructs the same target; differing originals are never overwritten,
and an already complete registration retains its FileExistsError behavior.

The C5 checks use an actual selected-snapshot projection but stub the expensive
upstream authentication call. They verify this storage adapter, including partial
write completion and tampering, not the complete 46-build/118-target controller.
That broader run remains separate and is not credited to these new source bytes.
Neither set makes real model/API calls or opens real VAL data.
