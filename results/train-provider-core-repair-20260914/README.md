# TRAIN provider core repaired synthetic evidence

Final source `921033bf09f16e6dc83042911e690debf4d1396e` passed 48 frozen checks with zero failures/errors, 631 source files unchanged, and zero real model/API calls. Native synthetic streams contain 21 MAIN requests. No native Grok executable was launched, and no scientific scoring or validation occurred.

This repairs two reviewed gaps after the preserved 52-test checkpoint: usage extraction now checks malformed sibling branches independently and conservatively recovers only unambiguous failed-frame scalars; declared immutable per-cell call-ID tuples bind identical repeated requests to their actual spans with strict ordering, exact coverage and explicit boolean eligibility mode. Failed frames remain incomplete and ineligible. The old legacy token ledger remains separate from recovered known usage. No global cross-invocation non-reuse claim is made: downstream controllers must freeze spans and enforce required disjointness.

repair-run-raw.zip contains every retained raw r4 test output, XML, source hash manifest, native original request/response/reservation/config/observer stream, Codex reviewed-context evidence, ledger and seal, except opaque fixture login files. repair-run-MANIFEST.json hashes each raw member; original-copy-map.json maps the original synthetic E-drive paths to these exact bytes. The ZIP was checked member-by-member against the original disk files.

checkpoint-52.zip is byte-identical to the immutable earlier checkpoint (SHA-256 a9f68c503df696448e3d3a3690a21512563ae4e77d1d8a82b0acf1d0080b2377). It preserves the initial 12 fixture failures/8 passes, the 20-pass checkpoint, and the 52-pass checkpoint with all raw evidence and their distinct frozen source identities. Those checkpoints do not imply the two later-found gaps were already repaired.

The tested-source directory contains exact current disk bytes. This archive's .gitattributes disables text conversion before staging. MANIFEST.json hashes every other outer member. The adjacent outer ZIP must match these outer member bytes, and committed Git blobs must match them too. The inner raw ZIP is independently checked against its per-member manifest; thus outer byte equality does not substitute for original-member checks.

Only new train_provider.py, its focused tests/docs, and evidence archives changed. Existing controller admission, _safe_call, FrozenProviderLedger, and legacy schemas remain untouched. This is provider-core engineering; remaining controller integration and C5 selection/calibration/validation remain open.
