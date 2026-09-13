# State/improvement repaired-source integration review

The earlier review of 68dcfa8 missed a concrete duck-typed barrier bypass.
It remains preserved as the original review, together with the later finding.
This follow-up reviews e99ffb0's repair and its integrated form at 103ab6d.

The target driver now requires the exact CandidateBarrier before invoking its
replay method. That method requires the exact frozen plan, provider ledger and
tuple of exact BuildResult objects. Build replay independently requires the
exact ledger. The previously failing proxy regression now rejects corrupted
build material before score issuance, without making any new model, Docker or
scorer calls after its fixture.

The merged scorer retains the distinct history/target provenance of this panel
and the ordinary panel's exact training identity. Its family guards reject
state-improvement mixed with exploration or scheduling; the integrated test
also rejects wrong family scopes. All eleven original candidate builds remain
frozen before the 22 legal targets, and the target ledger seals before scoring.

The root's frozen run at 103ab6d closed with 27 passed, no failures, errors or
skips, and all 526 tracked source/document hashes unchanged. It includes the
full eleven-build/22-target Docker/process grid, proxy and rehashed order/limit
attacks, scorer scope checks, legacy prediction scorer and label isolation.
The source archive separately preserves eight earlier closures, including the
red regression. Its 95 distinct accumulated checks are not a fresh 95-test run
at the final source. These are synthetic engineering checks, not real model
improvement, independent-family transfer or scientific effectiveness evidence.
