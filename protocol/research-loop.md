# Research loop

> **来源：** 从 `Ariestar/policy-signature` 的 `.agents/research-loop.md` 抽出（2026-08-26）。
> 文中 G1–G4 cursor、`docs/research-state/` 和 CUDA 调度属于源仓 programme，不是本仓主张。
> 本仓检验的是三角色分权、LOCK-before-RUN、提案≠执行权、二元小事实审计。
> **2026-08-27 协议修正（机制引用，不占用数字）：** 在 LOCK 与 RUN 之间加入
> Predict-then-Verify 资格预报（Zheng et al. ACL 2026 的「先预测再执行」）；
> 审计总判必须是预注册小事实的合取，可重复核对、不一致则 invalid
> （Kwok et al. 2026 的准则分解与重复评估）。**不**引入连续分、不按预测质量
> 给 docket 排序、不用 Beat Ratio / Terminal-Bench 数字。

> **V4 规范性入口（2026-08-24）**：机器真源是
> `docs/research-state/`，会话先运行
> `python .agents/research_controller.py validate`，再运行
> `python .agents/research_controller.py select --session <id>`。Stage 9 只提交
> `proposed` candidate；独立 challenger 通过 `research_controller.py admit`
> 后才可变为 Ready。Monitor 从不进入选择器；Ready 与 Active 为空时必须先运行
> `frontier-audit`。v4 终局记录允许 `candidate_proposals: []`。20 次限制只计算
> 经过审计的研究项关闭，Monitor 检查、环境修复和控制步骤不计数。本文后续涉及
> 全局 D-id/FIFO、直接写 DOCKET 或强制后继的文字只解释 v2/v3 历史记录。

This is the entry point for a research session. `agent-workflow.md` describes
how to run *one* experiment correctly; this file describes how sessions chain
into iteration without a human choosing the next question each time.

The distinction matters because the workflow's stages are all constraints —
things not to do — and a constraint has a failure mode: when every research
path is gated, the cheapest way to finish a session is to write another rule.
The loop below is built so that the cheapest way to finish is to close a
docket entry, and built to prevent an agent from declaring success by
substituting the goal.

## Architecture: three roles, separation of powers

Research work is divided among three roles with disjoint authorities:

### Proposer
Derives candidate research questions from prior evidence (Stage 9 reflection).
Questions pass a **two-sided minimal criterion band**: not too easy (already
answerable from artifacts in hand), not too hard (beyond current capability
given available resources). Passing this local screen produces `proposed`, not
Ready. A different challenger applies programme admission. Line-local FIFO and
the cross-line G1→G4 cursor then determine execution order.

The proposer **cannot**:
- Execute experiments or evaluate results
- Judge whether a question was successfully answered
- Admit its own proposal or mutate generated Markdown views

### Executor
Takes the entry at the queue pointer (wraps at end), pre-registers the decision
rule and falsifier **before seeing any outputs**, runs the work (Stages 0.5–7),
and writes a terminal decision record whose status, next_action, and reflection
are determined by comparing locked predictions against observed outcomes.

After LOCK and **before** RUN, the executor writes a cheap **eligibility
prediction** (units comparable? declared artifacts exist? construct still
holds?) and **verifies** those predictions against the locked rule with
pre-registered small facts. A failed verify is `withdrawn` — the expensive
run does not start. In this repo's `workflow_v2` runner this is **machine-enforced**
(eligibility `pass=false` or `ineligible` overwrites status). This is Predict-then-Verify of *whether the test is
executable*, not a ranking of which experiment would score higher.

The executor **cannot**:
- Modify its pre-registered decision rule after launch
- Add, remove, or reorder docket entries
- Rank Ready/Active by predicted quality, Beat Ratio, or verifier score
- Declare the program-level goal complete (enforced by `goal_link` and
  `_validate_no_goal_completion_claim`)

### Auditor
Reads the decision record and validates it against **many small, falsifiable,
pre-registered facts** rather than rendering a holistic judgment on research
quality. Examples of auditable facts:
- Does a result artifact exist at the declared path?
- Do logged runs match the manifest and decision record timestamps?
- Were tests written before the implementation they cover?
- Does the reflection's `surviving_hypotheses` contradict the hypotheses table?
- Is the `docket_selected` entry actually in DOCKET.md?

