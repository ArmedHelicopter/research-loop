This directory preserves immutable evidence from four frozen C4 checks.  The
`c4-frozen-runs-evidence.zip` archive contains the original runner metadata,
source snapshots, JUnit reports, and native-run receipts.  Its companion
manifest records original absolute source paths, byte lengths, and SHA-256
values; the validation record re-hashes every archived member.

`61fea55-success` is the historical normal-success check.  The two following
final-drift runs are retained as assertion-only failures caused by an obsolete
`provider_calls` assertion.  `1892f17-final-drift-pass` passed only the
corrected final-accounting-drift regression: it preserves 22 historical scores
while current eligibility is false.  It is not a re-run of the normal-success
assertion.
