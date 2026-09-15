# Bounded account freshness repair

The three sequential account GETs can each use a ten-second transport timeout.
The former five-second oldest-observation guard rejected two real observations
before model dispatch in the separately retained M4/M5 r2 attempt. This source
records a 35-second maximum age in each new reservation, checks it before launch,
and independently requires that exact frozen value during replay. Zero-paid
fallback checks, at most two account-read attempts, and no MAIN retry remain.
Original failed runs retain their original source, policy, ledger and conclusion.

The frozen 67-check batch passed 66 and failed one first synthetic inspect at
its unchanged ten-second timeout, before any model dispatch. The exact same source
then passed a focused rerun of that single producer/reader test. The full failed
report is retained and is not relabeled as an uninterrupted 67-test pass.
The genuine six-second synthetic GET delay test passed in the first batch and
independently replayed; changing the recorded bound and coherently rehashing it
was rejected. All checks use synthetic accounts/models and do not open real VAL.
