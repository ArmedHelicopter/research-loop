# Read-only pilot review and dispositions

Terra / medium reviewed domain_pilot.py, quota_check.py and existing runtime before the first client dispatch. No reviewer model experiment, scorer or core edit was performed.

- Verified M2 refresh and M3 context creation precede actual CLI invocation; per-call ledgers and prompt are saved before I/O.
- Execution receipts use admitted=True for model visibility. They do not pass the scientific RunSession.admit gate. Claims assert only recorded execution status; payloads explicitly state scientific_validated=false and scope; final outcome is unknown. Do not promote these roots as scientific findings.
- CLI quota query does not independently identify the desktop account. User explicitly confirmed account binding; remaining uncertainty is recorded. The client forces ChatGPT login, ignores user provider configuration and removes OPENAI_API_KEY/CODEX_API_KEY from its environment. No direct inference API is invoked.
- Reviewer noted the missing global serial lock. A nonblocking Windows file lock was added before dispatch. Each frozen opportunity directory is exclusive and cannot be silently reused. Slots and source hashes are checked before invocation.

Subsequent integration: legacy label-isolation tests passed 10/10 in a separate verifier fixture tree; solver checkout still lacks data/labels. Two initial offline fixtures failed on unused AuditVerifier constructor arguments and were retained. Third fixture completed with a substituted CLI transport and real Docker/runtime; it is not a model trajectory.

First live opportunity exposed a classifier error: an error-typed CLI item was a skill-description truncation notice, not a tool. The old opportunity remains failed. Subsequent protocol explicitly accepts only that known diagnostic; other diagnostics or tool item types fail closed. This is an execution correction, not a scientific criterion adjustment.
