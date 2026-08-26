# AGENTS.md — research-loop

本仓库的 programme 是 README 里那一句对照问题。没有完成态。不得宣告协议已证明、科研 agent 问题已解决、或任何 AGI 完成句。

## 与 policy-signature 并行

源仓的 G1–G4 / X 评估器继续在那边跑。本仓不占用那边的 GPU Ready。本仓默认用决策任务和 API / CPU。

## 循环禁止

检验协议时，不得用被测协议来：

- 生成或准入本实验的后继问题
- 见对照数字后改 `docs/SPEC.md` 的成功标准（只能追加注明日期的修正）
- 把 auditor 的 valid 解释成科学上的 proceed

## 标签隔离

`data/labels/` 不得出现在跑臂的工作树、提示或日志里。评分器在隔离进程中读标签。测试 `tests/test_label_isolation.py` 失败则禁止跑模型。

## 允许 / 不允许

允许：实现 SPEC 中的任务格式、臂、评分器；写隔离测试；记录阴性结果。

不允许：用预测排序替换 FIFO；为数字放松违规定义；把「文档更全」当主终点；复制源仓 PSB 原题或未发表 persona 结果。
