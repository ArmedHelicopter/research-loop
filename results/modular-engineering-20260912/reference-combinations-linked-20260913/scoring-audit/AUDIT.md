# Primary 评分端点与四项 TRAIN 校准准备审计

审计日期：2026-09-13。结论：已有实际训练参考准备、独立进程评分接线和签名校准资格门控；当前 DiscoveryBench / BLADE 端点仍是未校准的参考一致性适配分。没有证据支持将其当成官方指标、科学有效性或独立验证结论。

本轮只读源码、文档、官方代码及既有元数据证据；没有读取参考答案正文、验证 payload，也没有模型、scorer、Docker、测试或验证 lease 调用。只在本目录新增审计文件。源码读取期间 integration 由根节点推进：起点 `0063ca1f08a91658022f87ff4443f32e71c9eefa`，最后统一核对版本为 `8d8ff1028db8572431db78018f920c01e35bf47c`。20 个文件的文本与该版本一致；原字节 SHA 与 Git blob SHA 分别记录，17 项差异仅为 CRLF/LF。原 r1 比较回执保留，r2 追加解释，未改任何 custody 字节 pin。不是当前整个 HEAD 的冻结回归声明。

## 一、已具备的证据

| 项目 | 已核实内容 | 证据及限制 |
|---|---|---|
| 公共训练输入 | 固定每 benchmark 两项，来自原 train 且新 split=train；未重新挑选 | `work/primary-prospective-export-live-r1/frozen-request-r1.json`，SHA `8713df0bccbd7dfd499e4461790bb5c983fe0b89b37d3eac98867df250cb6685` |
| 实际参考准备 | 单次尝试成功，4 TRAIN、2D+2B；只返回 opaque handles / 元数据 | `work/primary-prospective-reference-live-r1/delivery-manifest-r1.json`，SHA `1c5b4ad41c2eb834b32d62c2eb85148c9f76f1a6a53996a0029ad92a4717526a`；正文继续私有。本轮未重读正文 |
| 消费边界 | 同一 pinned source buffer、task/public digest、selector、TRAIN identity、manifest / reference 字节复核；reservation 与失败保留 | `evaluation/modular/primary_reference_bridge.py`、`reference_store.py`；hash 在 evidence manifest |
| 真实 subprocess 合成接线 | 冻结 125 tests，0 failure/error/skip；其中双 benchmark 的标准评分子进程使用 canned evaluator | `work/primary-reference-checks/frozen-r1.xml`，SHA `3962344becb69cdbaf23ff9435afe11d6bcade125110986388981d6f5474418f`。这是此前源码的工程验收，不是实际 judge 校准，也不是本轮 HEAD 测试 |
| 实际历史 scorer | 文档封存了旧两项训练上的 scorer-only recovery：11 eligible scores、11 evaluator calls；全 panel 因一个失败而 inconclusive | `docs/MODULAR-CHECKPOINT-20260913-SCORING-RECOVERY.md`。本轮仅核文档，未读取历史 candidate / reference / prompt；不把旧结果迁移为新四项校准 |
| 校准资格门控 | `scorer-calibration-v1` 签名，绑定 panel/scorer/protocol/code/judge/parameters/rubric/material manifest/盲审/仲裁/适用 benchmark/criteria/coverage/confusion/uncertainty；legacy validation lease 要求验证通过 | `evaluation/modular/calibration.py`、`custody.py`、`tests/test_modular_calibration.py`。证明门控实现，不能证明签名统计真实或独立 |

四项中参考准备元数据记录 D 共 2 个参考假设、B 共 194 个完整分析替代项。194 是参考条目数，不是独立任务或校准样本数；本轮未审核这些条目的科学正确性。原 primary 封存、旧 81 TRAIN 协议、SAB 18 hold 与原四项包保持原有权限；此次审计没有重新核读它们的 payload 或改变分配。

## 二、与官方定义的差距

