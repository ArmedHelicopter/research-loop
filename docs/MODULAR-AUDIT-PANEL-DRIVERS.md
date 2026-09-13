# Q2.3/Q2.4 audit panel drivers

`audit_panel_drivers.py` binds caller-supplied public task material, subject
binding, dual-audit material, and a controller-only independent check to the
frozen train scenario. The driver never creates a validator, signed receipt,
admission value, or independent source. A caller-owned restricted shadow port
must execute through the active `RunSession`; a caller-owned receipt port then
returns exactly two frozen audit records for the active execution and objective.

Both M1-on and its offline shadow control keep `AuditVerifier` active. The
control never disables a host guard or confers an unsafe execution permission.
Every cell calls `RunSession.admit`, which invokes `AuditVerifier` and its
`EvidenceAdmission` gate, and then invokes the bounded final candidate path.
The final candidate is always `unknown`; a structurally admitted audit therefore
does not promote a scientific result in this train-only panel.

`same_wrong` retains caller-provided independent check material in controller
trace state. That material is absent from all model requests. Signature agreement
can authenticate the two configured issuers and still fail to establish
scientific correctness. These synthetic tests exercise engineering gates only;
they do not establish independent scientific authority or benchmark effects.
