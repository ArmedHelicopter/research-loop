# Grok CLI subscription transport smoke

The user authorized Grok CLI `grok-4.6` after declining additional API fees.
One synthetic constant request ran through the existing grok.com login, with
no API key route, no benchmark input, and no retry. The process returned
`{"ok":true}` in 10.938 seconds. The receipt reports one main model call under
`grok-4.6-build`, 9,335 input tokens and 46 output tokens (including 37 reasoning
tokens), for 9,381 total tokens. It reports $0.00644164 in server accounting;
this does not establish settlement or prove no additional charge.

The external inventory was empty: no skills, hooks, plugins, MCP or project
instructions. Runtime events nevertheless advertised 21 built-in tools; zero
tool calls occurred. Thus this smoke passes basic transport only, and does
not certify a tool-free request. The original reservation's no-tools invariant
was not established. `receipt.additional_api_fee_route_used=false` means only
that no API-key route was configured. The accompanying postrun verification
preserves both corrections without rewriting the original receipt.

The 128 output token request was set under the correctly quoted TOML key
`[model."grok-4.6"]`; no captured wire request proves server enforcement.
Earlier read-only preparations r1–r4 made no generations. They exposed native
profile discovery and an unquoted dotted TOML key, repaired before this run.
Further experiments require a separately frozen transport contract, explicit
tool exclusion, and a verified spending policy compatible with the user.

Only five explicitly allowlisted evidence files and the one-call reservation
are copied here. Credential homes, private profile directories and raw private
streams are excluded. Their hashes remain in the receipt for custody checks.
No scientific effectiveness or validation acceptance is claimed.
