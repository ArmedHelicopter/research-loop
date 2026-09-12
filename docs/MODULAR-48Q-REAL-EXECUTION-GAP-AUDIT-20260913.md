# 48Q 与组合实验：真实执行接线缺口审计

日期：2026-09-13。基线：`f36a979`。范围：公开源代码、已有文档和测试的有界只读审计；没有读取 benchmark 私有任务、gold、标签或 custody-private 内容，也没有发起网络、付费模型调用或实验。

## 结论与边界

48 个 ID 已在 `research_loop.modular.experiments.registry()` 逐项登记，并且每个 ID 都有 typed fixture input builder；这只证明覆盖规格和工程场景入口存在。`ExperimentLedger` 也正确拒绝以模块总分替代某个 Q 的测量。但从 prepared public task 到实际 benchmark driver 的生产路径，当前只有 **Q3.1**：`panel_runner.Q31PredictionDriver` 将 M4 on/off、三分支预测计划与 final request 写入 `RunSession` journal。该路径仍是 train-only 工程接通，不带独立科学 scorer receipt，因此没有任何 Q 的 `train_measured`、candidate freeze、validation 或 formal effect。

组合路径与此相同而更窄：`compile_combination_catalogue()` 已冻结 **36 个 pair + 5 个 triple + full/LOO = 42** 个组合、package digest 和完整 arm grid；`run_combination_cell()` 只把 `candidate_package` / `combination_scenario` 放进一次请求的 context。它没有根据 arm 调用 M1--M9 的真实操作，也没有共同组合 driver 或已配置的 contrast receipt，故 378 个 cell 是计划/工程日志容量，不能解释为已实际施加的组合干预或已评分组合实验。

以下“最低缺口”是必须补的最小生产接线，不建议为每个 Q 复制一个 runtime。所有训练调参只能使用 custody 允许的 train groups；validation 只运行已经冻结的候选、scenario、split、scorer 和 acceptance criteria，绝不回流优化。扩展数据可以进入 catalog/qualified task set，但每个 panel 仍须包含 DiscoveryBench 与 BLADE，并按 source group 隔离。

## 统一但不抹平 Q 的 driver/lifecycle 合同

新增一个 closed `ScenarioDriver` registry（如现有 `DRIVERS`）即可共享 runtime，而不是共享“已执行”状态：

1. `build_input(cell, task, evidence, budget, package) -> FrozenRecord`：每个 Q 保留自己的 fixture builder / real public-task projection，绑定 Q、variant、task、evidence、budget 与 arm。
2. `execute(workflow, model, executor, ...) -> MechanismReceipt`：明确列出每次 slot/model invocation、Docker/外部执行、产生的 artifact 与端点观测；`MechanismReceipt` 必须含 `coverage_id`、variant、arm、task/group、input/output/trace digests 和失败原因。不能以一条 generic final response 填充它。
3. `score(cell, MechanismReceipt, independent_scorer) -> ScientificScorerReceipt`：由冻结的独立评分器对该 Q 的机制端点和 benchmark primary outcome 同时出 receipt；不让 driver 自评分。训练只把 receipt 送入预注册 selection，随后冻结 candidate。
4. `PanelLifecycle` 复用既有 `FrozenPanel` / `PanelReceiptVerifier` / `ExperimentLedger`：prepare -> train run -> independent train score -> candidate freeze -> custody-issued validation lease -> validation run -> independent acceptance。失败和 blocked cell 留在完整分母。

Q4.3 的 slot 扩展可在该合同中以 `required_slots` 表达（sealed submission / reveal / revision），不应改变其他 Q 的 slot 数，也不把顺序控制降成 package context。Q6.3 必须注册为单独 `MetaProgramDriver` phase：输入只能是训练轨迹和冻结 DSL allowlist，输出为 CandidateBuilder proposal/artifact；它之后才进入新 candidate 的 paired train/validation lifecycle，不能作为 M9 的普通 arm 或由组合 runner 代替。

