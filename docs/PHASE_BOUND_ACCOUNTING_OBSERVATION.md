# Accounting from one bound phase observation

`PhaseProviderLedger.bind_events_with_calls(events, scope_id=..., require_eligible=True)`
returns `(call_ids, calls)`: the exact ordered ID tuple and immutable `FrozenRecord`
call tuple for that scope. It performs the same current session, original seal,
scope partition, and event binding checks as `bind_events`; the latter retains its
existing ID-only return type. `PhaseProviderAbort` rejects both methods.

Native `verify_build` consumes these already bound call views when checking its
model-charge journal. It no longer asks `calls_for_scope` to verify the same views
a second time inside that invocation. A new invocation reads current original
files again. No persistent cache, verification token, new score eligibility, or
change to the legacy Codex build path is introduced. Historical build auditing
still explicitly uses `require_eligible=False`; it cannot authorize target scoring.

The frozen regression at `ffb79ec` observed five complete provider inspections in
one native build replay. The intended bound after this change is three; this is
an inspection-count claim, not an overall speed or scientific-effect claim.
