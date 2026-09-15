# CDB argument diagnosis r1

Read-only analysis of the closed `grok130-initialize-stack-r1` private CDB output. The original r1 directory was restored after moving only these new analysis artifacts into this separate directory. No Grok process was launched or attached.

## Exact failure

The private CDB stdout contains the fixed parser diagnostic `cdb: Invalid switch 'n'`; its exit code was `0x80070057`. No private stack text, address, process memory, credential, or raw log was rendered here.

The installed CDB's own help advertises `-netsym:yes|no`, but its no-target parser rejects both `-netsym:no` and `-netsym no` with the same `Invalid switch 'n'`. This is an installed-tool parser inconsistency, so r1's `-netsym:no` prevented any attach or stack command. `-noshell`, `-sins`, `-pvr`, `-pd`, `-snul`, and `-y ''` parse without that error.

## Corrected candidate

Remove unsupported `-netsym:no`; retain `-sins -snul -y '' -noshell` to ignore inherited symbol paths, disable automatic symbol loading, set an empty explicit symbol path, and disable debugger shell. The candidate remains `cdb -pvr -pd -p <known-child-pid> -sins -snul -y '' -noshell -logo <private> -c "~* k; q"`.

A new owned Python sleep process with no network was used only to validate this exact CDB argument combination. CDB exited 0 in 0.484 s and the fixture was then terminated. It produced zero parsed stack frames and an empty CDB log, so this validates command-line parsing/return only. It does **not** establish that the corrected command captures a noninvasive stack; no result should be promoted to a corrected Grok diagnostic without root review. Fixture raw CDB files remain private under `retained-private-evidence/cdb-flag-fixture-r1`; the public fixture summary records only status/counts/hashes.
