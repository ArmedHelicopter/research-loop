# Modular benchmark adapters and execution boundary

`research_loop.modular.benchmarks` prepares the two existing benchmark families
as immutable `PublicTask` objects. `DiscoveryBenchAdapter` accepts only the
public question, difficulty, explicit `source_kind` (`synthetic` or `real`),
dataset descriptors and column descriptors. Its canonical `DataIdentity.benchmark`
is `discoverybench`; it preserves rather than infers the source kind, so a real
sample cannot silently enter a synthetic-only experiment.
`BladeAdapter` accepts only public dataset identity, research question, schema,
and task instructions. Both require a matching `DataIdentity`; unknown fields
and fields named like gold, reference, answer, label, scorer, or score fail
closed. Neither adapter reads files, selects tasks, loads references, or calls a
model.

`DockerExecutionBroker` accepts an exact program file and named public files
under explicitly configured allowlist roots. It builds a fixed `docker run`
command: locally-present pinned image digest with `--pull never`, non-root user, `--network none`, read-only root,
capability drop, no-new-privileges, resource limits, a noexec temporary file
system, and only individual read-only file mounts. It rejects directories,
symlinks, Windows reparse points/junctions, parent links, `..` traversal, paths outside those roots, mount-source colon/comma injection, unpinned images, arbitrary
commands, and invalid mount names. It never falls back to a host subprocess.

Each program validation and execution result is an immutable receipt bound to
the `DataIdentity` and content hashes. A missing Docker executable or unreachable
daemon or missing-image failures return `status="unavailable"`; timeouts, rejected inputs, and container
nonzero exits use separate typed statuses. The initial host check found the
Docker daemon unavailable, and no scientific score is derived from any execution
receipt.

Generated code receives no host output path. It may write only to the isolated
`/tmp` tmpfs and communicate retained evidence through clipped stdout/stderr in
the immutable execution receipt. This prevents user-controlled output paths and
host-side symlink replacement from becoming a write channel.

## Local Docker boundary evidence (2026-09-12)

Docker Engine `29.6.1` was available. The broker first inspected and then used
the already-local `research-benchmark-python:20260912` image with digest
`sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349`.
It ran a newly created public CSV fixture and generated Python program; no
benchmark task, reference, gold, label, or validation file was opened.

The successful immutable receipt recorded exit code 0 and showed: non-root UID,
failed outbound socket connection, failed writes to `/` and `/input/public_csv`,
and a successful write under `/tmp`. Its command had `--pull never`, `--network
none`, `--read-only`, user `1000:1000`, and exactly the program and public CSV
read-only mounts. Separate executions produced `failed` for an intentional exit
7, `timed_out` for a three-second program with one-second timeout, and `rejected`
for an out-of-allowlist mount. A Windows junction fixture was also rejected as a
reparse path before Docker invocation. The timeout receipt recorded a successful
`docker rm -f` of only its digest-derived container name; no container remained
after these checks.

The scoring helpers only aggregate dimensions returned by an independent
scorer. They do not receive references or instantiate a judge. Discovery keeps
context, variable F1, and relation plus their historical product; BLADE keeps
cvars, transform, and model plus their historical mean. Scores must be finite
and in `[0, 1]`; empty candidate output is zero.
