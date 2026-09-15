# CDB harmless-fixture capture diagnosis r2

Scope: only fresh owned Python sleep fixtures; no Grok, model, account, API, or network workload was started. Raw CDB output remains in `retained-private-evidence`; this report contains only fixed flags, statuses, counts, and module-label results.

## Findings

1. The original `-netsym:no` is rejected by installed CDB 10.0.26100.7705 as `Invalid switch 'n'`, even though its help advertises the flag. The same error occurs for the space spelling.
2. Both `-pvr -pd ... -c "~* k; q"` and `-pv -pd ...` exited 0 with only CDB startup output and zero frames. `-pd` is documented by the local help as automatic detach; the observed behavior is consistent with it detaching before the stack script can capture. This is an inference from the fixture outcome, not a claim about Grok.
3. A fresh third fixture used the following working command shape, with no `-pd` and explicit `qd` after the stack command:

```text
cdb.exe -pv -p <owned-sleep-pid> -sins -snul -y <fresh-empty-private-symbol-directory> -noshell -nosqm -logo <private-log> -c "~* k; qd"
```

CDB exited 0 in 2.031 seconds. The fixture was alive after CDB exited, then was explicitly terminated by the fixture owner. This verifies a bounded noninvasive capture with possible brief suspension and a successful practical detach of that owned fixture.

The only parser that found frames was Child-SP/RetAddr style (`^\s*[0-9a-f`]+\s+[0-9a-f`]+`): 35 frames. The old ordinal-prefix parser found zero. The frames appeared in private CDB stdout (7,101 bytes); CDB did not create the requested private `-logo` file. Therefore, a corrected future helper must parse the private stdout capture as well as any log file, while never publishing either raw artifact. No DLL labels were present in the public-safe extractor under the empty symbol configuration.

## Symbol/network boundary

The working command used `-sins`, `-snul`, and a fresh empty private directory for `-y`; inherited symbol paths were empty. This establishes no configured network symbol path and disabled automatic symbol loading. It does not independently prove that CDB's extension-gallery startup performs no unrelated network action; the raw fixture output is private and should not be treated as transport evidence.

## Decision

Do not alter or rerun closed Grok r1. A new reviewed diagnostic would need to use the exact `-pv`/`qd` command shape, cap it at 20 seconds, record that temporary suspension is possible, parse private stdout with the Child-SP/RetAddr rule, and treat a nonzero CDB exit, timeout, no stdout frames, or lack of child-alive-after-qd as capture-inconclusive.
