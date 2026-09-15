# r2 model binding and next normal-path control

## Read-only comparison

The closed r2 private model-update metadata has exactly one selected-model ID:
`grok-4.6` (four identical update notifications).  This exact ID equals the
frozen M4/M5 headless declaration in
`WORK/run_actual_m4m5_headless_r1.py` (its solver and evaluator specs both
declare `model: 'grok-4.6'`) and the frozen runtime's ACP constant and safe
configuration in
`actual-m4m5-headless-runtime-r1/research_loop/modular/grok_acp_transport.py:26,69-76`.
The normal transport checks that `currentModelId == MODEL` at line 447 and
checks the selected model again after `session/new` at lines 656-658.

This is exact metadata equality, not a statement that the marketing name
identifies a unique underlying weights revision, account entitlement, or
capability.  The only established fact is that the observed runtime ID and the
frozen expected string both equal `grok-4.6`.

## Binary and source boundary

The r2 initialize used the separately pinned 1.0.30 binary
`WORK/grok-cli-1.0.30/grok.exe`, SHA-256
`ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266`.
The actual M4/M5 runner instead pins
`C:/Users/Administrator/.grok/bin/grok.exe` to SHA-256
`bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672`,
matching its frozen runtime ACP `EXECUTABLE_SHA256` at
`grok_acp_transport.py:57`.  Therefore the r2 response does not prove that
the M4/M5 production binary will exhibit the same startup behavior.

The frozen M4/M5 runtime is commit
`2113371268b30411712273623371cbcf49e0ccc8`.  Relevant source byte pins are:

- `grok_acp_transport.py`: `f736d68218e49bf90fa6ead447097d8366d3827932bea5565c854e71d07aa855`
- `grok_headless_train_solver.py`: `2f47c188d7326a61934ba4cd5287766c1a5b9fa5e9de3c31c9bbd969b57dedc3`
- `train_provider_headless.py`: `02b93e656169855021dba63d2537e1dd43c5f454391293b5cd2ca3ae3d75c539`

The last source enforces the headless frozen model/effort pair at lines 30-47.
The headless solver constructs its immutable ledger, source pins, executable
pin, prompt cap, and one-reservation-per-request behavior before native I/O at
`grok_headless_train_solver.py:60-111`, then routes the actual call through
`run_headless_diagnostic` at lines 135-148.

## Minimal next control, if separately scheduled

Do not repeat the init-only harness: its deliberate method-frame rejection is
not the production notification parser.  The smallest relevant fresh control
is one isolated normal **headless TRAIN** opportunity using the frozen
M4/M5 runtime and its ordinary `GrokHeadlessTrainModelPort` / `run_headless_diagnostic`
path, with a single synthetic public TRAIN request and the normal strict ACP
notification handling.  Freeze a new work root, private home/profile/CWD,
source manifest, exact production executable pin, one request digest/schema,
and a one-call/60-second/zero-retry allocation before launch.  Retain the
reservation, raw private response, observer receipt, normal request binding,
and usage state whether it succeeds or becomes terminally unknown.

That control should verify the complete normal path: initialize followed by
the ordinary session and prompt protocol, selected-model checks, the existing
notification checks, and durable replay binding.  It must not inherit the
init-only `unexpected_notification` rule.  It does not need formal
calibration, VAL material, Daybreak, or a new approval merely to be designed;
it remains a bounded TRAIN engineering control and cannot establish scientific
effectiveness.  No control has been launched by this report.
