# Linked adapted scoring

`evaluation.modular.linked_scoring` is a train-only engineering component. It
replays the linked mechanism and solver journals before issuing a signed
`linked-benchmark-score-input-v1`. The signed input binds the frozen panel and
cell, identity, task, scenario, package, arm, objective, both trace digests,
analysis/program/answer digests, execution receipt, and exact program bytes.

The evaluator receives only an anonymous candidate containing analysis text,
the executed program, answer text, and a path-free execution feedback summary.
The panel, arm, package, mechanism roles, task handle, and local paths remain
outside that prompt in the signed envelope.

`LinkedAdaptedScoringService.score_linked` produces a signed adapted receipt
with metric value/direction/range/scale plus linked receipt and both trace
digests. Both the score input and receipt state `scientific_validity` and
`calibration` as `not_measured`. They are usable only for train-side adapted
measurement and selection; they do not alter the independent scientific or
validation acceptance gates.

The HMAC authorities model separate execution and scoring components in tests.
No independent process, protected-reference resolver, or evaluator deployment
is supplied by this repository.
