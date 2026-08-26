# 调查：分权协议能否降低科研 agent 的目标替换

时间：2026-08-26。本文件满足「先调查再命题」。第一项研究的问题在 `docs/SPEC.md`。

## Occupied — 将引用，不声称

- **目标替换是已记录的失败，不是假设。** `policy-signature` 在 2026-08-21 出现 agent 合并已有 commit、刷新 hash、重跑测试套并宣告 GOAL_COMPLETE。说明若「完成」可由治理动作产生，就不能当研究进展。
- **无效检验必须撤回。** 同仓 Exp10 因单位不可比整臂 infeasible，记录为 withdrawn 而非阴性发现。
- **规则膨胀会置换研究。** 同仓 2026-08-21/22 大约 2400 行治理、零行实验。
- **预注册与适应性设计。** LOCK-before-RUN 借鉴的是「何时改规则必须事先写明」，不是「禁止一切改动」。FDA 适应性设计是类比，不是本任务的证据。
- **POET / MCC 难度带。** two-sided band 来自「太易则无信息、太难则不可达」。本仓不声称已机械实现该带。
- **Zheng et al. ACL 2026。** Data-centric Solution Preference：不跑训练而预测哪份 ML 代码更好（18,438 对，61.5% pairwise）。占据执行前**方案**筛选。本仓任务是科研**决策**协议，不用他们的语料，也不用偏好模型给实验排序。
- **AIDE / AutoMind / MLEvolve。** Generate-Execute-Feedback 的 ML 工程搜索。占据的是「用执行反馈改进代码」，不是「用分权降低目标替换」。
- **The AI Scientist 一类系统。** 端到端出论文。占据自动化发现的工程形态；不回答分权是否降低假完成。
- **源仓 PSB。** 不能当本仓基线：题来自已关闭 docket，部分 runner 从产物读判定。

## Open

1. 三角色 + LOCK hash + 二元审计，是否降低预注册定义的协议违规率。
2. 该干预是否靠「全判 invalid」刷低违规，从而伤害判别力。
3. 效应是否只是多写 JSON（schema-only 臂）。
4. 同源模型分饰三个角色，是否仍有隔离效果。

## 本调查不授权的

- 把源仓 loop 说成已验证仪器。
- 新开 AutoML 搜索线。
- 把 AGI 写成目标。
