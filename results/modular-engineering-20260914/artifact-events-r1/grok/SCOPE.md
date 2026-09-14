# Scope

This directory is a public, byte-checked subset of the closed stdin-held versus EOF initialize-only diagnostic. It excludes every home/profile directory, auth file, private stdout/stderr/request streams, model material, and credentials. The two copied `public-closure.json` and `reservation.json` files are safe protocol receipts, not streams.

The driver had three pre-native repair events: an initial import-path error before the synthetic control; then `isolated_config(profile=...)` raised a signature error after the successful synthetic control and before entry to the native launch loop; then recreation of that empty A directory raised `FileExistsError`, also before the loop. The driver was repaired to add the integration import path, use `user=`, and tolerate that known-empty directory. Those terminal exceptions were not persisted as files at the time, so this statement preserves their known history but cannot independently reproduce their transcript. The completed aggregate closure is the evidence that exactly two subsequent native launches occurred.

Integrity limits: frozen digests prove the listed local code/config/exe bytes at native launch boundaries. They do not establish a root cause, service-side behavior, authentication validity, usage settlement, or scientific/model validity. Settlement remains unknown.