Each checklist item is recorded 0/1. The overall verdict is the **deterministic
AND** of those bits, not a holistic LLM judgment and never a score. The
`workflow_v2` scorer overwrites `audit_verdict` with that AND and, if the AND
fails, will not admit `proceed`/`complete`. An optional
second independent pass is allowed; any disagreement → `invalid` (repeat to
reduce variance, not to average a rating). A record that fails audit is
rejected and does not enter the evidence base.

The auditor **cannot**:
- Propose new research questions
- Modify the executor's decision rule or outputs
- Override a `stop` with `proceed` or vice versa

This separation prevents any single agent from defining a goal, executing toward
it, judging success, and declaring completion — the structural cause of the
2026-08-21 failure (agent merged pre-existing commits, refreshed manifests,
re-ran the test suite, declared GOAL_COMPLETE). No role has the four powers.

## The loop

```text
1. READ     .agents/checks/research_state.py (retrospective diff, not a score)
2. SELECT   research_controller.py select --session <id>
             (Active resumes first; Monitor and Deferred are not selectable)
3. SURVEY   docs/survey-<topic>.md — scoped to the selected entry's question
4. LOCK     pre-register the decision rule, acceptance criteria, and falsifier
             before launching compute or reading outputs
4a. PREDICT cheap eligibility forecast vs the locked rule (units, artifacts,
             construct). Not a preference ranking of alternative experiments.
4b. VERIFY  check the forecast with pre-registered small facts. Fail →
             `withdrawn`, skip RUN. (Predict-then-Verify of executability)
5. RUN      the minimum falsifier (agent-workflow.md Stages 1–5)
             - generation-bearing runs use environment_manager.py run cuda,
               which validates .agents/checks/device_check.py before launch
               (fails when NVIDIA hardware is present but torch is CPU-only;
               quick pilots, smoke tests, and
               CPU-consistency re-runs pass --allow-cpu and note the device
               when a decision record exists)
             - inline repair budget: max 3 attempts for trivial errors
             - gate failures and construct errors escalate immediately
6. ANALYZE  primary endpoint, then acceptance review (Stages 6–7)
7. OBSERVE  run observation layer sanity checks (Stage 6.5)
             - numeric bounds, consistency, visualization, hypothesis logic
             - errors block progression; warnings require review
8. CLOSE    terminal decision record with a status (Stage 8)
9. REFLECT  Stage 9 — interpret the result and optionally propose candidates:
              a. interpret the result against the survey's occupied claims
              b. evaluate the study (blind spot, weakest stage, cost)
              c. derive next questions from five sources: surviving
                 hypotheses, failed gates, untested assumptions,
                 unexplained anomalies, scope boundaries
              d. assess quality (novelty, policy_relevance, soundness,
                 actionability, information_gain)
              e. estimate cost and capability threshold for each
10. ADMIT   independent challenger applies the two-sided binary filter:
              - floor: can we answer this from artifacts already in hand?
              - ceiling: is this achievable with current capability + budget?
              - quality gates: L1-L3 lower band, U1-U4 upper band
              admit survivors, reject others with reason
11. CLOSE   update the canonical candidate and locked claim branch; render views
12. AUDIT   each locked checklist item 0/1; overall valid = AND of items.
             optional second pass; mismatch → invalid. never a score.
13. GOTO 1
```

Steps 8–10 keep the programme reflective without forcing a successor.
Step 4 (LOCK) is what prevents post-hoc goalpost moving: the decision rule must
be committed before outcomes are observed, so the executor cannot redefine
success after seeing results. Steps 4a–4b (PREDICT then VERIFY) spend a cheap
check on *whether the locked test can run at all* before the expensive RUN —
the research-decision analogue of Zheng et al.'s predict-before-execute, not
their AutoML preference model. Step 7 (OBSERVE) is the fail-fast sanity check
gate that catches calculation errors and impossible values before they propagate
into decision records. Step 12 (AUDIT) takes Kwok et al.'s criteria
decomposition and repeated evaluation, but stops at a binary AND: no continuous
score, no tournament over successors.

## What the two-sided band does

A pure minimal criterion (MCC, Brant & Stanley GECCO 2017) admits only problems
the *current* population can immediately solve, so "complexity can only arise
through drift" — questions requiring dedicated effort get rejected. POET's
fix (Wang et al. 2019) is a band: `50 ≤ difficulty ≤ 300` against current
capability. Transfer: a question passes if it is:

