# Ordinary scorer exchange observations

`LinkedScorerProcessClient` writes a separate append-only exchange journal beside
its legacy reservation journal. It retains the exact Python text sent and decoded
text received before parsing for startup and each ordinary scorer cell, with
reserved, received, authenticated, rejected, or unknown terminal states. The
records bind panel, optional cell, scorer configuration when available, and the
client source hash. Unknown costs remain unknown.

`read_scorer_exchange_observations` independently re-reads chain and text hashes.
These are custody observations only: they create no module attribution, semantic
parents, score authority, or scientific conclusion. They may contain private
scorer text and must stay with the original run evidence rather than be copied to
public catalogues.