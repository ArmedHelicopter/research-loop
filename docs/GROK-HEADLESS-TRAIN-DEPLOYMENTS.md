# Grok normal-headless TRAIN deployments

`GrokHeadlessTrainModelPort` keeps the historical 1.0.13 normal-CLI contract
when `deployment` is omitted. Existing ledger configurations therefore retain
their original fields and are not silently upgraded.

The only opt-in alternate is
`FrozenHeadlessTrainDeployment.create(executable)`. It admits one pinned 1.0.30
binary (`ca24…5266`), the `grok-4.6` model, normal streaming-JSON command
contract, empty inspect inventory contract, and the `1.0.30` account client
header. The descriptor, digest, executable bytes, and its source pins are
frozen into the provider configuration and every call context. Account request
records preserve the versioned header metadata, and replay requires it.

This is limited to normal headless **TRAIN** calls. It does not enable a
versioned ACP evaluator, relax account/login checks, authorize API-key billing,
settle title or all-opportunity usage, or establish a model result. Any failed
or uncertain opportunity remains terminal with unknown completeness.
