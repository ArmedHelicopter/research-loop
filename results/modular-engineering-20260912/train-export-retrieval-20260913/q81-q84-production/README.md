# Q8.1 / Q8.4 production engineering evidence

The main frozen integration suite ran source 30065f140262a96af92727c436e49ba8efac8942:
97 tests passed, including 64 complete controller cells (Q8.1:48, Q8.4:16),
128 fixture CodexModelPort calls, 60 caller-provider invocations from 192 total
opportunities, and 8 real Docker executions on the actual exported public CSVs.
DiscoveryBench and BLADE both use synthetic public train data; no real validation
or reference payloads were read. P0 and all factorial cells remain present.

Independent review corrected one metadata term after that suite completed.
Source f0a14e75f62ec026cf2cbf3773f72544c636ad2e uses
mechanistically_redundant_expected_null. Four valid arms make the conditional
M6 increment estimable; M2 already deduplicating creates an expected zero-increment
negative control, not design non-identifiability. Production code changed only
this string; byte replacement against the frozen source was mechanically checked.
All 21 bounded post-commit regressions passed, including 8 actual provider/M2
semantic cells over both provenance variants and all four arms, with no excluded
contrasts. The old annotation in the original frozen archive/authority is preserved
as historical evidence and superseded by this correction. It was never a mask.

FINAL-VERIFICATION.json records both source commits, every artifact hash, test
counts, denominators, retained failures, and limits. Source manifests contain
both worktree SHA256 and Git blob SHA256/OID. This result directory uses -text;
staged Git blobs are checked against the exact evidence bytes.

The first RED failed before export because the controller charged the union of
all stage slots to every variant. The second ran all 64 cells and 8 real Docker
executions, but independent verification rejected an aggregate output digest that
omitted intermediate responses. Corresponding changed runtime/grid source files,
full fixture directories, XMLs, and costs remain archived. The third successful
64-cell run is also retained. Across second/third/final main grids there were
24 real Docker executions; none are discarded from the execution history.

Source provenance admission uses the actual M2 EvidenceLedger in a dedicated
provenance ledger. Those admitted roots cannot become session scientific evidence;
P0 rejects a positive claim using them. Scientific independence, calibration,
reasoning quality, benchmark score gains, and programme completion are not proven.
Q8.5/Q8.6/Q8.7 remain outside this delivery and must be tracked separately.
