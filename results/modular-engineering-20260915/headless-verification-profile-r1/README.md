# Headless verification-profile archive r1

This package preserves closed verification/profile evidence. It contains no credential payloads. The three input manifests are retained only in the private ZIP because each contains 176 summary rows for `auth.json`/`*.key` paths; their contents are not copied into this public staging directory.

The original setup receipt is retained as historical evidence: it remains `setup_rejected_before_full_replay`. Its correction is additive: the original `originals_unchanged_after_rejected_attempt: false` resulted from JSON numeric precision loss for nanosecond mtimes, while the correction records byte/mtime and decoded-JSON equality across 6,655 files. The rejection is not reclassified as success.

The replay summary records 136 persisted-call replays in 1.619 seconds. This is a closed full5 verification-profile observation, **not** a C5 duration estimate. The replay itself reports unchanged originals. The public audit records repeated validation structure; it is evidence and a proposed bounded repair only.

`pstats-summary.json` is a metadata summary of the retained private pstats file. `private-zip-members.json` provides member hashes, sizes, and CRC32 values without copying sensitive input manifests publicly.
