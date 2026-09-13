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

## Concrete API

`PrimaryReferenceItem` binds one `PrimaryTrainExportItem` to the task canonical
digest and raw public-envelope, CSV and packet-receipt hashes. The caller supplies
the separately pinned original export receipt when constructing
`PrimaryProspectiveReferenceBridge`. Its `prepare(requests, packets)` returns the
unchanged `train-reference-publication-v1` metadata and opaque handles.

The bridge calls the prospective exporter's allocation and source-verification
contracts directly; it does not call its export operation again. The original
public export is immutable. A caller may prepare a strict subset of a pinned
export, but every requested member must pass the same full source/hold checks.

`reference_store._discovery` and `_blade` accept an optional bound-byte reader.
Legacy callers keep their existing default. `publish_train_reference_records`
only serializes already authorized train records; it grants no source access.
The bridge invokes the unchanged `FrozenTrainReferenceResolver` on its staged
store before final publication. No scorer-process or rubric source is changed.

`references.jsonl` retains each attempt, source verification, reserved reference
read, reserved publication and terminal result. Source inventory/audit verification
may hash reference-file bytes without interpreting them; the per-member read
reservation refers to semantic reference extraction. A damaged journal is left
unchanged and rejected. An interrupted reservation remains unresolved; this is
not a claim that all OS reads are captured by the journal.

## Evidence scope and actual four-task preflight

The subprocess fixture feeds explicitly synthetic signed candidate inputs to the
standard scorer worker. It performs no solver/model/Docker run. Its independent
canned evaluator checks that the correct benchmark reference and public question
reached its prompt and that an unallocated reference did not. Two successful
fixture calls establish wiring only, not scientific validity or calibration.

The actual four-task plan is recorded outside the tree at
`work/primary-reference-checks/actual-four-train-reference-plan-r1.json`, SHA256
`5e6a79bc55c1385b25f7eb73b61381adffb1a085d6a20b0c9ea68931e7208818`.
It rechecks the four existing public envelope/CSV/receipt byte pins and preserves
the original selection. No actual answer or reference was opened. The next
preparation additionally needs reviewed exact Discovery answer-key path/hash/
encoding descriptors and explicit root authorization after contract review.
BLADE annotation paths remain bound to the inventory and source audit; there is
no loose filename lookup or new allocation.

The original failing source-to-resolver test is preserved as `red-r1.xml`.
Development run `boundary-r3.xml` reported 24 passing checks, but source was edited
while that process was active. Its source-change receipt records process session
25716, the JUnit interval, file modification time and before/after source hashes
(the before image is explicitly reconstructed from the edit). That run is invalid
for frozen verification. Full final checks are rerun after a source commit.

## Frozen delivery

Source commit `574bfbf19837fac73ae4d464a67374b907b89d3d` passed 125 related
checks, with zero failures/errors/skips in 686.443 seconds. All 261 tracked
Python source/test files had identical hashes before and after the run. The
new bridge's standard scorer subprocess completed two synthetic calls, one per
benchmark, with zero failed fixture calls and no model/network/Docker calls.
The JUnit SHA256 is
`3962344becb69cdbaf23ff9435afe11d6bcade125110986388981d6f5474418f`.
See `primary-reference-bridge-verification.json` for raw report paths, retained
failure evidence, per-attempt reference journals and source pins.

The original four-task plan remains unchanged. Its independent descriptor
supplement at `work/primary-reference-checks/actual-four-train-reference-descriptor-r2.json`
has SHA256 `53b849053d87eb81565c16440f53c2460f800e9bdbbc1e0d568ee47445669f3e`.
The archived custodian script declares `synth`, `cp1252`, and answer-key SHA256
`afd51d7053cefff6b335c209a42a1943217cb73a9fd36144a500cce49ecda675`.
The archived status/publication/reference manifest agree with that descriptor,
the snapshot root, original custody pin, and both selected `synth/test` tasks.
Only the answer path's existence/size was inspected; its content was not read or
rehashed. Fresh byte verification remains a prerequisite inside the later
authorized preparation. Actual private reference preparation has not run.
