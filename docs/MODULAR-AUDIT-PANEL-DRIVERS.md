# Q2.3/Q2.4 audit panel drivers

`audit_panel_drivers.py` binds caller-supplied public task material, subject
binding, dual-audit material, and a controller-only independent check to the
frozen train scenario. The driver never creates a validator, signed receipt,
admission value, or independent source. A caller-owned restricted shadow port
must execute through the active `RunSession`; a caller-owned receipt port then
returns one immutable binding for the selected-material digest, task identity,
objective, shadow receipt, and both serialized audit payload digests. The driver
parses those payloads at the receipt boundary and checks their non-runtime body
fields against the frozen caller template before host verification.

Both M1-on and its offline shadow control keep fixed host parsing, receipt
authentication, task/execution binding, and dual-pair consistency checks active.
The control never disables a host guard or confers an unsafe execution
permission. Only M1-on calls `RunSession.admit`, which applies the
`EvidenceAdmission` disposition; M1-off records host-verified material as a
non-promoting frozen control. A common parser or pair rejection is recorded as a
P0 protection, not an M1-specific gain. The final candidate is always `unknown`;
a structurally admitted audit therefore does not promote a scientific result in
this train-only panel.

`same_wrong` retains caller-provided independent check material in controller
trace state. That material is absent from all model requests. Signature agreement
can authenticate the two configured issuers and still fail to establish
scientific correctness. These synthetic tests exercise engineering gates only;
they do not establish independent scientific authority or benchmark effects.
