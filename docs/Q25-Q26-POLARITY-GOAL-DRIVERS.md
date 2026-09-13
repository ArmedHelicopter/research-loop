# Q2.5 and Q2.6 train-only driver boundary

Q2.5 and Q2.6 accept one typed caller bundle for each public task.  Every
item carries source-bound public material and two `host-material-audit-v1`
authority receipts.  Each receipt signs the task identity, a digest of the
exact public material, the reported scientific state and outcome, execution
status, and the registered audit checklist.  The driver verifies both receipts
with the configured `AuditVerifier` before calling the model.  A caller flag,
an `admitted` field, or a self-reported validator result is not accepted.

Both arms perform this authentication as a fixed host protection.  The M1-on
arm then calls `EvidenceAdmission.decide` with the model's actual assessment
and the verified receipt facts.  It permits a non-unknown final candidate only
when the model assessment exactly matches an admitted receipt.  M1-off records
the verified receipt and assessment but does not call the admission gate.

For Q2.6, the assessment must also state the objective digest it would retain.
M1-on permits a non-unknown candidate only when that digest equals the
caller-frozen session objective.  A secondary or late-pivot response is still
called and retained, then rejected after the matched second call; the M1-off
control retains the same model response for the ordinary RunSession final
gate.  No source material, receipt, arm identifier, variant name, or controller
truth marker is put in a model request.

These are train-only engineering traces.  They do not execute the public
material in this session and do not establish scientific validity, independent
evaluation, or effectiveness.
