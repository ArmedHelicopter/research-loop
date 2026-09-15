# Admission controller transition sidecar

`controller-attempt-transitions.jsonl` records each persisted admission controller
checkpoint. Each row points to a write-once copy in
`controller-attempt-checkpoints/` and binds exact bytes, the configuration digest,
the controller source snapshot, and the retention-module source snapshot. The
writer flushes and fsyncs its copied checkpoint and chain row; this is not an
assertion that a filesystem prevents later privileged modification.

The terminal attempt checkpoint is copied before its tail is put in the final
controller receipt. Before return, the controller compares the exact receipt
bytes on disk with the intended `FrozenRecord`, confirms its transition anchor is
the originally held one, and calls `verify_attempt_transitions`. That verifier
snapshots and re-reads the chain, all retained checkpoints, both sources, and the
current checkpoint to reject a change during verification.

A failed or preflight-stopped attempt can retain only a truthful prefix and has no
final receipt; this sidecar does not claim a complete history for such a prefix.
It is custody metadata only: it neither registers module artifacts nor authorizes
scores, scientific conclusions, or unknown costs. A local adversary can rehash a
whole sidecar; an independently retained original external tail is required to
detect that rewrite.