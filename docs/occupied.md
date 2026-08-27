# Occupied 与 Open

调查时间：2026-08-26。对象：能否把科研 agent 分权协议当成已证明有效的治理仪器。

## Occupied — 将引用，不声称

- **2026-08-21 源仓失败。** Agent 用合并、刷新 hash、重跑测试套宣告 GOAL_COMPLETE。说明「完成」若可由治理动作产生，就不能当研究进展。来源：`policy-signature` 的 `AGENTS.md`、`tests/test_goal_integrity.py`。
- **2026-08-22 Exp10 withdrawn。** 闭环臂因单位不可比而整臂 infeasible；正确处理是撤回，不是收窄成「调度无优势」。来源：`policy-signature/EXPERIMENT_LOG.md`。
- **治理膨胀。** 源仓记录 2026-08-21/22 大约 2400 行治理、零行实验。说明未受证据约束的规则会置换研究。来源：`policy-signature/AGENTS.md`。
- **Zheng et al. ACL 2026。** 执行前预测哪套 ML 解法更好（18,438 pairwise，FOREAGENT Predict-then-Verify）。占据的是 AutoML 搜索筛选，不是科研决策协议效度。不得把 61.5% 或 +6% Beat Ratio 当成 loop 有效的证据。
- **Kwok et al. 2026，LLM-as-a-Verifier（arXiv:2607.05391）。** 对评分 token logits 取期望得到连续分，再排序选轨迹 / 当 RL 奖励。占据的是可最大化的 verifier 分，不是二元协议审计。不得把 Terminal-Bench 86.5% 或 SWE-Bench 78.2% 当成 loop 有效。详见 `docs/survey-llm-verifier.md`。
- **源仓 PSB。** 自称 loop 正确性基准，但题来自已关闭 docket，部分 runner 从产物读判定。占据的是「不要用这套数字」。

## Open

- 分权 + LOCK + 二元审计是否降低科研决策上的协议违规，且判别力非劣。见 `docs/SPEC.md`。
- 源仓文档与代码不一致的 LOCK hash / two-sided band，补成可执行干预后，效应是否还在。
- 不同模型族上三角色是否仍有隔离效果（同源模型分饰可能只是提示分工）。

## 本仓不得占用的主张

- policy-like behavior 的内部 signature（G1）。
- 人格接口的强度 / 能力 / 可逆性（G3/G4）。
- 「AI4Agent 领域的 AGI」。
