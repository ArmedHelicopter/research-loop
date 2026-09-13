# Proposed one-shot initialize-only transport diagnosis

Purpose: test the missing initialization response after the terminal author's
auth-method selection. This is a separate zero-prompt diagnostic, never a retry,
continuation or replacement of the original four-request authoring envelope.

Use the same installed grok.exe SHA256 bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672,
existing diagnostic8192 config and native environment isolation. Provision one
fresh private home/profile/cwd under work/init-only-r1. Copy the already refreshed
existing private native login opaquely from the terminal attempt, without reading
or hashing auth contents and without modifying either original login copy. The
shorter fresh directory is explicitly a changed experimental path, so success
would establish only that this fresh zero-session setup can initialize; it would
not isolate path length versus refreshed-login effects.

Freeze script, source/config/executable hashes, exact command/environment policy
and the following sole request before launch. The request is a code constant,
not accepted from a caller or material file:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"research-loop-bounded-acp","version":"1"},"_meta":{"startupHints":{"nonInteractive":true,"skipGitStatus":true,"skipProjectLayout":true}}}}
```

Exactly one native launch, one initialize write, zero session/new, zero billing or
topup RPCs, zero authenticate calls and zero session/prompt methods. Do not use
SinglePromptACP.invoke, which contains later session/prompt behavior. The new
small driver has no method dispatcher or material inputs and writes stdin only
once. Server requests or unexpected protocol activity are recorded privately and
cause rejection/tree shutdown, never an outgoing response or extra request.

Use the original60-second process lifetime and existing ProcessTree ownership.
Create a durable exclusive diagnostic reservation before Popen. Never retry after
any launch or uncertain write. Capture raw streams privately with bounded byte
limits; publish only counts, response shape/keys, whitelisted version/auth-route
flags, timestamps, exit/cleanup status and hashes. Record elapsed monotonic time
and actual child exit status on shutdown. Reject extra output/work; do not promote
initialization success into model/tool/account readiness or allowance evidence.

Before the native launch, synthetic subprocess fixtures must confirm the driver
writes exactly one initialize frame under success, malformed response, unsolicited
server request and timeout, and that the process tree is closed in each case.
The outbound-method assertion structurally excludes all generation methods.

No scientific reference, task prompt, candidate, expected score, reviewer request
or diagnostic180-main inventory is loaded. Startup may perform the CLI's ordinary
auth/cache refresh; no model generation, API-key route, purchase, new login or
account-setting mutation is introduced. A result, including another timeout,
ends this one-shot diagnostic. Root scope review is required before launch; no
new user confirmation is requested.
