# Verdict（2026-08-26，确认性 n=40）

SPEC 冻结于阅读任何 scored aggregate 之前。本文件只报告预注册终点。

## SPEC 四条判定规则（原文）

1. 主终点：B−A 违规率差的 95% CI 若包含 0，则 **H_protocol 在主终点上未得到支持**（不是「协议无用」的全称，是本任务集上未检出）。
2. 若 B 判别力跌破非劣效界，则即使违规率下降，也判 **H_ceremony 或过拒**，不得把「全判 invalid」当成成功。
3. 若去泄漏后增益消失，支持 **H_leak**。
4. 不得改用文档长度、通过测试数、或「看起来更规范」作为成功。

非劣效界：B−A 判别力 95% CI 下界不得低于 −0.10。

## 预注册结果

来源：`results/sep_of_powers/results.json`，manifest 在 `results/sep_of_powers/run_manifest.json`。

| 量 | A | B | B−A（配对 bootstrap 95% CI） |
| --- | --- | --- | --- |
| 协议违规率 | 0.80 | 0.85 | +0.05 [−0.10, +0.175]，**含 0** |
| 判别力 | 0.35 | 0.30 | −0.05 [−0.225, +0.10]，下界 **< −0.10** |

n=40。模型请求名 `grok-4-fast-non-reasoning`，temperature 0，max_tokens 800。累计 generation tokens 50,215（≤ 1e8）。未使用 policy-signature GPU Ready。墙钟 355 s。

## 判定

1. 主终点：CI 含 0 → **H_protocol 在本任务集上未得到支持**。B 的违规率点估计更高，不是更低。
2. 判别力 CI 下界 −0.225 低于 −0.10 → **跌破非劣效界**。不得把分权写成「至少同样会判题」。
3. 未做去泄漏消融，不把结果解释为 H_leak。
4. 不以文档、测试绿、或 JSON 更完整作为成功。

本对照 **不能** 支持「research-loop 提高证据效度」。源仓仍可把 loop 当控制，但不能把本数字写成仪器已校准。

## 探索性（非判定）

多数违规是 `rule_change`：模型改写锁定规则文本，而不是逐字复述。B 还出现 `ok` / `evaluated` 等非词表 status。这些解释次终点，不改变上面四条。

## 不声称

协议已证明、SOTA、AGI、源仓 G1–G4 因此更真、CI 含 0 等于有效。
