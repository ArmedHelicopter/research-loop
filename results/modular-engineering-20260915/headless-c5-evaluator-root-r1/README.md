# C5 evaluator configuration and closure checkpoint

Source `b937ad822ea849bc7d45a32318a0f9285e599309` passed 38 focused checks with 783
Python/Markdown source files unchanged from the exact pre-run snapshot.

The native stdio test scores the canonical 59 recipes across three synthetic
targets: 177 reservations and 177 successful signed scores. It exercises the
real C5 client, production evaluator factory and worker, controller finalizer,
signed envelope and independent consumer. A forged startup descriptor and
tampered MAC are rejected. Known synthetic MAIN tokens are 1,770; this does
not measure real model usage, title usage or settlement.

Other checks cover exact legacy/opt-in schemas, usage/config equality, complete
and partial signed closures, retained partial token counts, controller attempt
serialization, and label isolation. The finalizer retains the signed envelope
rather than replacing it with its verified body. The outer controller writes
the closure with its last captured solver-accounting snapshot before subsequent
journal, close or fresh provider reads; its entire history/target execution is
not exercised by this scorer-only seam.

The original source snapshot, test report, source-before/after maps and retained
file inventory are attached. Private test originals are archived separately;
credential-shaped files and reparse paths are excluded and listed. Archive CRC,
member bytes and unchanged original bytes/mtime were checked.

An exploratory agent run also passed the 177-cell seam. Earlier exploratory
failures incorrectly reused its basetemp/JUnit and were overwritten. That gap
is retained explicitly; missing original failures have not been reconstructed.
The exploratory success is supplemental, not the frozen source checkpoint.

No real Grok, paid API or VAL data was used. This does not execute 46 actual
history builds and 118 runtime targets, demonstrate module effects, complete
C5 selection, or establish independent acceptance. All 48 questions and the
planned single-module and combination experiment denominators remain intact.