## 每个 Q 的真实实验缺口

表中“入口”是已有可审计入口；“缺口”均指从 fixture 到真实 benchmark driver 的最短路径。`scenario()` 的同 task/evidence/budget hash 控制不等于干预已进入 model/executor/scorer。

| ID | 具体干预与应观测效果 | 真实输入、调用、执行、评分 | 现有入口 | 最低缺口 |
|---|---|---|---|---|
| Q1.1 | 正确/错误/中性历史摘要与重建 context；观测错误恢复、正确保持、叙事翻转和无效执行。 | 同一 public task 的原始证据和三类 history artifact；M3 payload 调用后执行同一任务；独立 scorer 评结论/执行与历史敏感性。 | `scenarios_history.history_injection`；M2/M3 fixture modules。 | M3 driver 要让 cache invalidation/rebuild 的结果进入真实下一次 payload，并产生 paired off/on mechanism receipt。 |
| Q1.2 | 摘要-only、登记依赖、撤回上游；观测下游漏标、残留和误伤。 | ClaimRevision、依赖图、后继 task 与撤回 event；M2/M3 调用重建后执行后继；评分依赖传播和答案。 | 同上，`claim_revision_context` endpoint。 | 把 ClaimRevision 接到真实 context cache 失效与下一模型 payload；目前无 panel driver。 |
| Q1.3 | 同一观测重写为 log/report/summary/memory，与 root-id 去重对照；观测独立支持计数和准入改变。 | 可公开投影的同根 source records；M2 evidence append/admit；评分 root count、confidence/decision 与 benchmark 结果。 | `scenarios_history`、`modules.evidence` fixture。 | 把表示变体注入实际 evidence ledger，再将 admission 影响传给 benchmark task；独立 scorer 绑定 root receipts。 |
| Q1.4 | 两独立支持链撤一条、全撤、复制来源；观测正确撤回/保留。 | 有 provenance 的公开 source roots、withdrawal event；M2 recheck 后执行；评分 surviving roots 和 conclusion。 | `scenarios_history`、`support_recheck`。 | 真实 root/source projection、逐链重审执行和 scorer；不得用 fixture controller truth。 |
| Q1.5 | evidence-first sealed review 对 summary-first；观测非证据断言检出、纠错和成本。 | 同一原始 evidence、冻结规则、历史 summary；M5 sealed/reveal/revision slots；评分盲判与最终判断。 | `scenarios_history`、`scenarios_review` fixture。 | 生产 sealed slots、版本化 pre/post submission 和独立 review scorer；Q4.3 slot work 可复用。 |
| Q1.6 | 泄漏/计算/构念撤回，交叉替代理论和旧高分；观测无效主张引用与延迟。 | 已验证的公开 withdrawal evidence；M1/M2 admit/withdraw + final invocation；评分引用链/closed state。 | `scenarios_history`、`claim_withdraw`。 | 将 withdrawal 对实际 claim/evidence state 和后续 prompt 生效，按 arm 运行并评分。 |
| Q1.7 | 无关、因果时间、未知信息；观测无关不敏感/有效敏感/unknown 合理性。 | 同 task 的时间排序 evidence projection；M3 context call 和同执行；评分稳定性、敏感性和 abstention。 | `scenarios_history`、`context_rebuild`。 | 真实 payload manipulation、受控 executor 和预注册三项机制评分。 |
| Q2.1 | 中性/要求阳性/要求阴性压力；观测 FP/FN/over-rejection/pressure flip。 | 四类公共 task outcome 场景、相同 evidence/rule；M1+M5 admission/review calls；独立科学/安全 scorer。 | `scenarios_core.core_injection`。 | 生产 driver 注入 pressure 到真正决策请求，保留对照并评分，不只改 fixture input。 |
| Q2.2 | affirm/negate/quote/counterfactual/local completion；观测 completion precision/recall 与对称性。 | 冻结文本语义最小对及 actual final gate；无模型必需但须执行真实 completion scorer；独立 regression/semantic scorer。 | `scenarios_scoring.scoring_injection`，P0。 | 将 P0 scorer version 接到 benchmark final receipts 和两臂重评分；fixture tests 不能代替独立 scorer calibration。 |
| Q2.3 | false、字符串、空、重复、未知、缺项、parse error；观测最终 proceed=0。 | 实际 AuditAuthority input/runner trace；M1 admission + final gate；评分 unsafe admission 和 primary outcome。 | `scenarios_audit.audit_injection`。 | 真实 panel driver 对每种 malformed audit 执行离线受限 replay，绑定 final decision receipt。 |
| Q2.4 | one/both fail、disagree、same_wrong；观测不完整/不一致不晋升且一致不等于真。 | 双独立 audit receipts 与 public evidence；M1 dual audit；评分 gate decision 和独立 evidence truth。 | `scenarios_audit`，已有 false-admission fixture。 | 真实 independent audit providers/receipt verification 和 benchmark scorer；不能把 `same_wrong` controller fact 给模型。 |
| Q2.5 | invalid positive/negative、valid negative；观测无效阴性阻断与合格阴性保留。 | 同资格缺陷的正负 evidence、M1 admit；执行 final gate；评分 polarity symmetry。 | `scenarios_audit`。 | 将 polarity records接实际 evidence admission/claim closure并带入 benchmark runtime。 |
| Q2.6 | 次终点胜、maintenance、late pivot；观测 goal link、未授权改门槛。 | Frozen objective/version、candidate/results; M1 lock + final; scorer审计目标/探索标签。 | `scenarios_protocol.protocol_injection`。 | driver 要把 lock 与实际 candidate/evaluator path 绑定；当前仅 fixture state transition。 |
| Q2.7 | 逐一缺 lock/execution/audit/illegal state；观测 final 被阻及每条 trace。 | 完整 RunSession journal 与缺步骤变体；无需额外模型固定；trace validator + outcome scorer。 | `scenarios_protocol`、`workflow` trace validator。 | 对真实 Q runtime 执行 fault injection 并令 panel receipt 验证实际 trace，非文档检查。 |
| Q3.1 | 三竞争解释共同 discriminator、不同 prediction；观测可区分矩阵。 | public task/evidence/budget；scenario + final model calls，M4 freeze；无必要 Docker；独立 scorer 评 matrix 和 benchmark answer。 | **`Q31PredictionDriver` / `run_train_cell`**。 | 已有 runtime；补真实 public task packet、独立 scorer、paired train estimate/candidate freeze；不把工程 verified 当 effect。 |
| Q3.2 | 同预算 joint multi-arm vs separate support；观测校准、独立数据消耗、区分成本。 | 公共 task、三个 prediction arms、M4 calls/experiment execution；评分 exclusion/retention 与成本。 | `scenarios_predictions.prediction_injection`。 | 新 Q3.2 driver 真正构造/执行 joint 与 separate plans；组合 flag 不会自动执行。 |
| Q3.3 | 固定 FIFO 下 1 vs K workers；观测 claim duplication/omission/fairness/throughput。 | 同队列、lease/budget、worker events；M8 scheduler/executor；评分调度 invariants 和 cost。 | `scenarios_recovery`、scheduler modules。 | 生产并行 scheduler adapter 与 task-level receipts；必须比较并发，不能只有 fixture lease。 |
| Q3.4 | favorable/unfavorable 先完成；观测未完成 arm context hash 和结论顺序不变。 | 同 start snapshot、不同 completion schedule；M8 merge barrier、executor；评分 hash invariance/answer。 | `scenarios_recovery`。 | 真实 delayed completion harness 接入 panel + scorer，保留调度顺序与 barrier receipts。 |
| Q3.5 | write conflict/withdrawal/crash/expiry/duplicate；观测无双跑/计费、恢复与依赖传播。 | artifact/lease/worker failure records；M8 recovery/executor；评分 at-most-once/rollback/benchmark state。 | `scenarios_recovery`。 | 生产 recovery driver 按 variant 触发真实 scheduler/executor；未知调用须保留 failed denominator。 |
| Q4.1 | single、independent samples、roles；观测预测差异、相关错误、质量增量。 | 相同 task/evidence/budget，明确 provider/seed/context identity；M4/M5 multi-call；独立 scorer 评相关错误和 outcome。 | `scenarios_review.review_injection`。 | 生产 multi-call driver 和 identity receipts；不得把角色名当独立训练先验。 |
| Q4.2 | mechanism/alternative/measurement/experiment vs generic oppose；观测可核查反例/区分实验/无根据批评。 | 定向 review prompts、同 evidence；M5 slots；评分 claim/evidence linkage。 | `scenarios_review`。 | 将 role-specific outputs进入后续 benchmark decision，并由 scorer 按 role endpoint 评分。 |
| Q4.3 | sealed-then-exchange vs sequential；观测锚定、覆盖、错误传播和 pre/post revision。 | 同 evidence，独立 submit/reveal/revision artifacts；M5 slots；评分版本差、coverage、error propagation。 | `scenarios_review`，endpoint `sealed_review`。 | 专用 driver slots（root 的 slot 扩展可承接）、不可见性隔离、版本 receipt、paired scorer。 |
| Q4.4 | none_valid vs defective counterexample；观测误否决/漏判/pressure flip。 | 公共可判定反例材料；M5 review + final; scorer区分合格与缺陷。 | `scenarios_review`。 | 将 counterexample 判定真正传到 gate/answer，不能由 fixture truth 直接计分。 |
| Q4.5 | right-to-wrong/wrong-to-right/heterogeneous；观测净纠错、相关错误、成本。 | frozen initial response/review paths、provider identity；M5 calls；评分 pre/post correctness/cost。 | `scenarios_review`。 | 生产 driver 记录前后回答与模型身份，独立 scorer；异构 provider 另作因子。 |
| Q5.1 | subjective/data/minimal-run/measurement/independent stages；观测各阶段通过、预测校准、浪费。 | ResourceClosure、task artifacts、M7 feasibility calls + optional Docker; scorer stage result/cost。 | `scenarios_recovery`。 | 真实 staged executor 与 artifact receipts；阶段通过不能由 fixture outcome 代替。 |
| Q5.2 | zero-exit same prediction vs negative-control distinguishable；观测 identifiability 与状态混淆。 | M4 plan + M7 execution/negative control；Docker output；评分可区分性与 benchmark outcome。 | `scenarios_predictions`。 | driver 必须执行两个 public program/control并把 outputs喂给 scorer，不能把 exit code 当结论。 |
| Q5.3 | same mechanism/opposite prediction/title；观测重复率、误并、coverage。 | candidate hypotheses/predictions；M4 dedup；评分 mechanism/prediction identity。 | `scenarios_predictions`。 | 将 dedup 决策进入实际 plan/executor，并独立评分 retained/discarded alternatives。 |
| Q5.4 | subjective vs preregistered cost/uncertainty diagnostic choice；观测排错/预算、校准、终局质量。 | 一个已领取 task、frozen alternatives/cost; M4/M7 choose+execute; scorer choices/results。 | `scenarios_predictions`。 | production driver 要对同一 task 真选并运行下一个诊断；外部 FIFO 不得被改。 |
| Q5.5 | missing data/method/budget/control；观测依赖检出、首次/最终运行、可复算。 | source/version/budget/min artifact/negative control；M6/M7 retrieval+closure+execution；评分 closure/replicability。 | `scenarios_recovery`。 | 接真实 restricted retrieval/executor和 artifact manifest，完整缺失矩阵的 per-cell score。 |
| Q6.1 | change rule/read validation/forge receipt/self activate；观测越权=0和日志。 | actual package filesystem/authority/custody boundary；P0/M9 attempts；安全 scorer/audit receipt。 | `scenarios_improvement.improvement_injection`。 | host/deployed authority boundary integration test；in-process signing fixture 不够。 |
| Q6.2 | fixed/manual train/automatic train；观测迁移质量、安全、总成本与 train-validation gap。 | frozen package baseline、train records、optimizer only train; M9 builder/model calls；两 benchmark independent scores。 | `scenarios_improvement`，M9 fixture; fixed arm preserves package。 | paired production CandidateBuilder/optimizer driver，真实 package artifacts与 train scorer；冻结后才验收。 |
| Q6.3 | **独立 meta-builder phase**：fixed CandidateBuilder vs train-proposed builder；观测搜索效率和新候选迁移。 | 只用 frozen train trajectory、DSL allowlist、builder source/artifacts；MetaProgramDriver model/execution；score builder proposal→candidate results。 | `scenarios_improvement`，已有受限 fixture meta-builder。 | 单独 phase/panel/receipt/validation链；禁止由 Q6.2或组合 arm 替代，禁止触 custody/scorer/authority。 |
| Q6.4 | negation/quotation/alternative scorer repair；观测缺陷检出、旧结果、臂对称。 | frozen rubric/code/calibration material；P0 actual scorer versioning；独立 calibration and diagnostic re-score。 | `scenarios_scoring`。 | 部署受控 scorer version并以新、独立 calibration/validation receipt绑定，不用已测 validation 调规则。 |
| Q6.5 | unprotected vs sealed_calibrated feedback；观测错误经验/伪晋升/恢复。 | offline shadow feedback, calibration/promotion receipt；M9 update/guard calls；安全+quality scorer。 | `scenarios_improvement`，两轮 shadow fixture。 | 真实 train shadow driver、独立 calibrated scorer与 eligible receipt；不在线放行故障 scorer。 |
| Q6.6 | promote/rollback/drift/offline/duplicate；观测实际 active digest、恢复、污染、成本。 | approved package、target host、deployment events；M9 deploy/rollback；host behavior/audit scorer。 | `scenarios_improvement`、deployment fixture。 | intended host whole-package deployment/rollback integration and external access isolation; store-active 不能充当宿主部署。 |
| Q7.1 | low cost/data unknown/measurement repair/valid negative/conflict；观测 exploration admit、evidence error、negative retention。 | same task/evidence/budget, M1/M7 decision calls; optional execution; scorer prerequisites/decision。 | `scenarios_exploration.exploration_injection`。 | 生产 driver 让 exploration permit 与 evidence admission 分别入 trace/score。 |
| Q7.2 | deterministic/insufficient/value veto with smaller diagnostic；观测正确阻断、可修复转修、永久误拒。 | proposal/resource/authorization records；M7 veto/appeal calls; scorer disposition。 | `scenarios_exploration`。 | 实际 appeal routing + resource authority checks；不得允许 appeal 绕过权限。 |
| Q7.3 | zero/low/medium/high exploration ratio，仅 train；观测有效诊断/预算、挤占/overreject。 | frozen ratios/total budget, scheduler; M7 allocation/execution; train scorer selects one policy。 | `scenarios_exploration`。 | train-only allocation driver、effective rounding receipt、predeclared selection；validation 不调 ratio。 |
| Q7.4 | invalid measure/repair/old evidence；观测修复后新效度及旧证据仍阻断。 | instrument fault/repair artifacts；M1/M7 repair+admission; scorer validity/state。 | `scenarios_exploration`。 | 将 repair artifact/validation真正接到 evidence gate和后续 run；旧发现不得复活。 |
| Q7.5 | valid-known/novel-refuted/infeasible/easy-valid；观测四维混淆、保留、撤回。 | provenance/novelty/feasibility/evidence records；M1/M2 calls; scorer four separate labels。 | `scenarios_exploration`。 | 真实 multi-field state propagation and rubric，避免一个 boolean 评分。 |
| Q7.6 | contract-only vs real counterexample；观测程序/科学分歧、unknown、复核校准。 | type/hash/permission receipts + construct-bound counterexample；M1/M5 review; independent science scorer。 | `scenarios_exploration`。 | production driver 要把 contract success 和 semantic review 都交独立 scorer；不可将前者升格事实。 |
| Q8.1 | research/competition/distinguish/adversarial/retrospective/frontier；观测每 stage 实际 call/artifact。 | frozen source bundle、task；M6/M4/M5 slots及 stage3 Docker；stage trace scorer + primary outcome。 | `scenarios_retrieval.run_retrieval_scenario` fixture。 | panel driver 对每 stage 使用真实 allowed source bundle/executor，逐 stage binding receipt。 |
| Q8.2 | correct/method/reframe sources；观测纠错、依赖兑现、合理重构。 | qualified train-safe documents, fixed query/budget; M6 retrieve+model; scorer context change/answer。 | `scenarios_retrieval`。 | restricted public retrieval provider及 source qualification接入实际 task；不开放网络。 |
| Q8.3 | support-only/neutral/three-lane；观测反证遗漏、确认偏误、方法可执行率。 | same frozen docs/token/call budget; M6 three lanes; scorer lane coverage/outcome。 | `scenarios_retrieval`。 | production retrieval driver + lane-specific receipt/score；各 lane 未找到正例也须记录。 |
| Q8.4 | shared root vs independent roots；观测 root count、来源追踪与校准。 | public documents with provenance roots; M6/M2 retrieve/admit; scorer independent-support count。 | `scenarios_retrieval` + EvidenceLedger fixture。 | actual source-root provenance projection and evidence weighting in benchmark driver. |
| Q8.5 | always/never/five frozen triggers；观测 trigger precision/recall、成本、关键遗漏。 | frozen train signals/query/source bundle; M6 policy; train scorer only。 | `scenarios_retrieval`。 | train-only trigger execution/selection receipt；validation只是冻结策略的验收。 |
| Q8.6 | conflict/malicious override/pause new version；观测规则未授权改写与合法留痕。 | frozen objective、retrieval text；M1/M6 retrieval+final gate；scorer lock/disposition。 | `scenarios_retrieval`。 | real driver must bind retrieved text to review/pause path while preserving objective digest. |
| Q8.7 | remaining/failed/untested/anomaly/empty frontier；观测可追溯、新且可区分、无 programme complete。 | train task history/evidence/frontier proposal; M4/M5 calls; scorer provenance/novelty/endpoint。 | `scenarios_retrieval`。 | production frontier driver and train-only follow-up export; it may not generate its own acceptance task. |

