# Linked public mechanism projection

`verified_mechanism_provenance` remains a controller and scorer artifact.  It
contains the complete cell binding, arm, package binding, stage trace, and model
request/response pairs required for replay.

`project_linked_public_context` derives the only predecessor record exposed to a
linked solver.  Its closed schema is `linked-public-mechanism-context-v1` and
contains an opaque panel-cell digest, identity/task/scenario digests, the full
provenance digest, the final mechanism candidate, and one typed mechanism
material record:

- Q1.5: public evidence, historical summary, and sealed review responses when
  the barrier actually completed; otherwise the same material schema contains
  an explicit null review.
- Q3.1: the frozen, stage-bound operational prediction plan, or an explicit null
  plan when the actual stage has no M4 plan.
- Q4.3: revealed initial and revision review responses when the sealed review
  completed; otherwise the same material schema contains an explicit null review.

The projection never carries an arm, variant, cell key, package, mechanism-stage
label, controller input, or predecessor model request.  It is reconstructed from
complete provenance for every verification; fabricated fields, missing actual
stage material, request/response digest mismatches, and stage/arm inconsistencies
are rejected.  This is an
engineering provenance boundary and does not measure scientific effect.
