# Full5 controller completion and separate label-audit correction

The original 11-test command at source `0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9` exited 1: ten label-dependent
tests failed in a worktree that deliberately excluded data/labels; the complete
34-cell controller test passed. The original failure report is preserved and
is not relabeled as an 11-test success. The controller was not restarted.

The same ten label tests passed in a separate label-audit process in the root
checkout. That process performed no model/controller execution. Each run's
783 Python/Markdown files match its own pre/post hashes.
The label-test file has identical bytes in the two checkouts. They share a Git
revision but 100 other files differ only in CRLF/LF
bytes. Both exact archives are preserved separately, without normalizing either
original or treating their raw source digests as interchangeable. No labels
were restored to the isolated execution worktree. This corrects the test
arrangement without weakening isolation or repeating the full controller.
The original native session 55470 was joined before run-file preservation.

All 34 cells succeeded and the four independent scoring workers produced
eligible signed final closures with no unscored cells. The test used 136
synthetic solver MAIN calls and 34 synthetic evaluator MAIN calls, with actual
Docker execution and stdio workers. These are engineering fixtures; there were
no real model, paid API, or validation-data calls. They do not measure any
module's scientific effectiveness or complete the real benchmark experiments.
The archive retains the controller's already-checked signed envelopes; the
archive script itself does not perform a new cryptographic authentication.

The private archive retains 6479 noncredential run files. Its exact
member list, hashes, byte counts, origins, credential exclusions and reparse-path
exclusions are recorded. CRC, each archived member, and unchanged original
bytes/modification times were checked. Public checkpoint files retain their
original bytes through directory-specific Git attributes. This archive is not
a credential-bearing or standalone reconstruction of the machine environment.

The older full4 run remains an independently archived incomplete attempt.
This full5 run used a new worktree and new output root, retained all 34 cells,
and did not resume, overwrite, or promote full4's partial results. C5's full
history/target selection, all remaining real single/combination experiments,
and independent validation acceptance still have their own completion criteria.
