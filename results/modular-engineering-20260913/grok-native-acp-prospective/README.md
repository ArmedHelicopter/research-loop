# Native Grok ACP prospective transport evidence

The third constant smoke passed on tested source `2586228b933c6e576bd2ed1290751639e4611337`.
Its one bound main prompt reported 2,256 input tokens (896 cached), 45 output tokens
(36 reasoning), 2,301 total tokens, and $0.00116892 service-reported main cost.
Three same-session public tool inventories were empty. Fresh before/after subscription
billing snapshots showed on-demand cap/used/prepaid balance zero and no auto-topup rule.
These snapshots are not an atomic account lock or final settlement proof.

Each separately frozen attempt allowed one main prompt and at most one initial title
opportunity, requested Grok 4.6, caps 128/100, retries zero, timeout 60 seconds.
Title usage/cost and all-opportunity totals remain unknown. The main ledger's one
model call is not a claim that all internal model activity comprised one call.

All three reservations are terminal. Attempt 1 rejected an unrecognized queue metadata
notification and has unknown usage. Attempt 2 rejected an absent optional response stop
reason: its independently observed response totals 2,300 tokens, but no terminal main
ledger was recovered. Neither was resumed or retried. The third attempt is a separately
approved corrected experiment. There were no benchmark or diagnostic generation requests.

`historical-public-evidence-r1` preserves the existing 37 payload files and their original
inventory byte-for-byte, including all five frozen checks and check 4's local test failure.
Its summary describes the historical state before attempt 3; `closure-summary.json`
adds the final state. Six exact tested source/test/doc files are included in that bundle.
Final frozen check 5 passed 52 tests including label isolation; all 667 source hashes
were unchanged before/after tests and the third smoke. This establishes transport
engineering behavior only, not scientific benchmark effectiveness.

Native requests/stdout/stderr, thoughts, profiles, auth files and session contents remain
private and are excluded. Public receipts retain hashes of private streams. The ZIP
contains exactly the files in `payload-sha256.json`; it excludes itself and that outer
manifest. `verify_archive.py` compares every listed payload byte, every decompressed ZIP
entry byte, every archive file's index blob, and (when requested) its committed Git blob.
The external verification receipt records the final archive commit without a hash cycle.