- **Not trivially easy**: answerable from existing artifacts without new work
- **Not beyond capability**: achievable given current methods, compute budget,
  and the strongest result we have produced so far

After work completes, **re-check the band** — if the question turned out to be
too easy (solved without learning anything new), it may be withdrawn. This is
an anti-gaming property: solving something *too well* disqualifies it.

## Reproduction eligibility vs. success threshold

Following POET: an entry earns the right to spawn follow-up questions at a
threshold **below** full success. Concretely:
- **Eligibility** (may submit a v4 candidate proposal): the work produced
  *demonstrable progress* — a gate passed, a hypothesis discriminated, an
  anomaly characterized, a boundary mapped — even if the question is not fully
  answered.
- **Success**: the question is conclusively answered (`proceed`, `complete`).

Among admitted entries, line-local selection follows insertion order; cross-line
selection follows the persistent G1→G4 cursor, never outcome quality.

## What counts as progress

Only three things, none of which a governance edit can produce:

- A canonical candidate closed by a terminal decision record whose reflection
  and locked claim update validate;
- A result artifact whose evidence chain validates;
- An `EXPERIMENT_LOG.md` claim moved to a terminal status.

`research_state.py` reports these as a **retrospective diff** describing what
changed in the evidence state: which entries closed, which claims moved, what
was added. It does not emit counts or any quantity that could be maximized —
closing one entry spawns two, so "number of closed entries" rises monotonically
whether research advances or stalls. A diff is a description, not a score.

## Asymmetric replacement for conclusions

To revise or withdraw a prior result (POET's transfer rule, enhanced):

A new conclusion must **beat the maximum of the last N evaluations** of the
incumbent (N=5 in Enhanced POET), and must pass **two independent checks**
(run the cheap one first):
1. The new evidence satisfies at least one criterion the prior evidence did not.
2. The new interpretation resolves at least one anomaly or boundary the prior
   reflection flagged, OR discriminates a hypothesis the prior could not.

This is an **asymmetric burden**: the incumbent gets the benefit of the doubt.
Prevents noisy re-runs from displacing stable results.

## Rules that make iteration possible

**An empty Ready frontier is audited, not patched.** Check Monitor triggers,
Deferred dependencies, and obtain two independent proposals per unresolved leaf.
Only a structured exhaustion certificate permits frontier termination.

**研究次数只由 closure event 计数。** 每次合法 `close` 会在
`docs/research-state/closures/` 原子写入内容寻址的不可变事件；20 次限制按同一
session 经控制器验证的事件数计算。控制循环走完一圈、环境修复或 Monitor 检查
都不增加研究次数。

**Selection is deterministic.** Active resumes first, then a persistent G1→G4
cursor selects a dynamic dependency line and admission time provides line FIFO.
No ranking, no priority, nothing to optimize. A Watch entry joins the Open tail
only when its named trigger fires. Ask the user only when an entry needs a
resource the project does not have (human raters or a paid API); the local GPU
has standing authorization and no cumulative hour cap.

**Investigation is scoped to the selected entry.** Stage 0.5 exists so a
question is framed against the evidence rather than against priors. It is not a
mandate to survey the field before any work may begin. Survey what the selected
entry needs. A one-entry survey for a cheap diagnostic is proportionate.

**Pre-registration is enforced structurally.** The decision rule, acceptance
criteria, and the falsifier's locked predictions must be committed (in
`decision_record.json` and the experiment script's docstring or a `DECISIONS.md`
if multiple predictions) before the executor reads outputs. This is what makes
mid-study adaptation legitimate (FDA adaptive design guidance): you may change
course, but the rule governing *when* to change must be written before you see
the data. Post-hoc changes to the rule are forbidden.

**Observation layer runs before decision record finalization.** After analysis
(Step 6) but before closing (Step 8), the observation layer validates that
results are internally coherent, mathematically valid, and consistent with prior
findings. This fail-fast gate catches calculation errors, NaN propagation, and
pipeline defects before they enter the decision record. Errors block progression;
warnings require review.

