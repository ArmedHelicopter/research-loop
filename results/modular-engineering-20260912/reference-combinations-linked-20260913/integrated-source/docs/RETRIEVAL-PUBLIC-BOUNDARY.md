# Retrieval request boundary

Q8.2/Q8.3 must expose only selected public sources and their existing public
qualification fields to both the precursor and downstream solver. Policy and
source-pool digests can identify experimental conditions despite being opaque.
They remain in controller provenance for exact source, arm and budget replay.

The repair checks every actual precursor request in all 24 frozen cells and all
72 model requests in the linked controller grid, using the actual metadata
values as well as their keys. Budget accounting continues to reserve the full
controller projection, so stripping metadata cannot increase source allowance.
Source tampering and metadata reintroduction must fail closed during replay.

Earlier passing retrieval fixtures that exposed these digests retain their
execution evidence with this model-blinding limitation. No scientific result is
promoted. Other retrieval stage/final drivers require their own complete public
context review; this bounded repair alone does not certify all M6 paths.
