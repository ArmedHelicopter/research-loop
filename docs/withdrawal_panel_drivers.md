# Q1.6/Q1.7 withdrawal panel drivers

`withdrawal_panel_drivers.py` supplies train-only production drivers for the
frozen Q1.6 and Q1.7 variant sets. Callers provide one typed,
identity-bound `typed-withdrawal-panel-bundle-v1` per prepared task. The
compiler projects only the selected material; missing or malformed bundles
fail closed.

Q1.6 sends a blind initial request, then sends caller-admitted invalidation
material through a matching M1/M2 on/off stage. When enabled it records an
actual evidence withdrawal and dependent-claim refresh. Q1.7 similarly keeps
current evidence out of the initial request, caller-admits it later, and uses
M3's real context construction or its declared control. Both finals receive
concrete stage responses and records, rather than only digests. These drivers
record engineering traces only; they create neither a score nor a scientific
acceptance decision.