**Inline repair has a strict budget.** Trivial execution errors (path typos,
missing imports) may be repaired inline during Step 5 (RUN) with a maximum of 3
attempts. Gate failures, construct validation errors, and unknown error types
escalate immediately to diagnosis. All repairs are logged in the decision record.

**Diagnosis before repair, as separate entries.** Establishing that a result is
invalid and fixing the cause are two decisions. Combining them produces a change
that cannot be reviewed, and tempts the repair to be judged by whether it
rescues the original conclusion.

**Governance changes require a triggering failure.** A change under `.agents/`
or to `AGENTS.md` must name the specific experiment or session it unblocks, in
its commit message. A rule added because it seems prudent is elective work
displacing research. If a rule has never been triggered, deleting it is also
progress.

**An audit finding is a docket entry, not a rewrite.** Discovering that a locked
result is invalid does not license editing it. Add the entry, run it, then
withdraw or correct the claim with its own record.

## Statuses that let a question close

The validator accepts, in addition to the workflow's original set:

- `closed_negative` — the falsifier ran, was valid, and answered no. Distinct
  from `stop`, where a gate failed and nothing was learned about the hypothesis.
- `corrected` — a later audit superseded an earlier interpretation of the same
  evidence.
- `withdrawn` — the result is invalid and its claim is retracted, not narrowed.

These existed in `EXPERIMENT_LOG.md` before they existed in the validator, so
closing an experiment required a status that no validator would accept. That gap
is now closed; the vocabularies agree.

## Termination

The loop does not terminate on *achievement* — README.md's program goal is a
research programme with no completion state, and
`_validate_no_goal_completion_claim` structurally forbids declaring it done.

One iteration is one canonical candidate closed by an audited terminal record;
environment refreshes, trigger checks, and governance edits do not count. The
loop terminates only when the iteration limit is reached, the token budget is
actually exhausted, external paid/human/license authority is required, or Ready
and Active are empty and a validated frontier audit emits an exhaustion
certificate. Monitor is not unaffordable Ready work,
and an unknown cumulative GPU budget is not a stopping reason. Persist and
validate `results/research_sessions/<session-id>/termination.json` with
`validate_research_exhaustion.py`. This is a
**resource/frontier condition**, not a success condition.

## Session hygiene

Start by running `research_state.py`; end by running it again plus
`environment_manager.py run cpu -- -m pytest`. A session that leaves both the docket and the log
unchanged did governance work, whatever its commit subject says — the tests
passing is not evidence that research advanced.

## Design rationale

This architecture draws on:

- **Minimal Criterion Coevolution** (Brant & Stanley, GECCO 2017): binary
  admission + FIFO queue with no ranking; "there is no attempt to say any
  candidate is better than any other."
- **POET / Enhanced POET** (Wang et al. 2019, 2020): two-sided band, reproduction
  eligibility below success threshold, re-checking after work, asymmetric
  replacement, novelty via reordering existing results.
- **FDA adaptive design guidance** (2019): pre-specify the *adaptation rule*,
  not just the endpoint; DSMB sees more than investigators; separation of powers.
- **Goodhart taxonomy** (Manheim & Garrabrant 2018): adversarial Goodhart occurs
  when an agent selects knowing the regulator's metric — so the auditor's
  criteria include at least one component determined post-hoc or unavailable at
  decision time (ANNECS principle: value depends on facts that do not exist when
  decisions are made, structurally unoptimizable).
- **Open-endedness formalization** (Hughes et al. 2024): the observer cannot
  intervene on the system (separation of judge from generator is definitional).
- **Debate > consultancy** (Irving et al.; Barnes & Christiano): a lone agent
  reporting to a judge who cannot inspect evidence degrades as the agent
  improves; holistic soundness judgments fail on obfuscated arguments; auditor
  must check many small falsifiable facts, not render a verdict on quality.
- **Unhackability theorem** (Skalse et al. 2022/2025): no non-trivial unhackable
  proxy exists over all stochastic policies; the only levers are reducing
  optimization pressure and shrinking the policy set to finite/enumerable.

The standard research cycle (Alele & Malau-Aduli 2023, JCU Pressbooks) is:
problem → review → framework → design → data → analysis → interpretation →
**conclusions and recommendations** → reporting → **reflection and evaluation**
→ new gaps → cycle continues. Steps 8–10 above implement the bolded stages,
closing the loop.
