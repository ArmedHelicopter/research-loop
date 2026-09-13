# Grok CLI transport and subscription accounting

The user permits the existing Grok CLI `grok-4.6` and permits no additional API
fees. The implementation must use the included subscription route, refresh
account metadata before each prompt, and fail without retry or purchase when
quota is exhausted. Missing account usage percentage is unknown; it is not
100% available. Service-reported dollars are retained separately from actual
settlement and never replaced with a zero tariff.

The installed CLI's native read-only ACP methods returned a unified SuperGrok
account, zero on-demand cap, zero on-demand use and zero prepaid balance. A
successful empty auto-topup result means no configured rule in the reviewed
client model. This combined snapshot supports included-only use under the
service's account semantics. There is no discovered request-level spending
lock, and a past snapshot does not authorize a changed account configuration.

The first constant-response smoke exposed a startup bug: `--tools ""` is parsed
as no override, leaving real built-in tools registered. Windows preserves the
empty argument. An exact 33-name denylist in a private isolated agent profile
subsequently produced two empty tool inventories without a model prompt.
Wildcards are not accepted substitutes. The next runtime transport must use
the same ACP session for `session/new`, empty-tool verification and then
`session/prompt`, with a durable reservation before that prompt. Checking the
headless stream after launch is only a post-dispatch check.

`grok_cli_protocol.py` is the versioned headless stream inspector. It binds
one session, one terminal turn and one reported main model call, cross-checks
intermediate and terminal usage, rejects runtime tools and tool activity,
checks schema/text/structured-response agreement, and preserves parseable
usage even when the response is rejected. Unknown cost remains unknown.
The observed output cap check does not certify an unobserved wire parameter.
These checks have not yet connected a Grok transport to the TRAIN controller
or diagnostic scorer; that connection requires its own explicit process and
accounting contract. Existing Codex and HTTP contracts stay versioned.

The isolated r5 constant smoke has one actual model call (9,381 reported
tokens and $0.00644164 server accounting), zero observed tool calls, and an
unmet empty-tool invariant. The later metadata checks and 45 protocol/label
tests used zero generation calls. Evidence is retained under
`results/modular-engineering-20260913/grok-subscription-smoke/` and
`results/modular-engineering-20260913/grok-contract-root/`. Credential homes
and raw private ACP streams are excluded. No benchmark data or validation was
opened in these checks.