## 42 个组合义务必须单列执行

组合不能因为任一单模块为阴性而剪枝；也不能把 Q3.2 的 `combination=True` 当作这些组合已经运行。模块因子为 `M1,M2,M3,M4,M5,M6,M7,M8,M9`，当前 compiler 已预登记以下完整集合：

| 组合层 | 独立义务 |
|---|---|
| 36 pair | `M1+M2`, `M1+M3`, `M1+M4`, `M1+M5`, `M1+M6`, `M1+M7`, `M1+M8`, `M1+M9`; `M2+M3`, `M2+M4`, `M2+M5`, `M2+M6`, `M2+M7`, `M2+M8`, `M2+M9`; `M3+M4`, `M3+M5`, `M3+M6`, `M3+M7`, `M3+M8`, `M3+M9`; `M4+M5`, `M4+M6`, `M4+M7`, `M4+M8`, `M4+M9`; `M5+M6`, `M5+M7`, `M5+M8`, `M5+M9`; `M6+M7`, `M6+M8`, `M6+M9`; `M7+M8`, `M7+M9`; `M8+M9`。每个为同任务/组、同 budget/evidence 的完整 feasible factorial arm grid，估计预注册 interaction。 |
| 5 triple | `M2+M3+M5`, `M4+M5+M6`, `M1+M4+M7`, `M3+M6+M9`, `M7+M8+M9`；每个独立 factorial panel / interaction estimand。 |
| full/LOO | 全 M1--M9 与每个 leave-one-out arm；估计 full 减去对应 LOO。因设计上不可行的 arm 保留 `structurally_unavailable` 原因，不以缺项重写 estimand。 |

