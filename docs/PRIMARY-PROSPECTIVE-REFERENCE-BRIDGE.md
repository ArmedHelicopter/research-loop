# Primary prospective train reference bridge

The bridge accepts only explicitly pinned primary train public packets under the
new observed-family partition. It preserves the original inventory version and
new group/split identity. It does not manufacture a legacy custody store, change
the old 81-task protocol, relax the rubric, or create a validation entry point.

## Frozen behavior and verification contract

1. Validate the entire typed allowlist, train allocation, eligibility/holds,
   task digest and public packet declarations before reference content access.
2. Verify raw and canonical seal pins, original audit inputs, the existing export
   receipt, public file/CSV/receipt hashes and exact source selector. Rebuild the
   public projection from pinned source bytes and compare its complete task and
   CSV with the supplied packet before reading an answer or annotation.
3. Read references only through guarded paths, with all ancestor reparse checks,
   source locator and byte pins, and explicit Discovery answer-key descriptors.
   Parse each verified byte buffer through the existing reference parser.
4. Reserve each reference read and publication durably. Preserve failed/partial
   attempts in a hash-chained journal with fixed safe errors and zero external
   call cost. Recheck pins/eligibility before publication. Keep the scorer store
   separate from the source snapshot, solver packets, seal and journal.
5. Publish the unchanged frozen reference-store schema. Use the standard resolver
   and scorer worker in a real subprocess with synthetic references for both
   benchmarks. A successful fixture score is neither scientific evidence nor
   proof of an OS isolation boundary.

Required negative cases include validation/held allocation, wrong task/public
digest, selector drift, source drift, answer-key drift, reparse substitution,
partial publication, journal corruption and secret-bearing exceptions.

This implementation stage does not read actual answers or references. A later
actual preparation requires review of this contract and an exact four-train-item
request retaining the already frozen selection. No failed item may be replaced.
