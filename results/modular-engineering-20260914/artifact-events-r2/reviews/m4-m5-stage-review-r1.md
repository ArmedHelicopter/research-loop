# M4/M5 stage review r1 (read only)

Reviewed `artifact-evidence-provenance` at `8e692a1` without edits or test
execution. This is an engineering-provenance review, not an acceptance claim.

## Findings

### P1: a C4 reveal trace does not require its actual `reveal_output` descriptor

`_verify_m4_m5_artifacts` collects reveal descriptors but only reports their
count (`research_loop/modular/m4_m5_artifacts.py:172-186, 227-230`). It then
calls `_check_c4_reveals` with source journal rows alone (`:222-226`). The
helper accepts a C4 reveal when its submission list equals any complete review
assembled from the *entire final* `reviews.jsonl` (`:249-266`). Therefore an
attacker who coherently rehashes/reseals the catalogue can remove the one
`reveal_output` descriptor while retaining a `c4_review_reveal` trace, and the
verifier still accepts. The trace has no reviewed descriptor binding.

Minimal repair: retain descriptor position while walking `all_descriptors` and
build a map of validated reveal descriptors keyed by their actual output
(`review_id` plus ordered submissions). For every C4 reveal trace, require
exactly one matching `reveal_output` descriptor that occurs earlier in the
catalogue; require the reveal descriptor's three causal parents to be the
already-seen M5 submission descriptors for that review. Consume the match, so
one output cannot satisfy two reveal traces.

### P1: reveal validation uses the final source-journal state, not the state at the trace

`_check_c4_reveals` first builds `roles`, `submitted`, and `submissions` from
all review journal events and only then iterates traces
(`research_loop/modular/m4_m5_artifacts.py:249-266`). It does not use the
catalogue position, the ordered M5 artifact descriptors, or the output observer
position. A coherently rebuilt catalogue can move a C4 reveal trace before the
submission descriptors (or make a trace refer to a later complete review) and
still pass because the helper sees the final two submissions. This is exactly
the chronology distinction the observer was added to preserve.

Minimal repair: remove the final-state matching helper from the acceptance path.
During the single catalogue walk, maintain per-review submitted descriptor
state. Validate an output descriptor only against submissions already seen;
when a `c4_review_reveal` trace appears, bind it to one already-validated output
descriptor with the same ordered tuple. Do not derive a reveal from raw source
journal state after the walk.

### P2: M4/M5 verification does not authenticate the trace-artifact parent chain

The verifier obtains the lock payload from the first trace descriptor
(`research_loop/modular/m4_m5_artifacts.py:154-161`) and uses only the most
recent trace descriptor digest as the implicit M4/M5 parent (`:166-171,
195-215`). It never verifies the trace descriptor parents themselves. The
generic catalogue allows any prior descriptor as a parent, so a coherently
rehashed/resealed arbitrary root parent on an original trace can remain
accepted if subsequent M4/M5 parent rewrites point to that trace digest.

Minimal repair: before using trace descriptors, verify the trace stream itself:
the first original lock trace must have no parents and each subsequent trace
must have exactly the immediately preceding trace descriptor as its sole parent.
If legitimate non-trace descriptors may interleave, compare against the prior
trace digest rather than catalogue adjacency. This makes arbitrary root-parent
rewrites reject without changing runtime producer behavior.

## Focused regression tests

1. Produce a real C4 reveal trace and output, delete only `reveal_output`,
   coherently rebuild catalogue hashes/seal, and assert verification rejects.
2. Coherently rebuild so `c4_review_reveal` occurs before its M5 submission
   descriptors (or bind it to a later review with equal final rows); assert
   rejection even though `ReviewEngine` can replay final `reviews.jsonl`.
3. Duplicate one valid reveal output and add/bind two C4 traces; assert a
   one-to-one output/trace requirement rejects reuse. Also reject a trace whose
   ordered submission tuple differs by role order or response bytes after all
   hashes are recomputed.
4. Coherently add a prior arbitrary descriptor as the lock trace parent, update
   the trace/M4M5 descriptor chain and seal, and assert the trace-parent check
   rejects.

Existing tests exercise raw source journal rehash/order/duplicates
(`tests/test_m4_m5_artifacts.py:54-67`) and task identity (`:97-130`), but do
not create a C4 trace and attack its bridge output or descriptor chronology.
