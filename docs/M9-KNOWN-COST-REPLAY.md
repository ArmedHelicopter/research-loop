# M9 source cost consistency during replay

M9 build and target runtimes stop when a source qualification has unknown
realized cost. Successful replay must apply the same stop rule before accepting
the build or issuing a target score input. A provenance signature alone does
not establish known cost.

The first frozen checkpoint73477f8 reproduced nine coherent counterexamples:
three state/M9 targets, three mechanism/M9 targets, the M6/M9 corpus and two
canonical history builds. Each source response was re-signed with unknown cost;
its trace binding and hash chain were updated. Build cases also updated the
original file hash inventory. Generic source/trace replay passed, seven target
score inputs were issued and both canonical builds were accepted. The replay
attacks made no new model, source or Docker calls. All original and altered
records are preserved separately; initial normal fixtures performed46 target
Docker executions and46 independent process scores before these attacks.

The repair repeats the existing stop rule in canonical verify_build and in
state/mechanism target replay, including the separately qualified M6 corpus.
DualMaterialVerifier retains its broader verified-but-unknown contract for
other experiment families; no global provenance policy was tightened.

The repaired checkpoint exercises both full normal grids with17 canonical
builders,133 scripted model calls,142 source qualifications,24 retrieval
operations,46 target Docker executions and46 process scores, followed by the
same nine coherent attacks. Two prior-history fixtures each add two scripted
model calls and one Docker execution, recorded separately. Label checks and
the original canonical/state/mechanism unknown-cost stop cases accompany this
checkpoint. The exact test closure and source hashes determine completion;
this description does not turn an active checkpoint into a passing result.

These are synthetic engineering checks. They do not establish scientific
qualification, benchmark improvement, real usage costs or validation acceptance.
