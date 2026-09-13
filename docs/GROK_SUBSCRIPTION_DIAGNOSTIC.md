# Included-subscription diagnostic bridge

`four-train-diagnostic-included-subscription-v1` is an explicit prospective
diagnostic contract. The historical `four-train-diagnostic-calibration-v1`
continues to require positive reliable monetary/token quotes and exact main
HTTP accounting. No zero tariff, dummy tokenizer, Codex type or translated
Codex event is supplied by this bridge.

The fixed grid has four TRAIN identities, two per primary benchmark, nine
material kinds per identity, 36 material slots, up to 108 reviewer/arbitrator
main prompts, and 72 evaluator main prompts. Every admitted main opportunity
also reserves one possible initial title opportunity: the complete grid allows
at most 180 main plus 180 title opportunities. A smaller explicit global cap
can stop execution earlier without removing unavailable, failed, unknown or
unused slots from the diagnostic result. Material availability and expected
target-state counts are included separately.

The requested model is Grok 4.6 for both opportunities, title cap 100, retries
zero and per-session timeout 60 seconds. The caller must explicitly choose
`input_byte_cap`, `main_output_cap` and `observed_main_token_cap` using `policy(...)`.
There are no inferred diagnostic capacity defaults. The separate native entry
`run_native_diagnostic` admits `diagnostic-main-and-initial-title-v1` and generates
an exact pinned config for the chosen main output cap. The original smoke entry
and its 128 output / 20,000 observed-total defaults remain unchanged.
These byte/output/observed bounds are not tokenizer quotes. The observed-token
ceiling is checked after execution and is not an input token reservation or a
wire-certified capacity bound. Tokenizer and model context capacity remain unknown.
Long BLADE references are never
truncated: the complete rendered input must fit the frozen byte cap or the
entire compilation fails before transport.

Known main input/output/cache/reasoning counts and service-reported main cost
remain native camelCase accounting. A missing title receipt is expected unknown;
title and all-opportunity totals and final settlement stay null. Successful
included-only billing checks constrain the spending route rather than define a
zero-dollar tariff. Native preflight requires fresh typed billing/topup checks
and an empty actual tool inventory in the same selected-model session. This
is not an atomic account settings lock. Main uncertainty, native faults, usage
identity replay or source drift retain the reservation and stop subsequent I/O.

The diagnostic native receipt has its own schema
`grok-native-acp-diagnostic-receipt-v1`. It binds the actual prompt, output schema,
canonical response, native reservation bytes, frozen source manifest, byte cap
and observed-main-token cap. Before signing a reviewer result or returning an
evaluator result, the provider compares the returned receipt to its private
on-disk receipt, verifies the reservation against the same session/prompt and
source pins, and checks all response/request digests against the frozen inventory.
A different but semantically valid response is still rejected; known native usage
is preserved. Original smoke `grok-native-acp-receipt-v2` files are unchanged.

## Private compilation and execution

The worker is `python -m evaluation.modular.diagnostic_subscription`. Its stdout
contains only fixed status and artifact hashes; exceptions never expose private
material bodies. It uses the standard resolver, the exact existing private
renderer and the same all-reviews-before-any-evaluator sequencing. Each reviewer
sees complete anonymous candidate/reference/rubric messages and no expected
target or other review. No new login, credential extraction or account mutation
is implemented. Native session homes must already be provisioned privately by
the caller through the authorized existing-account workflow.

1. Prepare an immutable new manifest with `schema` above, the original complete
   `tasks`/`slots`/signed-material mappings, `validation_eligible=false`, distinct
   authorities, explicit new `policy(...)`, and current runtime/input pins.
   `own_sources()` supplies bridge/native/renderer/schema/core dependency paths;
   the original pilot runtime pins remain required too. This creates a new
   manifest and never rewrites the prior HTTP manifest or material receipts.
2. Prepare a private config with schema `diagnostic-subscription-worker-config-v1`.
   Fields are `manifest`, `materials`, `key_files`, `reference_store`, `input_files`,
   `journal_path` (same standard private custody formats), plus `request_inventory`
   and `native_deployment`. Every descriptor is an absolute `{path,sha256}`.
   During local compilation the latter two fields may be null.
3. Run `freeze --config ABSOLUTE_CONFIG --sha256 CONFIG_SHA256 --output ABSOLUTE_INVENTORY`.
   This validates all 36 signed material targets and complete references before
   computing every ready slot's role/repeat/request/prompt/schema/port digest.
   Evaluator requests are compiled through the standard rubric endpoint's local
   callback without invoking any model. Unavailable slots remain in the manifest.
4. Write a new frozen run config pointing to that inventory and a deployment
   descriptor. Deployment schema is `frozen-native-subscription-deployment-v1`,
   with absolute pinned `executable`, `frozen_files` (absolute path to SHA256),
   and `slots` keyed by every compiled opportunity ID. Each slot contains unique
   absolute `cwd`, `private_home`, `private_profile`. All input/source pins,
   executable and every exact `diagnostic_config(main_output_cap)` file must be in `frozen_files`.
   Homes contain only pre-provisioned native auth and config; profiles/workdirs
   must be empty at use. Auth bytes are not an output or archive input.
5. Review and freeze the config, material availability, inventory, source checks
   and opportunity budget before authorizing real execution. This implementation
   task runs synthetic fixtures only. After separate authorization, the exact
   command is `run --config ABSOLUTE_CONFIG --sha256 CONFIG_SHA256 --output ABSOLUTE_RESULT`.

The outer fsynced journal reserves the opportunity before starting its transport;
the inner native reservation is created after same-session account/tool gates
and before prompt I/O. They are distinct reservations. A rejected native gate
may leave an outer opportunity reserved with zero dispatched prompts. Neither
journal nor private transport root can be reopened to retry a run. The native
transport kills its process tree on timeout. A supervising caller that launches
the whole multi-opportunity worker must independently enforce its overall process
tree lifetime; this module does not claim OS isolation or a parent scheduler.

The request inventory is recomputed against complete frozen private material
before execution and must match exactly. Actual runs require caller-provisioned
native deployment metadata; the normal command has no synthetic or HTTP fallback.
The explicit fixture factory is a Python testing seam, not a CLI deployment mode.
Synthetic subprocess tests exercise renderer, reservation, native event parsing,
accounting, signed private reviews, all-review freeze and 72 diagnostic outcomes.
Passing those tests establishes engineering behavior, not scorer qualification,
formal calibration eligibility, validation acceptance or scientific effectiveness.
