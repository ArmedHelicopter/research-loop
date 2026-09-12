# Modular benchmark adapters and execution boundary

`research_loop.modular.benchmarks` prepares the two existing benchmark families
as immutable `PublicTask` objects. `DiscoveryBenchAdapter` accepts only the
public question, difficulty, dataset descriptors and column descriptors.
`BladeAdapter` accepts only public dataset identity, research question, schema,
and task instructions. Both require a matching `DataIdentity`; unknown fields
and fields named like gold, reference, answer, label, scorer, or score fail
closed. Neither adapter reads files, selects tasks, loads references, or calls a
model.

`DockerExecutionBroker` accepts an exact program file and named public files
under explicitly configured allowlist roots. It builds a fixed `docker run`
command: pinned image digest, non-root user, `--network none`, read-only root,
capability drop, no-new-privileges, resource limits, a noexec temporary file
system, and only individual read-only file mounts. It rejects directories,
symlinks, parent symlinks, paths outside those roots, unpinned images, arbitrary
commands, and invalid mount names. It never falls back to a host subprocess.

Each program validation and execution result is an immutable receipt bound to
the `DataIdentity` and content hashes. A missing Docker executable or unreachable
daemon returns `status="unavailable"`; timeouts, rejected inputs, and container
nonzero exits use separate typed statuses. The initial host check found the
Docker daemon unavailable, so this package has fake-process and dry-run coverage
only; an actual container boundary check requires the integration operator's
Docker backend.

The scoring helpers only aggregate dimensions returned by an independent
scorer. They do not receive references or instantiate a judge. Discovery keeps
context, variable F1, and relation plus their historical product; BLADE keeps
cvars, transform, and model plus their historical mean. Scores must be finite
and in `[0, 1]`; empty candidate output is zero.
