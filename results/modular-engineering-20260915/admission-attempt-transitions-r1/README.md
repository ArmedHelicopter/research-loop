# Admission controller checkpoint retention

Every actual persist writes a separate exact checkpoint copy and chained source/config record.
The terminal checkpoint precedes the externally held receipt tail. Before returning, the controller
checks the persisted receipt against its intended bytes and independently re-reads the retained chain.
The sidecar is engineering custody evidence, with no invented module attribution or semantic parents.

The isolated frozen source passed four focused checks: actual poisoned-ledger controller prefix and
return, preflight-stopped prefix, coherent rehash rejection against the original external tail, and
persisted-receipt tampering rejection. The merged ROOT passed the same four plus ten label checks.
No full sixteen-cell experiment was rerun here. These synthetic checks made no real model or paid API
calls and did not read real VAL inputs. Exact original sources and noncredential runtime files are retained.
