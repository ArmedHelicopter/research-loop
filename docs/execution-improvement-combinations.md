# Execution policies with frozen improvement candidates

This version implements three distinct TRAIN designs: M7×M9, M8×M9 and
M7×M8×M9. M2 is fixed background in every target and optimizer history arm.
The effects are conditional on that background and the two realized candidates
within each design. They do not estimate unconditional singleton effects.

Each design executes two canonical history builds, labelled 00/01 for M9
off/on. All target arms with the same final M9 bit reuse the exact candidate.
The complete allocation is six executed builds, sixteen arm bindings (4+4+8),
and thirty-two target cells (8+8+16) across BLADE and DiscoveryBench. Six builds
and all sixteen reuse bindings freeze globally before any target operation.
Shared build costs are charged once within their design. Candidate variation
is not an uncontrolled target-policy factor. No candidate proposal is discarded
except the declared ordinary M9-off proposal: its fixed useful builder is used,
and its equally reserved proposal remains audited without entering the target.

M9 sees only bound, already observed TRAIN history. Its optimizer cannot see
target tasks, policy levels or scores. History and target task subjects are
disjoint; different tasks in one group are not claimed independent. M7 selects
two actual literal jobs under a two-job/two-cost budget: the common ordinary job
and either the second ordinary job or the admitted exploratory probe. M8-off
executes those same selected jobs serially. M8-on runs the actual bounded FIFO
scheduler with dependency/resource exclusion and a complete phase merge.
Ordinary jobs are identical across M8 levels. Both modes expose the same FIFO
public result shape. The immutable candidate, fixed qualified state and actual
selected job outputs enter the same two-slot solver, whose generated program
and original input mounts execute in restricted Docker.

The prospective allocation is 70 model calls (6 history proposals +64 target),
6 restricted builders, 76 independent source qualification calls (12 history
+64 target), 96 Docker opportunities (64 auxiliary +32 solver), 32 independent
primary process scores, and zero retrieval. The inherited history acquisition
is accounted separately. Two literal jobs/cost units, two target model slots,
context cap, timeout and Docker limits match within each design. Unknown model,
source or auxiliary execution costs preserve attempted/unused rows and block
future target I/O. Failed jobs retain their receipts and cannot reach the
solver. All target provider accounting seals before any score request.

Versioned execution-improvement panel provenance permits only its exact
history manifest; the default CombinationPanel contract remains unchanged.
The repaired exact candidate barrier and original provider ledger replay are
reused. Family replay additionally reconstructs qualified state, persistent
phase queue and event files, exact literal programs, original CSV/artifact
bindings, Docker argv/limits/mounts, original model requests/responses, public
joint context, and solver execution before issuing an independent score input.
These checks bind caller-frozen trusted engineering records; they are not an
attestation against replacing every trusted record and authority.

Pairs retain their registered interaction contrasts. The triple additionally
reports all seven normalized descriptive terms: M7, M8, M9, M7×M8, M7×M9,
M8×M9 and M7×M8×M9. Acceptance criteria freeze every coefficient before execution.
Each term sums signed cell means divided by 2^(n−component order), with
task/replicate means then equal group weighting. With one group per benchmark,
confidence intervals are null; no significance or causal efficacy is claimed.
For the triple, main coefficients are ±1/4, pair coefficients ±1/2 and triple
coefficients ±1. Pair interactions retain their ordinary ±1 scale.

Verification uses synthetic source/model/reference fixtures, real restricted
builders, real Docker and independent scorer processes. It covers complete
factorial accounting, actual container overlap, dependency/resource serial
execution, reversed completion with FIFO output, timeout removal, source
preflight, candidate/provider barriers, strict scorer scope, repaired hash-chain
attacks and failure/unknown denominators. There is no real generation, private
reference access or validation access. Q6.3, other triples, full and LOO remain
separate obligations; this slice does not prune or merge them. Earlier eleven-
build and six-build protocols and their original evidence remain immutable.
