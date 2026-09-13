# Shared public execution boundary

`research_loop.modular.panel_execution` owns the reusable input declaration,
restricted diagnostic execution and public observation interfaces. Feasibility
and exploration drivers consume this module independently. Neither imports the
other experiment's private implementation to execute public diagnostics.

The boundary checks exact artifact IDs, SHA-256 values and byte counts, routes
execution through the existing `RunSession` and Docker broker, and gives the
model only the public execution observation. Input selection remains a
caller-owned `PublicInputResolver`. The production custody controller supplies
only its exported training CSV and rejects foreign declarations before model
or authority calls.

The module owns no scientific admission, diagnostic-selection policy, scorer,
dataset split or validation authority. These decisions remain in their own
interfaces. The extraction preserves the existing function bodies and runtime
behavior; experiment-specific verification and rechecks remain with the
relevant caller. The old local aliases in the feasibility module preserve its
internal calls without making other experiments depend on those aliases.
