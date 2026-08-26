# AGENTS.md — research-loop-validity

本仓库只回答 README 里的那一句问题。它没有完成态。任何 session 不得宣告「协议已证明有效」「科研 agent 问题已解决」或任何 AGI 完成句。

## 本仓与源仓的关系

- 源仓：`E:\_ryanDev\AI\policy-signature`。那边的 programme、G1–G4、评估器和 docket 不在本仓范围内。
- 本仓可以引用源仓的失败记录和协议文本，作为设计来源和负例。
- 不得把源仓未发表的 persona 结果、claims JSON、PSB 原题（含 `gate.json` 判定）复制进来当任务。

## 循环禁止

验证「分权 loop 是否有效」时，**不得**用被测 loop 来：

- 生成或准入本实验的后继问题
- 在见到对照数字后改 SPEC 里的成功标准
- 把 auditor 的 valid 解释成科学上的 proceed

对照的判定规则只写在 `docs/SPEC.md`。改规则必须追加注明日期的修正，并标明此后分析是探索性的。

## 允许做的

- 实现 SPEC 里的任务格式、臂、评分器。
- 在评分器与任务文本隔离的前提下写测试。
- 记录阴性结果和协议偏差。

## 不允许做的

- 把 FIFO 换成预测排序或 ForeAgent 式执行前筛选。
- 为了让数字好看而扩大任务集、放松违规定义、或把「文档更全」当主终点。
- 在本仓写入 `GOAL_COMPLETE`、programme 完成、或「AI4Agent AGI 已实现」。
- 用源仓 GPU 配额「证明治理」，除非源仓独立 admit 且不占 G1–G4 Ready。本仓实验默认用 API / 本地 CPU 上的决策任务。
