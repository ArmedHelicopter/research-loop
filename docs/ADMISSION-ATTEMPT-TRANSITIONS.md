# Admission controller transition sidecar

`controller-attempt-transitions.jsonl` records each persisted admission controller
checkpoint.  Each row points to a write-once copy in
`controller-attempt-checkpoints/` and binds the exact bytes, configuration digest,
and current controller source snapshot.  The final controller receipt carries the
last transition digest and current checkpoint digest only after the terminal
checkpoint has been persisted.

`verify_attempt_transitions` re-reads every retained copy, the chain, the current
attempt file, and the caller-supplied external tail.  A failed or preflight-stopped
attempt may therefore retain a truthful prefix with no final receipt.  The sidecar
is custody metadata: it neither registers module artifacts nor authorizes scores,
scientific conclusions, or unknown costs.  A local adversary can rehash a whole
sidecar; an independently retained original external tail is required to detect
that rewrite.