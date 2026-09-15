# C5 selected-registration retention

A selected C5 bundle spans one history identity and multiple target identities.
It is therefore not placed in a per-task `ArtifactCatalogue`: doing so would
invent a task subject for a cross-task bundle. `register_authenticated_selected_run`
keeps the existing authenticated canonical registration and also retains its exact
newline-terminated bytes in a write-once `.original` file plus a sealed,
task-neutral provenance sidecar. `verify_registration` reauthenticates the run,
compares the registration, retained original, source snapshot, and sidecar bytes
before returning. This records no module parent, acceptance, deployment, or
scientific authority; a failed authentication writes no registration or sidecar.
If a crash leaves the canonical target but no or only one sidecar, a later call
may complete retention only after reauthentication reconstructs byte-identical
target content. A differing target or existing sidecar is rejected. Verification
of an old target without the new sidecars reports incomplete retention; it is not
silently upgraded to this audit format.
