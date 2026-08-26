# Verdict（2026-08-26）

本文件写于 SPEC 冻结之后。确认性 n=40 任务集与标签隔离已落地。
**没有阅读任何模型 scored aggregate，因为本环境不能调用 LLM。**

## SPEC 四条判定规则（原文）

1. 主终点：B−A 违规率差的 95% CI 若包含 0，则 **H_protocol 在主终点上未得到支持**（不是「协议无用」的全称，是本任务集上未检出）。
2. 若 B 判别力跌破非劣效界，则即使违规率下降，也判 **H_ceremony 或过拒**，不得把「全判 invalid」当成成功。
3. 若去泄漏后增益消失，支持 **H_leak**。
4. 不得改用文档长度、通过测试数、或「看起来更规范」作为成功。

非劣效界保持：B−A 判别力 95% CI 下界不得低于 −0.10。

## 本环境实际完成的

- 公开任务 40、隐藏标签 40、id 对齐。
- 臂 B 的提示路径先提交 `decision_rule` 再给 `new_observation`；sha256 在观察前计算。
- `python -m pytest tests` 通过（含标签隔离、withdrawn 上 proceed 不得算 clean）。
- `python -m experiments.sep_of_powers.cli --task T001 --arm A|B` 各启动两次，均因缺少 API 密钥以退出码 2 结束。

## 本文件不声称的

- H_protocol 得到支持或被证伪。
- 任何违规率、判别力、CI、SOTA、AGI、或「协议已证明有效」。
- CI 包含 0 被当成协议有效。

缺 `XAI_API_KEY` / `GROK_API_KEY` / `OPENAI_API_KEY`。密钥可用后，用冻结信封跑 n=40 配对，再把数字写入 run manifest；在那之前不得补造模型输出。
