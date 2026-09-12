# M6 retrieval and M7 exploration

`research_loop.modular.modules.retrieval` implements M6 as a provider port over
a caller-supplied `FrozenSourceBundle`. It has no network client. A frozen policy
and pre-retrieval signals decide whether to call the support, counter, and method
lanes; every lane has a separate fixed budget and may be empty. Returned documents
must exactly match the frozen bundle. A source root is retained once across all
lanes, so reports and paraphrases cannot add independent weight. Retrieved text is
not an input to the frozen trigger policy.

`research_loop.modular.modules.exploration` implements M7 without scheduling
work, so it cannot change FIFO. `ExplorationPlan` accepts only a train identity
and requires a data version, minimal artifact, negative control, and bounded
execution/token closure. Feasibility progresses through data, minimal run,
discriminating measurement, and independent result; a successful process exit
cannot advance later stages. `admit_exploration` issues only a bounded,
non-evidence diagnostic after data closure. Evidence-insufficient and value-doubt vetoes may
reserve a smaller diagnostic budget, but its permit says `not_evidence`.
Deterministic blocks require a repair and new feasibility assessment rather than
an appeal bypass; `review_appeal` records that distinct outcome. Ratio candidates
are train-only experiment parameters.

Instrument repair names old invalid evidence and requires new execution. It does
not restore an old positive or negative finding. These modules are engineering
mechanisms and require separate train experiments and independent benchmark
receipts before any effectiveness claim.
