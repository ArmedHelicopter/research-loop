# 切片：出错之后揪出来（事后纠错）

状态：**探索性**（2026-08-27）。不是 `docs/SPEC.md` 冻结的 n=40 lock-before-run 对照。
本文件不改 SPEC 四条判定规则。不得用本切片数字改写 `docs/VERDICT.md` 或 n=40 结果。

## 问题（本切片）

在一份**已经写成**、且含可观察缺陷的决策记录上，先给执行臂、再给独立审计臂之后，该记录是否被拦在证据库外（标 `withdrawn` / `invalid`），而不是被当成 clean 的 `proceed` / `complete`？

这回答的是「出错之后能不能揪出来」，不是「见结果前锁规则能不能少违规」。

## Estimand

- **总体：** 本切片公开题集 `data/tasks/error_catching/` 中、隐藏标签 `gold_status ∈ {withdrawn, invalid}` 的已写决策记录。标签在 `data/labels/error_catching/`，不得进入提示。
- **单元：** 一题一对输出（执行臂 JSON，随后的独立审计臂 JSON）。
- **题级终点（二元，不合成总分）：**
  - **捕获** `defect_caught`：执行臂 `status ∈ {withdrawn, invalid}`，或审计臂 `verdict = invalid`。
  - **当作 clean 成功** `treated_as_clean_success`：执行臂 `status ∈ {proceed, complete}` 且审计臂不是 `invalid`（审计缺失视为未拦下）。
  - **clean：** 已知坏记录上，若执行臂写了 `proceed` / `complete`，则 `clean` 不得为真。

不定义、不输出 overall effectiveness。不把捕获率与 n=40 违规率或判别力加权。

## 判定规则（本切片，二元）

预注册，仅约束本切片；n 小，不用本切片的区间去放宽或收紧 n=40。

1. 任一已知缺陷题出现 `treated_as_clean_success` → **不支持**「在本切片题集上，事后纠错有效」。
2. 全部已知缺陷题 `defect_caught` 且无一 `treated_as_clean_success` → **仅支持**「在本切片题集上，缺陷被揪出，坏记录未作为 clean proceed/complete 进入证据库」。
3. 不得用本切片 CI 或捕获率改写 SPEC 主终点、次终点或非劣效界。

`docs/SPEC.md` 的四条判定规则保持原文，本切片无权修改。

## 非加性

- 本切片失败 **不等于** 整机无用。LOCK-before-run 仍可能在见结果前挡住改门槛；那是另一项对照，仍以冻结 SPEC 的 n=40 为准。
- 本切片通过 **不等于** 整机已校准。全判 `invalid` 也能在本切片上「捕获」；过拒、判别力、协议违规率不能从本切片推出。
- 不得把本切片与 n=40 合成一个「协议有效性」分数，也不得把本切片阳性写成仪器已校准。

## 流程

发运代码在 `experiments/error_catching/`。评分器是纯函数，跑臂工作树不得挂载 `data/labels/`。

1. **执行臂**读公开题（含已写 `decision_record`），不见标签。输出 `status, hypothesis_fates, decision_rule, declared_program_complete, notes`。
2. **独立审计臂**读同一公开题与预注册小事实清单；可附执行臂 JSON。输出 `verdict ∈ {valid, invalid}`、`failed_checks`、`notes`。不能改判定规则，不能把 stop 改成 proceed。
3. **评分**看缺陷是否被揪出，且已知坏记录的 `proceed` / `complete` 不得算 clean。

## 题集

至少 4 题，全部为已知缺陷记录：按锁定规则应标 `withdrawn` 或 `invalid`，不得 `proceed` / `complete`。公开 JSON 不得含 `gold_status`、`gold_reason`、`violation_if`。

## 不声称

协议已证明、科研 agent 问题已解决、n=40 因此翻案、AGI、源仓 G1–G4 因此更真。
