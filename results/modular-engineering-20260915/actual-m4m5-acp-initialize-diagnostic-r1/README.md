# ACP initialize-only diagnostic archive

## Correction controls interpretation

`wrapper-receipt-audit-r2-correction.md` is controlling: the nested native `exec_command` result was dropped because the orchestration emitted only `r.output`. No session id was retained. A yield boundary is not process termination; launch cleanup, exit, timeout, and settlement are unproven.

`RESULT.md` and `receipt.incomplete.json` are preserved historical evidence and contain earlier wrapper-timeout/ended wording. They are explicitly superseded for interpretation by correction r2 and are not rewritten.

The archive contains no retry. Usage and settlement remain unknown.
