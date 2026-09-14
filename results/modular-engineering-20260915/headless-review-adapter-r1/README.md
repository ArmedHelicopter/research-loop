# Headless diagnostic review consumption

The explicit v3 diagnostic worker now carries native Grok headless receipts
through the reviewer/evaluator ports, budget ledger and pilot. Each dynamic
request, worker config and deployment is pinned before consumption. Binding
or review rejection retains the original raw receipt and observed usage, then
closes further I/O. Unknown title and settlement fields remain unknown.

The frozen integrated source `a334cd63fbb61f767b34656bb10844ac0d73e692` passed
132 checks in 162.234 seconds, with 755 source/document files unchanged.
The [original closure](root-frozen-originals/headless-review-adapter-root-r1-closed.json),
[JUnit report](root-frozen-originals/headless-review-adapter-root-r1.xml) and
[exact source archive](root-frozen-originals/headless-review-adapter-root-r1-sources.zip)
cover the native synthetic producer, real private port/pilot consumer,
legacy subscription, schema validation, authoring and label isolation.

Four selected isolated journal archives contain 96 original members in total:
a consumed positive review, a rejected binding, an actual on-disk private
request mutation and a rejected semantic target. Each ZIP has a member hash
inventory. They are engineering cases, not independent scientific samples.
No real model call or VAL access occurred in these tests. Native account
responses in the selected archives are synthetic; auth and signing keys are
excluded. The isolated run has no retained JUnit/stdout record; its reported
five passing checks are not counted in addition to the integrated 132.

The partial commits and earlier failing test remain in Git history. The final
integrated code/test bytes agree with isolated `afb118ba`; the strict positive
assertion was retained when resolving the intervening test conflict.

[Stage manifest](stage-manifest.json) records original paths, versions, file
hashes and exclusions. Real TRAIN review execution is a separate run with
its own frozen manifest; this archive grants no calibration or VAL eligibility.
