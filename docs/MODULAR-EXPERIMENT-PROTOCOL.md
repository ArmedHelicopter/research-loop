# 模块实验与训练/验证隔离协议

日期：2026-09-12。状态：实施前协议设计，尚未生成真实数据切分或启动新实验。配套：[架构与模块路线](MODULAR-RESEARCH-ARCHITECTURE.md)。所有待冻结数值必须由 P0 依据训练数据、资源和组数确定；不能读验证结果后补填。

## 1. 已经在用的两个 benchmark

| 项目 | DiscoveryBench | BLADE |
| --- | --- | --- |
| 原始来源 | [allenai/discoverybench](https://github.com/allenai/discoverybench) | [behavioral-data/BLADE](https://github.com/behavioral-data/BLADE) |
| 既有实跑配置 | synthetic，12 对任务 | real datasets，9 对任务 |
| 旧实验来源 | [discovery/PROTOCOL.md](../../research-loop-benchmark-20260912/discovery/PROTOCOL.md) | [BLADE_PROTOCOL_V2.md](../../research-loop-benchmark-20260912/scienceagent/BLADE_PROTOCOL_V2.md) |
| 既有主分 | 匿名模型评分的 context × variable F1 × relation | 匿名模型评分的概念变量、变换、统计模型参考一致性均值 |
| 量尺边界 | 适配分；旧12题中6题目标列常量，参考关系与可识别性可能冲突 | 适配分；参考集未穷尽全部科学合理分析 |
| 新协议保留 | 原任务、原量尺含义、分项报告与来源 | 原数据与分析任务、分项报告与参考来源 |

两者分开判定，不平均成一个总分；适配分不能标成官方 leaderboard 分。ScienceAgentBench 只有未评分准备，不是当前两个实跑 benchmark 之一。gate 的六题词法 routing fixture、research-loop 的 W/LCK 决策题用于工程/机制回归，不替代这两个外部 benchmark。

旧批次结果已见 [REPORT.md](../../research-loop-benchmark-20260912/REPORT.md)，只作训练诊断和历史对照；新模块效果必须重新配对，不能拿旧 A 与新 B 跨版本比较。

## 2. 切分单位与污染审计

这里的训练/验证集是**科研任务和数据来源族**的划分，不是每张 CSV 随机分行。某题内部预测模型需要的 train/test 划分按该题的科学设计处理，与 agent 开发的外层 split 分开记录。

P0 由数据托管器只读固定上游 commit、文件 hash、metadata 结构和历史清单，产出 `inventory.json` 与 `exposure-ledger.jsonl`。先做来源去重、资格判定和曝光审计，再分配；优化器此时不看剩余任务正文或参考答案。

1. DiscoveryBench：同一底层数据、metadata 的多问、多改写、合成变体属于同组；共享源研究或同一生成机制/模板的任务作更高层分组。分组不只凭任务 ID 或目录名。
2. BLADE：同一原始数据集及其 research questions、所有 annotation/reference paths、变换副本一起分组；共享论文或上游样本时合并来源组。
3. 两个 benchmark 跨库检查数据 hash、来源与近重复。跨库同源组必须同一 split；不能在 BLADE 训练、DiscoveryBench 验证同一份观测。
4. 旧 Discovery 12题、BLADE 9题，以及 panda_nuts/crofoot 开发题及其他确认已曝光任务的**整个来源组**只能进入训练/诊断池。准备调用、评分夹具、日志、摘要、参考程序、RAG 索引与曾阅读的整库题面都纳入曝光审计。
5. 缺参考、数据损坏、环境不支持等资格规则必须与模型成绩无关，预先固定；缺陷样本保留在注册的诊断层，不静默删除困难题。
6. 公开 benchmark 的底座预训练曝光不可证明为零。这里保证本次优化的访问边界，不声称模型从未见过这些数据；不到满分不能排除污染。

初始方案：已曝光组全部固定为 train-only；对其余符合条件的独立组按 benchmark、real/synthetic、领域和资源档分层，尽量使整体达到约 **70% 训练 / 30% 封存验证**。这是分组数目标，不是逐题精确比例，不覆盖官方 split 命名；若官方有 train/dev/test，优先保留其结构并显式记录本地映射。已曝光的官方 test 只能视作本地训练，不能因官方名称继续称干净验证。

确定性分配采用固定 seed 和组内容 hash；seed 在查看候选效果前承诺。不根据分数反复换 seed；train 和 validation 在 group/source/hash 上交集必须为空。完整分组表和验证 task ids 由托管器保存，训练环境只收到 train manifest 与封存验证计数/承诺。

**数量是硬前置条件。** P0 报告每个 benchmark 的总组、曝光组、合格新组、训练组、验证组和预定阶段数；若剩余组无法支持两套 benchmark 的独立验收，就只能继续训练诊断。不能把同一数据集的多题/多种子充作更多独立组，也不能换个名字重用旧题。

当前元数据预警：本地 BLADE 有15个数据集目录，只有12个具 `data.csv/info.json/annotations.csv`；conversation、fertility、toy 缺 annotations。9个正式族与2个开发族已明确曝光；其外只有 soccer 在文件结构上具完整评分材料，**最多1个新可评分候选族**，仍未证明其未曝光或来源独立。因此不能承诺现有数据支持全部模块的逐阶段确认性验收。旧21题可在新协议明确作为 train/diagnostics；这不改它们在旧实验中的测试身份或旧结论。

DiscoveryBench 的本地官方结构为 `synth/{train,dev,test}` 与 `real/{train,test}`。按目录计数分别为 synth 230/69/75 个 dataset 目录、real 4/10 个目录；这些不是独立任务或来源族的最终数量。旧12题来自 synth/test。首期继续 synthetic 的既有口径，优先以官方 train/dev 为训练候选、尚未曝光的官方 test 为验证候选，经 source-group 合并后冻结真实比例；若扩展 real 则独立分层报告。按70/30强行重洗官方 test 不是优先方案。

用户要求的全部问题和实验仍须保留。补充数据的顺序是核查两 benchmark 同一版本未使用部分、再评估官方新增的独立任务；若仍不足，可按原 benchmark 任务格式/量尺建立独立来源扩展集，须独立命题和审核，并明确标为 benchmark-derived extension，不能称官方成绩。扩展数据不是本轮已完成件；需要独立数据生产与验收后才解锁后续验证。

若保持原版 benchmark 且无足够新数据，仍逐模块实现并在训练侧实验，确认性验收标 `blocked_insufficient_independent_groups`；不能声称满足了“每模块新验证”。可另预注册一次冻结全部候选后的联合验证来回答有限问题，但它不是逐步据验证晋升的等价替代，不能默默切换协议。

## 3. 访问权限与数据流

| 角色/运行包 | 可读 | 不可读或写 |
| --- | --- | --- |
| 开发者/优化器 | train tasks、train 执行与评分反馈、公共接口代码、训练校准材料 | validation 输入、参考、逐题结果、日志、缓存、摘要；正在验收的 scorer/标准 |
| 训练被测 agent | 当前训练题公开信息、训练域冻结记忆、自己的执行反馈 | gold/reference/scorer；即使训练也不能把答案直接给 solver |
| 冻结验证 agent | 托管器交付的**当前验证题公开输入**、冻结训练记忆、自身本题执行反馈 | 其他验证题、gold、得分、外部历史文件、跨题更新持久记忆 |
| 验证评分器 | 固定候选输出、对应私有参考、冻结 rubric | proposer/arm 标识、模块提示、训练调参历史；被测包代码写权限 |
| 验收/晋升服务 | 封存配对指标、访问记录、质量审计、预算与当前版本 | 修改候选以争取通过、改本轮 split/scorer、向优化器提供错误案例 |
| 人类报告读者 | 已消耗阶段的报告与访问审计 | 已读内容不能再作为将来的未见验证；不把错误详情转发给优化器 |

“优化不能访问验证集”不禁止已冻结的被测 agent 在验收时解答当前验证题；禁止的是据此修改模型、提示、模块、检索、记忆或后续优化策略。权限按角色和阶段落实，而非让所有 agent 在同一仓库中遵守口头约定。

被测环境从 allowlist 构建，不能挂载整个项目根或上游 clone。模型程序通过已有受限 broker 执行；训练/验证各有容器、文件根、数据库、cache namespace、session 与日志。容器不挂宿主凭据、Docker socket、gold、验证根目录或任意 shell 工具。仅另起 Python 进程、用文件夹名隔开或递归扫禁词均不足以保证隔离。

优化执行也必须处在训练专用环境；拥有宿主全盘工具的交互 agent 不能被宣称已经技术隔离。验收包由独立操作者/服务构建和运行，访问令牌仅授权指定 trial 和当前 task，读取有审计。内容 hash 用于绑定，来源信任由独立进程权限/受控写入保证；不把 hash 自称当身份认证。

验证期禁用任意网络。M6 检索使用切分前固定的资料快照，经托管器排除任务答案、参考代码、结果讨论及近重复来源；优化器仅能检索 train-safe 语料。验证时冻结查询算法和检索源，不能访问 benchmark 仓库、官方解答或历史报告。开放网络检索效果另开协议，不能继承本协议的无泄漏主张。

## 4. 逐模块训练与一次性验收

```text
登记模块假说与可变参数
  → 在 train 内按 source group 做内部交叉验证/开发划分
  → 有限预算搜索、记录全部候选与失败
  → train-only 选择候选/目标组合，并冻结完整实验panel
  → 冻结代码/提示/参数/记忆/检索/模型/环境/评价/停止条件
  → 托管器领取未用过的 validation stage shard
  → 在同一 shard 上运行当前基线与候选及预注册对照
  → 独立盲评、统计、安全与成本验收
  → accept / reject / inconclusive / invalid_measurement / incomplete
  → 合格包切换并确认；其他状态保留旧基线
```

train 内部用于挑候选的折仍属于训练权限域，不称本协议的 validation。优化包括改代码、提示、角色、budget allocation、阈值、检索词、记忆、少样本例子和模型配置；不只指参数训练。

每次提交一个预先冻结的实验panel。单模块阶段含候选与对照；组合阶段可含同时冻结的2×2、2³或全量/消融臂，所有臂在同一新来源组分片配对。不能看结果后增加候选、改参数或改变目标组合；验证服务不返回驱动调参的逐题反馈。整个panel完成后分片标为consumed，不能在未来新候选上重用。详见 [组合实验协议](PARALLEL-IMPLEMENTATION-AND-COMBINATION-TESTS.md)。

反复看到 pass/fail 也会产生自适应选择。因此模块次序、候选提交流程与阶段统计预算预注册，**每阶段使用全新来源组分片**；晋升器可据验收决定保留版本，优化器只接收后续允许使用的包，不接收验证错误说明。版本保留本身仍是选择信号，故不能再次用旧 shard 证明后续改动泛化。

P0 封存 `StageAllocationManifest`：全部模块/子阶段/组合panel × 两 benchmark 的资格、分片承诺、全部冻结臂与contrast、目标bundle、尝试上限、alpha 分配、未触发/失败/数据不足转换和 final 是否存在。托管器只按此分配签发 lease；不得因上一阶段分数重新选择分片或改变验收顺序。独立模块实现和训练可以并行。没有足够验证组时 final 明确记 unavailable。

同一 manifest 内的 `coverage_allocations` 必须逐一覆盖矩阵48个 ID，每项固定 scenario/version/变体、required arms、stage、candidate、mechanism endpoint 与两个 benchmark 的 task-group lease/阻塞原因。评价器核对场景实际进入模型 payload、规定的执行已发生且对应回执具同一 ID。普通总分回执不能满足未运行场景；只有 benchmark 主分作为伴随读数时，机制资格仍单独判定。

`BlockedReceipt` 由托管器绑定 stage/coverage_id/benchmark/inventory_digest/reason 签发；不含虚构分数，不记 validation_measured，也不许可默认晋升。补齐数据后按新注册的独立分片继续原实验义务，不把 blocked 当通过。

给最终组合预留从未启用的 `V_final`；最终目标bundle由训练结果选择，可以包含单独无增益但互补的模块。冻结后一次比较B0、该目标bundle与预注册控制/消融，不按final得分改选赢家。若没有足够独立组，必须明确最终组合没有独立验证，不降低门槛掩盖不足。

失败后允许只用 train 继续改进，并预注册下一次候选；不能根据验证失败案例定向修复后再次测同一 shard。确需查看/修复验证揭示的问题时，该 shard 明确退役为已曝光诊断材料；后续评价使用全新独立组，而且新优化仍只用 train 域材料。不得自动把退役 shard 导入训练记忆。

## 5. 先验证量尺，再比较模块

P0 分别验证两个 adapter 的输入、数据可识别性、执行回执、评分语义与分项聚合。旧分保留；改量尺生成新 `scorer_version`，两臂在同一新规则下重新评价。

校准材料来自 train 或独立制作的非验证夹具，覆盖有效阳性、有效阴性、无效测量、不确定、否定/引用完成声明、正确拒绝、过拒、合理替代分析和空输出。至少包含双盲复核与分歧仲裁；固定 LLM judge 不是人类 gold，也不能因一正一负夹具通过就宣称全面可靠。

`CalibrationReceipt` 绑定 scorer code、judge identity/参数、rubric、校准材料 manifest、盲审/仲裁协议、适用 benchmark、混淆矩阵与不确定性。缺任一绑定不发 validation lease。独立制作的校准材料归 train/calibration 权限域，不能从封存验证题提取或据验证表现挑选。

科学有效性和参考一致性分别输出。Discovery 的常量目标/无法识别关系不应因复述参考关系得到“科学有效”的肯定；BLADE 的合理非参考方法不应自动变成科学错误。保留兼容历史的适配分，并新增预注册的科学有效性/可识别性读数；不靠合成加权总分隐藏冲突。

基于模型结果发现评分器缺陷时：冻结本轮解释，标 `invalid_measurement`，保留原结果；独立量尺维护者在训练材料上诊断与修正，对两臂对称处理。修正后重评旧材料只作诊断，新确认性验收使用新 shard 和新预注册版本。被测模块不能修自己的当轮评分器。

## 6. 公平对照与预算

单模块在共同B0上测独立贡献，增量阶段以 `B_i` 与 `B_i + M` 测条件贡献；组合阶段用预注册因子设计和contrast。增加调用/上下文/执行的模块及组合，均加入等预算普通自修订/多次采样控制。单独、条件、组合净收益和交互效应分别报告，不能把累计提升归给最后模块或将单独不显著当作组合无效。

基线可规划、检索已允许资料、执行、检查错误和修订；不得故意削弱。两臂固定同底座、工具、数据、环境、CPU/RAM、总 token 与墙时上限；同一 task/seed 下随机化或交替执行顺序。多模型差异必须另作因子，不与角色分离同时改变。

旧实验虽同为三调用/两执行，A/B 的最终反馈机会并不相同。新 P0 明确 `阶段 → 本阶段输入 → 允许执行 → 下一阶段可见反馈` 时序表，并提供两种区分清楚的读数：

- 机制对照：对齐可见执行反馈次数和时点，只替换本模块；不能用“同样三次调用”代替时序对齐。
- 实用成本对照：给相同资源上限，模块自己分配；分配损失属于实际效果，报告真实使用量与闲置量。

实际调用能力和健康度在冻结前检查；默认沿用已有 Luna/low 作为候选起点，而非假设它永远健康。身份/版本、输入输出 tokens、模型调用、执行次数、CPU/RSS、墙时/P95、人工复核和训练搜索成本分开记；缺 usage 记 unknown。不能静默换模型或复用旧任务的付费/调度授权。

阶段预算在首次 scored call 前固定，包含训练搜索、scorer 校准、验证、失败尝试与收尾预留。达到预算或实际配额拒绝即封存 incomplete，不新增样本“补到显著”。恢复复用同一 trial/task/arm id，先核对已有完成结果，不能挑最好的一次。

## 7. 指标、统计与决定

两个 benchmark 分别报告原始分、分项、每个来源组的配对差；不直接合并。主要分数在本 benchmark 内归一到 [0,1] 仅用于统一阈值单位。按 source group 聚类做配对重采样/预注册检验，多题、扰动、多种子是组内重复。样本不足时不给虚假的窄置信区间。

必须同时报告：参考一致性、科学有效性、正确拒绝与过拒、假阳性/假阴性、正确改错/错误改对、违规/未授权晋升、运行与计费失败、真实总成本。unknown/inconclusive 是允许的科学判断，不把所有 abstention 当错误；但必须测判别力防止一律拒绝。

每模块在 train 阶段登记属于质量、成本或安全机制假说，冻结最小有意义效应 `delta`、非劣界 `epsilon`、安全界、组数/统计功效目标与 familywise 错误预算。不能把 epsilon 默认成看起来容易过的百分比；须解释为什么业务/科研上可接受。跨模块、两 benchmark、多臂和重复提交纳入同一个预注册检验族，使用冻结的 alpha 分配/调整；主检验之外标探索性。

验收原则：

0. 先检查实验机会覆盖与来源组数量：not_exercised / insufficient_independent_groups 阻断对应机制确认；未触发时的总体分数仅作伴随结果，不当模块成功或失败。
1. 隔离和完整性先过门：任何验证泄漏、未授权放行、伪造来源、改规则都阻断晋升。
2. 两 benchmark 的科学安全读数无观测回退；零事件仍报告相应上界，不能推成真实风险为零。过拒/正确保持不得超出预注册界。
3. 质量模块：两 benchmark 的质量差下界均达到预注册非劣要求，且预注册目标上的改善超过 delta 并满足调整后的统计门槛；仅一个 benchmark 改善时只作相应范围主张，不能让另一边显著退步被均值抵消。
4. 成本模块：两 benchmark 质量均非劣且安全条件满足，成本改善达到冻结门槛；训练和额外审计成本另列摊销，不以 token proxy 宣称总负载降低。
5. 安全/机制模块：目标错误下降且任务判别力和成本满足冻结条件；全部拒绝或未实际触发模块不能作为通过。
6. CI 过宽为 inconclusive；量尺无效为 invalid_measurement；基础设施中断为 incomplete；完整失败为 reject。以上均不记 accept。

基础设施失败与被测算法失败使用预注册归因规则：已交付题目的模型解析/代码错误属于方法结果；宿主掉线、配额拒绝属于未完成，单列分母与覆盖率。完整配对分析不能静默剔除方法失败；差异性缺失必须报告并阻断不可靠晋升。

## 8. 冻结对象和回执

以下为字段设计示意，`pending` 表示尚未冻结，不能直接用于运行：

```yaml
schema: modular-trial-v1
state: design_only
stage: M1
baseline_digest: pending
candidate_digest: pending
changed_module: scientific_admission
panel_digest: pending
factor_levels_and_feasible_cells: pending
contrast_matrix_and_target_bundle: pending
benchmarks: [discoverybench_synthetic, blade]
dataset_commits: pending
split_manifest_digest: pending
stage_allocation_manifest_digest: pending
exposure_ledger_digest: pending
validation_lease: pending
scorer_versions: pending
calibration_receipt_digest: pending
model_and_parameters: pending
execution_image_digest: pending
call_and_feedback_schedule_digest: pending
retrieval_and_memory_digest: pending
criteria_and_alpha_budget_digest: pending
search_and_evaluation_budget_digest: pending
allowed_optimizer_domain: train
validation_memory_writes: forbidden
validation_network: disabled
```

运行包所有可影响行为的代码、提示、模型、数据、scorer、环境和依赖均内容绑定；缺少字段拒绝启动。receipt 另含 trial/task/arm/run/seed/source group、原始输出 hash、每个执行回执、known/unknown usage、盲序随机化、分数、失败原因和生成方身份。

晋升器核对 parent/active、candidate、criteria、split、scorer 与 receipt 一致后才生成部署许可；宿主确认实际使用同 digest 才记 deployed。回滚后再用独立工程任务确认实际行为恢复；不改写历史科学结果。

## 9. P0 与后续模块的集成验收清单

以下应通过真实导出包/执行 broker/评分服务链路，不只调用 helper：

- 优化器读取验证路径、上游 clone 的 gold、历史验证日志、检索答案、跨域缓存均失败并留访问记录；模型生成代码同样无法读取。
- 训练组别名、CSV 副本、同源多问及跨 benchmark 同源内容不能进入验证；已经消耗的 shard lease 不可重用。
- 验证 agent 只读当前题，任务结束 memory/cache 销毁；下一题无法获取上一题输出或评分。
- 更换 candidate/scorer/image/prompt/split/hash、交换两臂、漏配对、缺 cost receipt、缺签发权限均 fail closed。
- 两个 adapter 的同一 frozen package A/A 对照评估时序与评分方差；A/A 差异应按预注册容忍区间诊断，不要求随机模型逐字相同。
- 工具执行 → evidence binding → review →科学状态→ scorer 独立回执接通；退出 0、引用不存在 evidence、跨 subject 均不能自证有效。
- M2/M3 撤回一条来源后重建上下文，旧摘要不得恢复失效主张，独立支持链保留。
- 晋升/回滚走真实 package resolver，下一次宿主任务读到预期 digest；shadow 内存态变化不算部署。

首期先完成 inventory、隔离和评分校准，再冻结每个模块的确认性资格与 validation 分片规模；不减少任何模块实现或训练侧实验。该前置检验失败时交付具体缺口和训练侧工作成果，不虚构已完成数据切分或泛化结论。完整范围按 [48项实验矩阵](MODULAR-RESEARCH-COVERAGE.md) 验收。
