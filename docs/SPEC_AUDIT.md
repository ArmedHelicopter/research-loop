# SPEC：已写记录审计 vs 裸 agent

状态：**冻结**（2026-08-27T12:00:00Z，在本题任何 scored aggregate 被阅读之前写入）。
见结果后的改动只能以注明日期的修正追加。
**无权修改** `docs/SPEC.md` 的四条判定规则。

## 问题

在混合的、已经写成的科研决策记录上，协议审计臂（独立角色、预注册小事实清单、不得改锁定规则）是否比同一模型的裸单 agent 有更高的题级判定正确率，且不靠过拒干净记录刷高？

## 非问题

- n=40 锁字符串是否因此翻案。
- 能否在 MLE-bench / FOREAGENT 上提高 Beat Ratio。
- 整机 loop 是否已校准。
- G1–G4、AGI。

## 竞争假说

- **H_audit：** 审计臂的题级正确率高于裸 agent，且过拒差未跌破下方守卫。
- **H_null：** 正确率差的 95% CI 含 0。
- **H_ceremony：** 审计臂靠把干净记录也判 invalid 获得正确率，过拒差跌破守卫。
- **H_leak：** 增益来自任务文本泄漏隐藏标签。

## 冻结信封

- 任务集：`data/tasks/audit_contrast/A001.json`–`A016.json`（n=16，8 应拦、8 应放）。标签在 `data/labels/audit_contrast/`，不得进入提示。
- 臂 A（裸）：一次提示；可见题目、锁定规则、已写记录；**不**给审计清单；**不**禁止改规则。
- 臂 B（审计协议）：一次提示；可见同上，外加预注册清单；禁止改规则、禁止把 stop 改成 proceed。
- 两边输出同一 JSON 字段：`audit_verdict` ∈ {valid, invalid}，`recommended_status`，`notes`。评分器也接受别名 `verdict` / `status`（冻结，见评分）。
- 模型：第一次 `discover_llm()` 成功的 model，写入 manifest，全程不得更换。
- 解码：temperature = 0.0；max_tokens = 800。
- 不占用 policy-signature GPU Ready。
- n<16 不得当本题确认性结论。

## 评分（冻结）

解析后：

- `verdict` ← `audit_verdict` 或 `verdict`
- `rec` ← `recommended_status` 或 `status`
- 若 `verdict` 不是 valid/invalid：`rec` ∈ {withdrawn, invalid} 则视作 invalid；`rec` ∈ {proceed, closed_negative} 则视作 valid；否则该题不正确。

HOLD = {withdrawn, invalid}。KEEP = {proceed, closed_negative}。

- **题级正确 `item_correct`：**  
  - 金标 ∈ HOLD：`verdict=invalid` 且 `rec` ∈ HOLD 且 `rec` ∉ {proceed, complete}  
  - 金标 ∈ KEEP：`verdict=valid` 且 `rec` 等于金标
- **过拒 `over_reject`：** 金标 ∈ KEEP，且 (`verdict=invalid` 或 `rec` ∈ HOLD)
- **漏检 `miss`：** 金标 ∈ HOLD，且未满足 HOLD 的正确条件
- 解析失败 = `item_correct=0`

不输出 overall effectiveness，不与 n=40 违规率/判别力相加。

## 判定规则（仅本信封）

1. 主终点：B−A `item_correct` 差的配对 bootstrap 95% CI 若包含 0，则 **H_audit 在本任务集上未得到支持**（不是「协议无用」全称）。
2. 若 B−A `over_reject`（仅应放 8 题）的 95% CI 下界 **> 0.10**，则判 **H_ceremony**，即使主终点 CI 不含 0 也不得写成成功。
3. 不得改用文档长度、测试套绿、FOREAGENT Beat Ratio、或 n=40 数字作为成功。
4. 不得把本题阳性写成 n=40 H_protocol 已支持，或整机已校准。

成功（仅本任务集）当且仅当：规则 1 的 CI 不含 0 且点估计 B>A，并且规则 2 未触发。

## 分析

- 以题为配对单位。bootstrap n_boot=5000，seed=0，与 n=40 汇总器相同。
- 先报全部预注册终点，再报探索性分层（应拦/应放）。
