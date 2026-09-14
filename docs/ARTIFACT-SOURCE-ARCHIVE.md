# Frozen producer-source archive verification

`ArchivedSourceResolver` lets `ArtifactCatalogue` verify a historical producer
source snapshot after the original source file has changed or disappeared. The
caller must provide the frozen ZIP path, its expected SHA-256 digest, and the
absolute source root that was used to record the source snapshot. The resolver
reads the requested ZIP member in memory and rejects duplicate, traversal,
absolute, and cross-root member paths. It also checks the member's exact length
and SHA-256 against the descriptor's recorded producer-source snapshot.

Archive resolution is read-only. It never extracts files, and catalogue
`append` still checks the live producer file before binding a new descriptor.
Without a resolver, verification retains the existing live-source behavior.

An archive byte match only proves that the archived file matches the recorded
snapshot. It does not establish semantic replay, correctness under changed
code, or equivalence of the original environment.
