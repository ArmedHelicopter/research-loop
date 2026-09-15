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