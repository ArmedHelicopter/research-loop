# 调查：Kwok et al. LLM-as-a-Verifier 与本仓 loop

时间：2026-08-27。来源：arXiv:2607.05391v2（Kwok, Li, Atreya, Liu, Jiang, Finn, Pavone, Stoica, Mirhoseini）。PDF 只作阅读，不进仓库。

## 论文实际主张

- 验证（判断解是否正确）是生成之外的新缩放轴。
- 方法：不对 LM-judge 的离散分词取 argmax，而对评分 token 的 logits 取期望，得到连续分；再沿三条轴放大——分值粒度、重复评估、准则分解。
- 用 Bradley–Terry 把连续分变成偏好概率，再用 Probabilistic Pivot Tournament 在候选轨迹里选最好的（从 O(N²) 降到 O(Nk)）。
- 用途：测试时选轨迹、进度监控、给 SAC/GRPO 当稠密奖励。
- 数字（他们的基准，不是本仓的）：Terminal-Bench V2 86.5%，SWE-Bench Verified 78.2%，RoboRewardBench 87.4%，MedAgentBench 73.3%。Oracle Pass@K 在 Terminal-Bench 上可到 98.9%，瓶颈是「谁来挑对的轨迹」。

## Occupied — 将引用，不声称

- **带分数的轨迹验证 / 测试时选优 / 稠密奖励。** 这是 agent 工程的 verifier-as-ranker，不是科研决策协议。
- **准则分解后仍合成可排序的连续分。** 与本仓 auditor「只做二元小事实、永不打分」方向相反。
- 不得把 86.5% / 78.2% 或「验证可缩放」写成 loop 有效。

## 和 loop 的关系（相邻，不可替换）

| | Kwok et al. | 本仓 research loop |
| --- | --- | --- |
| 对象 | 编码/机器人/医疗 agent 轨迹好不好 | 科研决策记录是否协议违规 |
| 输出 | 连续分 → 排序 → 选轨迹 / RL 奖励 | `valid`/`invalid`，禁止量表 |
| 失败模式 | 离散 judge 打平、挑不出 Pass@K 里的对解 | 假完成、见结果改门槛、无效检验当阳性 |
| Goodhart | 分是拿来最大化的（选优、RL） | 故意不设可最大化的分 |

「把大判断拆成多条准则」看起来像 auditor 清单。差别是：他们把分解结果**加回一个可排序的分**；我们规定分解结果**不得**合成 overall effectiveness，也不得拿来给后继排序（FIFO，禁止偏好模型）。

若把 LLM-as-a-Verifier 接进 auditor，就是用可最大化的分替换二元审计，直接违反 `protocol/research-loop.md` 和反 Goodhart 设计。本仓不实现、不对照他们的基准。

## Open（仍属本仓）

在**不见正确规则**的科研决策题上，真 LOCK-before-RUN 是否降低假完成 / 改门槛 / 假阳性，且判别力非劣。见 `docs/SPEC_TRUE_LOCK.md`。这不是他们的 Pass@K 选轨迹问题。