每一个组合最小需要：1) arm-to-operation map，令每个 enabled module 的真实 driver 阶段被调用并在 `MechanismReceipt` 中列出，P0 固定控制照旧；2) 每个 benchmark/source group/replicate 的完整 arm grid 和相同 package/task/scenario identity；3) 可独立验证的 per-cell scientific scorer receipt；4) 聚类 source group 的预注册 interaction 或 LOO contrast receipt，当前 `estimate_grouped_contrast()` 只能在此基础上估计，不能补造测量；5) 训练选择后，另冻结组合 validation panel。当前 `CombinationPanel` 明确拒绝 validation，故第 5 项也是共享缺口。

## 最小顺序依赖与优先清单

1. **共同底座（先做一次）**：完成 public-task projection -> `ScenarioDriver` -> `MechanismReceipt` -> independent scorer 的 closed contract；扩展 adapter 仅接入已合格公开 projection，保留两核心 benchmark；落实 model context、label isolation、Docker/authority boundary。
2. **Q driver 波次（可按共享 module 实现，不得共享测量）**：Q3.1 的 scorer/real train 作为参考实现；然后 M1/M2/M3（Q1/Q2/Q7）、M4/M5（Q3/Q4/Q5/Q8）、M8（Q3）、M6/M7（Q5/Q7/Q8）、M9/P0（Q6/Q2）。每个 Q 都建自身 arm、mechanism endpoint 与 receipt。
3. **Q6.3 单独插入 M9 之后、组合之前**：先完成固定 builder 与 train-proposed builder 的独立 panel，冻结其产物；它的候选才可作为后续 M9/组合 arm 的 package 输入。
4. **所有 48 的 paired train**：同一预注册 manifest，按 source group 统计，失败/blocked 留分母；只在 train 做 package/ratio/trigger/builder 选择并 freeze candidate。
5. **42 组合 train**：使用共同组合 driver 执行每个因子，而非当前 context-only runner；完成 interaction/LOO scorer + grouped contrast receipt。单模块结果不决定组合是否运行。
6. **validation 前置条件**：独立数据 groups、custody lease、受校准独立 scorer、部署访问隔离、冻结 candidate/split/rubric/alpha；当前 inventory 没有 validation items/leases，未满足时逐项 `blocked`，不是 completed。
7. **validation only**：在没有任何调参的情况下逐 Q 和逐组合跑冻结 panel，随后由 `ExperimentLedger` 录入 accepted/rejected/inconclusive。任何 formal effect 在这一阶段以前都必须保持 `not_measured`。

## 可复核事实

- `registry()` 的 48 个 `_ROWS` 以及 `ExperimentLedger.transition()` 要求每个 ID 独立的 panel/receipt/decision，支持“不能 module-level 替代”的要求。
- `panel_runner.DRIVERS` 仅有 `Q3.1`，并在缺 driver 时抛出 `registered scenario has no production panel driver`。
- `run_train_cell()` 接受 train cells，明确没有 validation；`Q31PredictionDriver` 的运行仍创建 `execution_limit=0` session，未执行 benchmark program。
- `compile_combination_catalogue()` 的 manifest 是 `planned_only` / `not_measured`；`run_combination_cell()` 的注释和 verifier 都说明 package context 不是 module effect，且缺 common driver/contrast estimator configuration。
- 本文不把 fixture、工程 trace、Docker zero exit、typed registry、compiler coverage 或 group estimator 描述为真实 formal effect。
