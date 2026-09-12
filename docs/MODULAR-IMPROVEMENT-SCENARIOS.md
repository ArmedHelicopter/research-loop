# Q6 M9 scenario driver

`research_loop.modular.scenarios_improvement` runs frozen offline fixtures for
Q6.1, Q6.2, Q6.3, Q6.5, and Q6.6 on public Blade and DiscoveryBench task
adapters. It retains callback inputs/outputs, immutable package digests,
search cost, receipts, and deployment state under the supplied sidecar.

Q6.1 sends each privilege attempt to a public callback and then crosses the
actual package or acceptance boundary. These checks show API/package rejection
only; no same-process fixture is described as operating-system isolation or
secret custody.

Q6.2 compares fixed, manual train-only, and automatic train-only packages at
the same search cost. It does not request acceptance: the authority accepts
only a signed validation-service envelope, and the scenario does not read its
inputs.

Q6.3 executes `RestrictedBuilderPort` with a frozen builder DSL. The
train-proposed arm separately creates, independently accepts, activates, and
then executes the new builder; it does not merely change a prompt.

Q6.5 retains intentionally faulty scoring feedback as an offline replay and
does not invoke deployment or acceptance. Q6.6 uses `FileDeploymentPort` and
`ExecutionRuntime` so the next workflow reports the active package digest,
then records rollback, duplicate receipt, and fail-closed drift/offline fixture
outcomes. The corrupted-state arms are local fixture corruption, not a claim
about a real host outage.

These scenarios do not measure model improvement, validation quality,
scientific validity, production isolation, or cross-process security. They do
not use network calls, labels, or real validation payloads.
