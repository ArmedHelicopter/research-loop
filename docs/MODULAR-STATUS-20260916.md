# 模块实验当前状态（2026-09-16 11:40 +08）

**12:20 更新：** 本地 TRAIN 接口的 [7 份冻结原件](evidence/local-ollama-train-engineering-r1/README.md)已独立归档（提交 `f13bfb7e`）：3 项检查通过，824 份源码逐字节核验，零实际模型/VAL 调用；独立本地评分器仍未实现。C5 原生会话 45472 经原句柄核查仍在运行，40/46 构建成功、118 目标未开始，选择和 VAL 均未开启。账户实时查询仍为已用 99%、剩余 1%；完整目标仍未完成。

**12:14 更新：** 实际 Q6.3 已闭合为 8 单元、0 评分，原生退出 0 仅表示控制器完成收尾；[174 份原件与独立核算](evidence/actual-q63-grok130-r1/README.md)已归档。Q5.1/Q5.2 的 36 单元工程链路已完成，[8147 份原件](evidence/feasibility-linked-engineering-r1/README.md)保留原 r2 的两项测试错误及 r3 零派发补充验证。实际模型效果与 VAL 仍未测量。

本地模型已完成 4 次 CPU 可用性调用和 6 次 Docker 检验；最后一版程序通过 2/2 输入，但模型自报预期计数仍错误。[全部本地尝试](evidence/local-qwen7b-readiness-r1/README.md)独立保留，仅属部分可用性证据。本地 TRAIN transport 的 3 项冻结检查通过，独立 evaluator/scorer/closure 尚未实现。M8 的 9 变体完整集成仍未运行，不能将 projection 提交算作完成。

Messages 实际 actor 的同源码[10 项标签隔离检查](evidence/messages-actual-label-isolation-r1/README.md)已通过。运行 helper 已修正为接受现有额度的有限 token 或金额授权，不再要求新增正额美元付款；禁止充值/付费后备。额度授权仍 pending，金额/总 token 强制限额未建立，未发起真实 supplier prepare/run。

C5 原生会话 45472 仍运行；最近快照为 46 个构建中 40 成功、6 未开始，118 个目标未开始。账户剩余 1%，原 9% 上限不变。完整目标尚未完成；以下保留 11:40 的历史快照。

目标尚未完成。范围保持全部 48 个问题、P0/M1–M9、独立 Q6.3 阶段、全部单模块与条件变体、36 个 pair、5 个 triple、C4 full/LOO 和 C5 TRAIN 选出的组合。单模块阴性不删除组合。问题明细沿用 [48 项接线审计](MODULAR-48Q-REAL-EXECUTION-GAP-AUDIT-20260913.md)；其中 9 月 13 日的运行状态是历史快照，不能当作当前状态。

## 固定实验边界

- 只允许 TRAIN 调参与选择；VAL 只验收冻结候选，不能反馈优化。
- 两个主 benchmark 为 DiscoveryBench 和 BLADE。扩展数据仍按来源组隔离。
- Grok、Icompify 和本地模型分别建立配置、原始记录、用量、选择与验收系列；不能合并为同一次实验。
- 每个完整面板保留失败、未知、阻断和未开始单元；费用未知不能记为零。工程通过、Docker 退出零和 source hash 相同不证明科学效果。
- 当前没有实际 VAL 模型调用或验收结论。没有任何近期不完整面板支持删除模块或组合。

## 已归档的近期真实 Grok 运行

| 面板 | 完整分母 | 原始终态 | 有效验收结论 | 证据 |
|---|---:|---|---|---|
| Q3.1 r2 | 12 | 0 评分；2 评分失败/未知、1 求解失败、1 机制失败、8 未完成 | inconclusive；0 eligible | [独立核算与原件](evidence/actual-ordinary-q31-r2/README.md) |
| M1×M4×M7 r9 | 16 | 4 评分、2 失败、10 阻断 | inconclusive；0 eligible | [独立核算与原件](evidence/actual-admission-prediction-exploration-r9/README.md) |
| M7×M8 r4 | 8 | 6 评分、2 生成程序失败 | 完整面板未通过；0 eligible | [独立核算与原件](evidence/actual-exploration-scheduler-r4/README.md) |

Grok 的账户查询已显示现有周额度耗尽。原运行不更名、不覆盖、不重试未知机会。额度恢复后按新恢复批次补跑尚未执行的义务；不使用其他模型填入 Grok 原分母。

## 新供应商和本地模型

Icompify 的 `/v1/models` 返回 9 个实际可用 ID。对三个候选进行两轮共 6 次试调用后，暂选 `deepseek-v4-pro`；其严格 JSON 和两个实际 Docker 输入案例通过。另两个候选的截断或结构错误保留。该证据仅用于当前接口配置选型，不代表能力排名或科学效果。

[模型列表、试调用和选择原件](evidence/icompify-provider-selection-r2/README.md) 已归档。供应商全量实验尚未派发：现有额度边界待用户回复，接口余额查询为 403。不会充值或开启付费回退。

独立代码分支的已闭合工程证据：

- TRAIN 接入 `ac5f826cf18e2a9c43b5cf40d2b97c2a3d470595`：12 项通过，818 个源码文件未变；完整 Q3.1 12 单元、48 次本机 HTTP、12 次 Docker 和独立 synthetic 评分。它没有真实供应商 benchmark 结果。
- 独立评分器 `ae7ac0a746948acd86b13b84f75a61b0cde7b733`：4 项通过，822 个源码文件未变；实际评分子进程、两个本机 HTTP 评分、原件重放和失败边界。明确保留完整 12 单元中的 2 已评分/10 未评分。仅支持已检验的 TRAIN 主评分接口，不能宣称 VAL 或 lineage 评分已经接通。
- 上述独立分支尚不等于所有模块已整合进同一个生产版本。

本地 Qwen2.5-7B-Instruct 缓存的 14 个文件（15,242,807,270 字节）已复制到 E 盘并核对源/目标 SHA256。专用 Ollama 实例仅用于本系列，参数固定 GPU 0 层、CPU 4 线程、8192 context；量化导入和至多一次本地可用性探针仍在运行。此时没有本地 benchmark 效果结果。

## 尚在运行与尚未闭合

以下为上述时间的进程观测，不是完成声明：

- 实际 Q6.3，原生会话 78795：评分回执列完整 8 单元，其中 5 个 evaluator unknown/failed、3 个 producer failed，科学效果 not_measured；父进程原始 JOIN 尚未返回，尚未作为最终闭合归档。
- C5 全流程工程检验，原生会话 45472：46 个构建中 38 成功、8 未开始；118 个目标仍未开始。完整选择与注册尚未证明。
- Q5.1/Q5.2 全 36 单元工程检验仍在运行。已知可能的结果读取测试缺陷只允许在原运行结束后修复，并对原件重放，不能重写原结果。
- M8 Q3.3/Q3.4/Q3.5 的 projection 接线已有独立提交，但全部 9 个变体的完整实际执行与独立评分检验尚待闭合。
- 其余问题逐项实际 benchmark 测量、全部组合的实际测量、独立评分校准、TRAIN 选择与冻结、VAL 验收及组会完整报告仍有未完成工作。不能用上述工程检验替代。

用户要求的三日目标截止仍为 2026-09-19 07:30 +08。Codex 最初剩余 9%，最新账户剩余 3%；不购买或重置额度，也不因预算不足缩写原验收标准。
