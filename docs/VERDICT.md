# Verdict（2026-08-26，确认性 n=40，B 观察轮含任务主干）

SPEC 冻结于首次阅读 scored aggregate 之前。B 臂观察提示曾漏掉 `_stem`，该次结果作废。本文件只报告修复后、同一冻结信封的重跑。判定规则未改。

## SPEC 四条判定规则（原文）

1. 主终点：B−A 违规率差的 95% CI 若包含 0，则 **H_protocol 在主终点上未得到支持**（不是「协议无用」的全称，是本任务集上未检出）。
2. 若 B 判别力跌破非劣效界，则即使违规率下降，也判 **H_ceremony 或过拒**，不得把「全判 invalid」当成成功。
3. 若去泄漏后增益消失，支持 **H_leak**。
4. 不得改用文档长度、通过测试数、或「看起来更规范」作为成功。

非劣效界：B−A 判别力 95% CI 下界不得低于 −0.10。

## 预注册结果

来源：`results/sep_of_powers/results.json`，manifest：`results/sep_of_powers/run_manifest.json`。

| 量 | A | B | B−A（配对 bootstrap 95% CI） |
| --- | --- | --- | --- |
| 协议违规率 | 0.90 | 0.825 | −0.075 [−0.225, +0.075]，**含 0** |
| 判别力 | 0.325 | 0.175 | −0.15 [−0.30, 0.00]，下界 **< −0.10** |

n=40。请求模型 `grok-4-fast-non-reasoning`，temperature 0，max_tokens 800。本轮 generation tokens 55,215（≤ 1e8）。未使用 policy-signature GPU Ready。墙钟约 282 s。

## 判定

1. 主终点：CI 含 0 → **H_protocol 在本任务集上未得到支持**。点估计 B 违规略低，但不能当作检出。
2. 判别力 CI 下界 −0.30 低于 −0.10 → **跌破非劣效界**。B 判对率点估计更差。
3. 未做去泄漏消融，不解释为 H_leak。
4. 不以文档或测试绿当成功。

在匹配上下文的 A/B 对照下，**不能**支持「research-loop 提高证据效度」。源仓仍可把 loop 当控制，不能把本数字写成仪器已校准。

## 不声称

协议已证明、SOTA、AGI、源仓 G1–G4 因此更真、CI 含 0 等于有效。
