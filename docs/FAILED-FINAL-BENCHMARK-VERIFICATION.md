# Failed benchmark execution followed by an unknown answer

The shared solver can finish its candidate protocol after Docker returns a
nonzero exit code. The runtime receipt remains `failed`, has no scored output,
and stays in the allocated denominator. A valid unknown answer does not make
the execution successful or supply scientific validation.

The narrow failed-final branch now requires the final `analysis_program` and
`final_answer` slots, the exact response/execution schedule, a real failed
execution receipt with a strict integer nonzero exit code, and the bound unknown
candidate protocol. It additionally verifies:

- The bounded model program encoded with the current host's `write_text` newline
  convention equals the literal bytes of `analysis-{attempt}.py` beside the trace.
  Those bytes, their SHA256 and size bind the execution request and artifact.
  The artifact must name this fixed file. Link/reparse components are refused;
  an external artifact path is never used as a read target.
- The analysis request declares a nonempty, unique set of named public inputs
  with strict SHA256/byte-count records and matching container paths. The entire
  set must match the execution receipt and final public/consumed context.
- Final context binds the actual analysis response, program and execution digest.

This is read-only verification against retained host artifacts. Moving the
artifact tree or replaying it under a different host newline convention requires
a separately specified provenance-preserving migration; this branch does not
silently reinterpret it. Timeouts are outside this nonzero-exit branch.
Input hashes here bind the recorded public declarations to the broker receipt;
this is not a second CSV read or an independent attestation of Docker execution.
Trusted original byte/receipt pins remain necessary against wholesale journal
and artifact replacement. Reparse checks do not establish OS isolation against
a concurrent privileged writer.

The three pre-fix synthetic counterexamples consistently rehashed their own
journals and solver records: an unexecuted model program, missing input sets on
both sides, and a real zero-exit execution relabeled failed. Both common and
combination verification accepted all three; `work/ff-red.xml` preserves that
RED result. Further tests cover empty/duplicate/drifted/ill-typed input records,
ill-typed/missing exit codes, path/size/byte substitution, and the reparse refusal
gate. The latter uses deterministic gate injection, not a claim of OS authority
isolation. All workloads are public synthetic fixtures with real local Docker;
no paid solver, private task, validation input or original run is modified.
