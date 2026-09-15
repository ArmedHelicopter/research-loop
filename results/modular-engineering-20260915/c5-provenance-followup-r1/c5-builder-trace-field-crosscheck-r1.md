# C5 builder trace derived field crosscheck r1

This is a derived field crosscheck across closed original records. It does not add a catalogue-parent edge, establish module ownership or causal consumption, run an independent `verify_stage`, or support a scientific conclusion.

## Builder request fields

The generic trace `c4_builder_request` is descriptor `e0c4866e07988d94d76fe8294863433d9490965cb95e75b6e0ced2f0cf7d0362` at history journal line 98. Its private-free field summaries match the typed M9 records:

| Trace field path | M9 field path | result |
|---|---|---|
| `data.builder` | line 99 `m9_builder_selection` (`96401d22…`) `payload.canonical.builder` | equal, compared by canonical field SHA-256 |
| `data.parent` | line 100 `m9_builder_subjects` (`b7ca1724…`) `payload.canonical.parent_digest` | equal |
| `data.search_cost` | line 100 `payload.canonical.search_cost` | equal: 1 |

M9 subjects also retains the full parent record. Its FrozenRecord digest equals `parent_digest`; the generic trace stores that digest, so a direct object-to-string equality test would be a type mismatch.

## Builder terminal fields

The generic `c4_build_terminal` trace is descriptor `8eeefb73177c7504142e320cab58d04ea114ef0a1eca9c2b22012c4f9759c7ce` at line 108. Its `data.candidate_digest` equals all three retained candidate summaries:

- `FrozenRecord(candidate.json).content_hash`
- line 104 M9 `m9_candidate` descriptor `d48d1e7c35b57dd3c6871dbb633b6e66411f00f6e337bfa609c5d8155a2b8c23`, whose snapshot canonical body equals `candidate.json`
- history stage `receipt.json.candidate_digest`

All are `53a54d3b356f06fc98b8e903c69514f4488ee8778b4819bec600a1c5725bab96`.

The M9 terminal is line 105, descriptor `5c39cef111b138a8d70ce894be581d4b1eb5285c2e3f45aef9bbbea7eee54141`. Its snapshot identifies `m9-build-terminal.json`, with the same SHA-256 as that retained file and matching `succeeded` status.

## Source and integrity boundary

All five read inputs match before/after SHA-256, bytes, and mtimes; full details and each of nine field comparisons are in the companion JSON.

Current ROOT `full_loo_driver.py` is 26,463 bytes / SHA-256 `4ff5493eb5c4425cc1beebcb5051c9371da0ed07335b45418c5c9cc7faa5f58d`. It does not byte-match the archived probe source copy listed as 26,513 bytes / SHA-256 `94858bf9d02c94a0a6a69384c8e4d6c17cc837925d043ac14eb914ddb2fce9e9`. The current source’s lines 271–282 show the offline history path verifying phase/M9 artifacts, checking selected builder and candidate, then recreating the three C4 trace events. That behavior is cited only as current-source evidence; no source-identity equivalence is claimed.
