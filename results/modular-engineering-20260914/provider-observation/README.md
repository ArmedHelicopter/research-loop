# One fresh provider inspection per phase verification

The old PhaseProviderSession verified each original twice: configuration()
called inspect(), followed by another inspect(). The new method returns an
immutable configuration and call tuple from one fresh strict inspection.
This is local observation only: it is neither a persistent cache nor sealing,
scoring, or acceptance authority. Every later verification rereads originals.

The four red cases replayed two calls as [1,2,1,2] instead of [1,2]. Production
78481b6 repaired this. The first repaired check passed 66/67; one new fixture
used calls_root instead of the real Codex call_root. 0c5c63e fixed only that
fixture path. The final frozen check passed 67/67, with all 618 source hashes
unchanged. Tests cover both provider types and later response/configuration
drift, followed by terminal refusal without another model call. The source ZIP
is captured before each run and checked against the original before manifest.

This proves the repeated replay was removed at that seam, not an end-to-end
throughput improvement. All model peers are synthetic. No real Grok request,
API purchase, validation score, or module effectiveness result is produced.
Original failures are retained. Keys, private stores, caches, profile material
and executables are excluded explicitly; these ZIPs are not standalone
authenticated replay environments. Complete originals remain locally.
