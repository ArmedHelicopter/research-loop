# Fixture Q6.3 output adapter: next bounded implementation

Read-only follow-up at source 35d2209, 2026-09-14. Not implemented or verified.

`run_improvement_scenario` has no existing artifact acceptance reader and is
only invoked by the engineering fixture tests in this checkout. The experiment
registry imports its injection schema, not the execution function. Preserve
that distinction: these are not prospective benchmark runs.

The current Q6.3 fixed branch calls `restricted_builder_execute`, ignores that
callback's returned payload and executes the fixed DSL with two search units.
The proposed branch consumes one `meta_builder_candidate` callback containing
exactly `builder_dsl`, creates a MetaBuilderCandidate, activates a real local
BuilderRegistry through fixture-only acceptance, and executes the registry's
active DSL with two search units. Invalid proposals return a rejected fixture
result before activation. Neither branch uses a RunSession model invocation.

Reuse `_begin_bound_outputs` and `_verify_bound_outputs` with search_cost=2 and
strict_projection=False. Its literal-output checker still binds the original
DSL, parent, manifest, candidate and receipt; only the separate prompt/lesson
projection restriction is inapplicable to this fixture's memory/mode output.
The existing C4 and closed-proposal adapters continue to use search_cost=1 and
strict_projection=True. Do not route fixtures through the proposal adapter.

Create a fixture-owned immutable input record before its first callback. Retain
each actual callback request before calling it and each canonical return before
using it. For failures, retain the original error and existing bytes; a missing
or untyped response is not a fabricated model response. Bind selection to these
actual callback descriptors and the original task/control/variant record.
Fixed selection must explicitly identify its ignored callback and fixed DSL.
Proposed selection must retain the consumed DSL, meta package, activation
receipt, selected registry version and durable registry state. Read registry
state without invoking a constructor that could create or modify it.

Add an actual read-only fixture result consumer. It must compare the immutable
returned ImprovementScenarioResult, original result file, callback ledger,
builder outputs, sealed catalogue and file list. Recompute fixed/proposed
selection independently. A successful result requires a successful inner build;
an auditable failed terminal never satisfies success. A missing original file
must not be repaired by verification. Preserve the original two-unit allocation
separately from interpreter attempt count and unknown total resource usage.

Exercise the actual fixed and proposed Q6.3 functions, invalid proposals,
interpreter failures, mixed returns and partial writes. Check coherent mutation
of callback consumption, selected builder, two-unit allocation, candidate and
terminal state through the actual new reader. Existing Q6.1/Q6.2/Q6.5/Q6.6
fixture outputs and their optimizer/activation/rollback artifacts still need
their own output inventory and adapters; adding a generic fixture log does not
close those entries. No optimization or validation data need be opened here.
