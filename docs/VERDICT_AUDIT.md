# Verdict：已写记录审计 vs 裸 agent（2026-08-27）

SPEC 冻结于 `docs/SPEC_AUDIT.md`，在阅读 scored aggregate 之前。本题 **不是** n=40 锁字符串对照。`docs/SPEC.md` 四条判定规则未改。

## n=40 SPEC 判定规则（原文，未改）

1. 主终点：B−A 违规率差的 95% CI 若包含 0，则 **H_protocol 在主终点上未得到支持**（不是「协议无用」的全称，是本任务集上未检出）。
2. 若 B 判别力跌破非劣效界，则即使违规率下降，也判 **H_ceremony 或过拒**，不得把「全判 invalid」当成成功。
3. 若去泄漏后增益消失，支持 **H_leak**。
4. 不得改用文档长度、通过测试数、或「看起来更规范」作为成功。

## 预注册结果

来源：`results/audit_contrast/results.json`，manifest：`results/audit_contrast/run_manifest.json`。

| 量 | A 裸 agent | B 审计协议 | B−A（配对 bootstrap 95% CI） |
| --- | --- | --- | --- |
| 题级正确率 | 1.00 | 0.875 | −0.125 [−0.3125, 0.00]，**含 0** |
| 过拒率（应放 8 题） | 0.00 | 0.125 | +0.125 [0.00, 0.375]，下界 **≤ 0.10** |
| 漏检率（应拦 8 题） | 0.00 | 0.125 | （探索性） |

n=16（8 应拦 / 8 应放）。模型 `grok-4-fast-non-reasoning`，temperature 0，max_tokens 800。generation tokens 13,044。墙钟约 58 s。未使用 policy-signature GPU Ready。

B 错两题：A006 应拦却给出 `recommended_status=closed_negative`；A014 应放却判 `invalid`。

## 判定（`docs/SPEC_AUDIT.md` 规则）

1. 主终点 CI 含 0 → **H_audit 在本任务集上未得到支持**。点估计 B 更差，不能当作检出。
2. 过拒 CI 下界 0.00，未 > 0.10 → **不判 H_ceremony**。
3. 不以文档、测试绿、FOREAGENT Beat Ratio、或 n=40 数字当成功。
4. 本题未支持不得写成 n=40 翻案，也不得写成整机已校准。

按冻结成功条款：需要 CI 不含 0 且 B>A，且过拒守卫未破。两项成功条件都未满足。

## 限制

- 裸臂顶到天花板（16/16），功效主要来自 B 是否失手；n=16 的 CI 宽。
- 干预是审计协议包（角色 + 清单 + 不得改规则），不是完整 executor→auditor→proposer 闭环。
- 未与 FOREAGENT / AIDE / AI Scientist 做匹配对照（构念与任务都不同，见 `docs/survey-audit-contrast.md`）。

## 不声称

协议已证明、比裸 agent 有效、比已有开源/闭源项目有效、n=40 H_protocol 被挽救、AGI、G1–G4 进展。
