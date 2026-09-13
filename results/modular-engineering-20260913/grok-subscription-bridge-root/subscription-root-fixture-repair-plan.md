# Root fixture integration findings

Root frozen checkpoint at4515ad4 is still active; no tested source was edited.
The already completed diagnostic fixture directories show two distinct issues.

Direct calls to tests/helpers/subscription_worker.py::fixture_factory launch
the synthetic ACP peer with a private cwd and inherited os.environ. The peer's
diagnostic path imports tests.helpers.calibration_pilot_fixture, which fails
with ModuleNotFoundError when the caller has no PYTHONPATH. Native receipts
honestly preserve unexpected_eof and unknown usage, causing expected-success
tests to fail. The archived isolated run had inherited an environment in which
the import was available. The fixture helper must explicitly bind PYTHONPATH
to its own source checkout; no production import fallback or native rule changes.

The nested full worker test had six accepted native prompt receipts, no final
result and no surviving worker process after its parent deadline. The original
test's subprocess.run timeout is60 seconds for a multi-opportunity fixture;
the earlier isolated run took12.808 seconds. Await final original traceback
before classifying the root failure as timeout. If confirmed, give only the
synthetic multi-call parent an explicit120-second process-tree lifetime with
preserved partial streams. Per-native fixture bounds and the actual Grok
60-second session contract remain unchanged. Use the existing tested
ProcessTree owner to close descendants, not an unowned launcher-only timeout.

Preserve this original full closure, each failed test, accepted and rejected
native observer receipts, original6 completed prompts and all unused/unknown
opportunities. Repair after closure, commit clean, then rerun the affected
worker/bridge/native/default/label integration scope under an explicitly
absent external PYTHONPATH. These are fixture failures, not real Grok calls
or scientific diagnostic results.