官方源定位：Discovery 的 [CLI](https://github.com/allenai/discoverybench/blob/main/discovery_eval.py) 明确导入 `eval.new_eval`；本地该文件也如此。BLADE 的[官方仓库](https://github.com/behavioral-data/BLADE)及[项目说明](https://blade-bench.github.io/)将评价对象设为数据分析的概念变量、数据变换和统计模型。以下算法细节来自 evidence manifest 中单独 SHA 绑定的本地官方代码，没有执行或 import 上游程序。Discovery snapshot 上游 revision 仍 unknown，不能用在线 main 冒充原 snapshot pin；BLADE snapshot revision 为 `6118fa8d5007b91aa8c91c518182db82446a4547`。

| ID | 差距 | 对结果解释的影响 |
|---|---|---|
| D1 | 官方 `new_eval.py` 先分别分解 gold / generated hypotheses，空分解有 fallback；当前端点一次判断整个匿名候选 | 多个子假设、遗漏、重复或额外发现的误差结构不同 |
| D2 | 官方按 generated 子假设依序匹配尚未覆盖的 gold context；有 exact/null context 分支和 LLM 比较；当前仅一个 0/1 context | 当前不能表达 gold context 覆盖率，也未验证匹配顺序敏感性 |
| D3 | 官方 matched 子项分数乘变量 F1 与关系分，再用 predicted 子项数作平均分母，最终乘 gold-context recall；当前只算 `context × variable_f1 × relation` | 同名维度不意味着同一个 HMS。不能拿当前数值直接对官方排行榜或论文数字 |
| D4 | 官方要求变量匹配计数，再计算 precision/recall/F1；当前让 judge 直接给 0..1 的 F1，没有可复算的计数证据 | 数值一致性、遗漏与过度声称的惩罚尚待核验 |
| D5 | 官方入口传入 query、gold/pred hypothesis/workflow、dataset metadata；本地受控参考/context 与结构化最终候选经过 adapter | 输入表示、列描述、workflow 的语义保真尚未按官方管道逐项验证；当前 private reader 的 pin 正确不等于表示等价 |
| D6 | 本地官方 CLI 固定 `gpt-4-1106-preview`，分解、context、变量、关系可发生多次调用；当前独立 Codex judge 一次严格 JSON | 模型、提示、调用结构和失败处理不同。官方任何已发表 judge agreement 都不能转移为本地校准 |
| D7 | 本地官方 evaluator 有 -1 / fallback / 异常路径，当前不合法维度 fail closed、失败不能评分 | 失败与分母策略必须分别报告，不可只对成功子集比较均值 |
| B1 | 官方先 convert / 执行 / 处理完整分析，然后匹配 ground truth；当前对候选文本和完整参考替代项评分 | 文字“说对了”不能证明程序计算、列值或模型实际执行正确 |
| B2 | 官方 TransformMatcher 比较值 hash、类别值 hash、graph hash，并做图同构匹配；当前 transform 只是 0/1/2 文本级路径支持 | 没有建立数值等价、图结构等价或数据状态正确性的证据 |
| B3 | 官方概念变量按 Control/IV/DV/Moderator 匹配并保留匹配数与双向分母；当前 cvars 全局 0/1/2 | 粒度与归一化不同，不能由一个 ordinal 还原官方变量覆盖/匹配率 |
| B4 | 官方统计模型做模型语义匹配、unique 模型及模型关联 cvars 匹配；当前 model 为一个 0/1/2 | 模型类别、具体设定、关联变量与多个模型分母被合并 |
| B5 | 官方还报告跨运行匹配/coverage/diversity（包括抽样 k、Simpson diversity）；当前只有三项除二后的均值 | 单个候选适配分不测分析多样性，也不替代整组官方汇总 |
| B6 | 当前允许候选被一个完整参考替代项支持，不要求实现所有互斥替代项；但三个维度分别判断，没有显式共同 reference-alternative witness | 可能各维度分别被不同替代项支持而缺乏一个连贯分析。要用反例校准，不应现在改 rubric |
| B7 | 官方与当前都依赖参考集合，科学上合理但未收录的方法可能不匹配 | 低参考一致性不能自动解释为科学错误；替代分析、无效测量及合格阴性要单独审查 |

本地官方代码自身也有版本及实现细节需冻结：例如 `new_eval.py` 的 matched 子项循环实际继续传入完整 hypothesis/workflow；BLADE 某些指标函数存在各自边界行为。此次仅记录观察，不修官方代码、不推断它与所有论文实验完全相同。若日后建立 official parity，必须先选定具体版本、入口、参数、失败政策和报告指标；不能混搭理想公式与另一个版本的实现。

## 三、已有校准设计与尚未落地之处

1. **已有协议，尚无本地四项实证校准。** `MODULAR-EXPERIMENT-PROTOCOL.md` 第 5 节要求九类材料、至少双盲复核与分歧仲裁、精确版本绑定；保留旧分，修评分器要新版本并对称重评。`calibration.py` 接收并核验外部签名的聚合结果，不创建材料、盲审、仲裁或统计。有限检查范围内未发现能由当前四项直接产出真实校准证据的完整 driver；这不是全磁盘“绝无其他材料”的断言。
2. **当前科学维度与校准标签缺少映射。** 主端点严格输出三个数值维度和 reason，没有 typed abstain、invalid_measurement、scientific validity 或“正确拒绝”类别。九类 coverage 是材料分类，不能把它们直接当作 endpoint 输出。必须另行冻结独立标签与统计映射；没有定义时不要造 tp/tn/fp/fn。
3. **二分类混淆矩阵不足以校准该连续/有序分。** 需要分别报告 D context/relation 离散混淆、variable F1 误差、B 各 ordinal 混淆及 aggregate 偏差。二分类阈值若要用于资格，必须在结果前明确其目标及阈值；本轮不改已有阈值。
4. **签名不验证标注真实性。** verifier 不核对逐例独立审稿、case 唯一性、相同 source group 的相关性或 coverage 分类互斥性；可签名数值只是身份认证。九种 coverage 求和等于 matrix 总数，协议必须明确“一例一个主类别”或另设去重分母。
5. **uncertainty 无统计语义。** 当前只验证每 benchmark 有有限非负数；没有强制 CI 方法、置信水平、独立组分母或上下界。两个任务/benchmark 无法稳健估计总体可靠性；多次 judge / 扰动不能充当更多独立 task。
6. **版本绑定要补齐具体运行参数。** ScorerConfig 绑定 rubric/evaluator id/version；完整模型、effort、CLI/context、输出上限、价格与 source/config 还需一起冻结。calibration 的 judge_parameters 只要求 Mapping，不会自动证明和实际端口一致。HMAC 共识也不是 OS 隔离或独立专家身份的证明。
7. **未作当前四项 context 容量核验。** B 的全量替代参考可能造成长 prompt；当前不允许静默截断参考。实际 tokenizer/context/cost preflight 必须在服务内进行，只输出长度/hash/可容纳状态，超限要停，不能删 reference 使其“可跑”。
8. **候选材料入口不能伪造真实运行。** IndependentScoringService 只评分绑定成功 RuntimeReceipt 的最终候选，linked 服务还有执行回执要求。当前四项只有公共包/参考准备，不能捏造模型/执行 trace 把人工构造候选说成 benchmark solve。未来校准应使用明确 train-calibration worker 复用 FrozenBenchmarkRubricEndpoint / resolver，出独立 calibration-observation；或另有授权的真实 solver run 后按原流程评分。
9. **文档存在部署时态漂移。** 早期协议/端点文档还说生产 resolver/evaluator 尚未部署，后续 reference-store/process/checkpoint 已提供实际训练接线和旧任务调用证据。正确结论是“训练评分接线已有、当前量尺未校准、validation acceptance 未开放”，不是“所有端点都没实现”。

`tests/test_modular_calibration.py` 中 9 类各 1、precision/recall .8 等是合成测试输入，不是生产默认准入标准；不得照抄签发真实资格。未执行该测试的本轮只读审计也不声称它在当前 HEAD 已通过。

## 四、下一步可执行草案（本轮未执行，不构成新模型授权）

### A. 先做零调用 preflight

输入限定为上述原四项请求、实际 reference request/publication、export receipt/journal、完整 public 包与 CSV 的已有 pin、private store manifest 及 caller 的精确 TRAIN handle allowlist、原 24 inputs、primary seal/audit 和 SAB hold、拟部署 scorer/server/model/context 配置。使用 `work/primary-prospective-reference-live-r1/frozen-reference-request-r1.json` 的原 pin 集合，不用目录搜索扩张输入。

冻结预算：1 次 preflight；恰好 4 个 TRAIN binding；模型/scorer/Docker/network 调用均 0；验证读取/lease 均 0；不创建 candidate。不自动重试、不换项。先核完整 metadata/source/config pins；随后只在独立受控 resolver 内做最多 4 次绑定消费及请求容量估计（这一后续步骤涉及 TRAIN references，需要按原边界在独立服务内执行，正文不进入优化者）。所有检查 reservation、失败及原 bytes 保留。

输出：`preflight-request.json`、`preflight-source-pins-before.json`、`preflight-observations.jsonl`（仅 token/benchmark/hash/count/固定状态）、`preflight-cost-ledger.jsonl`、`preflight-source-pins-after.json`、`preflight-receipt.json`。额外 task text/reference 不得进入公开报告。模型精确 tokenizer 可用性、context 上限、满参考请求大小、有效输出上限、schema/model/config digest 必须由可信程序核验；估算若不精确则明确 unknown，不能声称容量合格。

通过标准：4/4 精确 TRAIN/source/public/selector/group/seal/reference pins 一致；0 越权读取；无 hold；全部输入前后相同；全量请求可容纳且不截断；端口支持冻结 schema，运行依赖/无工具上下文/成本 reservation 合同齐备。任何错配、未知 schema、成本或容量不明均关闭实际调用资格。该通过只叫 `train_scorer_preflight_passed`，不叫 calibrated / official-qualified / scientific-valid。

### B. 固定四项的材料与诊断性校准 pilot

这是新工作实现草案，尚无可直接运行的生产 calibration driver。先建立显式校准 worker，复用标准私有 resolver 和现有 rubric endpoint；不改 rubric、不将人工候选放进伪造 runtime。由独立材料托管者/专家基于这四项 TRAIN 制作材料，优化者不接触 reference。每项预留九类各一个 slot，共 36 slots；源任务和 token 不变。类别为 valid_positive、valid_negative、invalid_measurement、uncertain、negation_or_quoted_completion、correct_rejection、over_rejection、reasonable_alternative、empty_output。

冻结时每个 slot 要绑定 candidate SHA、source group、独立预期分项或明确 unknown、理由/证据的私有 handle、许可范围与材料制作记录。若某类在该任务上没有真实可支持材料，slot 保留 `unresolved_material`；不能把参考复述标为科学有效、把构造程序标为真实运行，不能换任务补齐。科学否定/不可识别性需要数据与测量依据，无法仅凭文本制造合格阴性。

材料先经两位与 solver / 被测模块分离的盲审者，各最多 36 judgments（72 总上限），第三位最多仲裁 36 次。盲审隐藏 arm、候选来源、另一个 reviewer 和 judge 输出；一次固定仲裁后 unresolved 保留。预期标签与不确定性口径在模型请求前封存。九类 slot 是分母承诺；无法映射到当前三维 endpoint 的类别保持诊断或不适用，不硬转二分类。

拟冻结模型预算：0 solver / 0 Docker；最大 36 份可用 candidate × 2 次同配置 judge 请求 = 72 次 evaluator calls；每次输入最多 61,440 tokens、输出最多 4,096 tokens，合计硬上限 4,718,592 tokens；累计金额硬上限 USD 20（行政预算建议，不是对实际定价的估计）；每次请求 240 秒，总串行调用墙时上限 4.8 小时，无自动重试。必须先按冻结模型价格/计费契约及请求大小持久预留最坏费用；任何预算无法被可靠预留则停止而非当 0。实际配置若不支持该输出/context 上限，A 阶段不通过，另写新前瞻协议后再启动，不能运行中改参数。两次重复用于稳定性，不选较好的一次；失败/unknown cost 都算已尝试，并禁止继续到无法保证预算的请求。

输出：材料私有 manifest、review/arbitration 私有 records、仅 hash 的公开映射、冻结 rubric/model/source/criteria/config、所有请求/响应/费用/失败的私有 ledger、逐维误差及重复差异的 metadata report、完整 36-slot / 最大72-call 分母。输出类型为 `four_train_scorer_diagnostic_pilot`；不签 validation-eligible CalibrationReceipt。

pilot 的完成标准与质量结论分开：完成要求全部 slot 有 terminal 状态、所有合法请求或跳过原因可审计、没有版本漂移/泄漏/超预算、两个 benchmark 分开报告。质量草案预声明硬反例（空输出的 score 必须 0；恶意候选不能改变 rubric；不合法 JSON/维度不签分；task/reference 错配在 I/O 边界拒绝）及相对关系（受控单维破坏不能提高相应分、等价措辞不应产生未经解释的改变），同时完整报告 exact agreement、ordinal confusion、F1/aggregate MAE 和重复差异；不以事后挑选阈值宣称通过。硬反例失败则 invalid_measurement，保留原输出，由独立维护者另起 scorer version 修复。

不应在这个 pilot 里设一个漂亮准确率作为最终“校准通过”。后续真实资格需要独立组规模、逐类精度/召回/弃权口径、连续误差标准和具有统计含义的 uncertainty 阈值，经结果前协议确定；这个四项 pilot 可以发现缺陷、支持后续样本量设计，不能自行证明这些要求满足。

## 五、四项无法支持的结论

- 不能证明官方 HMS / BLADE 指标等价、全 benchmark 覆盖、真实数据子集泛化、跨数据族误差界或最终科研效果。
- 不能证明准入阴性/正例的总体可靠率，或给 validation 解封；两任务/benchmark 的重复评价仍是两任务/benchmark。
- 不能证明所有 194 个参考替代项都正确、当前运行可执行、数据测量可识别或替代分析穷尽。
- 不能借 signed receipt / subprocess / SHA 证明 OS 完全隔离、专家独立或模型预训练未曝光。
- 不能取代尚封存的 primary 独立验收，也不能把 SAB 18 hold 静默用于补数。旧已测评分保持原版本和分母。

完整本地证据清单及 SHA 在 `evidence-manifest-r2.json`（20 源/文档、14 官方代码、13 既有元数据/JUnit），原 `evidence-manifest-r1.json` 保留。所有证据路径均以 `E:/_ryanDev/AI/research-loop-modular` 或 `E:/_ryanDev/AI/research-loop-benchmark-20260912` 为绝对根。此报告是资格与量尺审计，不是新源码提交或科学校准结果。
