# 一天限定用途验证：已有证据与缺口

调查时间：2026-09-10 23:41 UTC。只续接已完成审查，不重开广泛文献调查。

## 已占据：引用，不重复主张

- 8 月 n=40、修正 workflow n=16 未通过整体启用标准；历史 B token 成本约为 A 的 5.07 倍。来源：本仓 docs/VERDICT.md、docs/VERDICT_WORKFLOW.md 及仓外 research-loop-effectiveness-check.md。
- 5626f668 的运行包已有确定性约束、双审计、版本冻结和回滚；fixture 不证明模型增益。来源：docs/SELF_IMPROVING.md。
- policy-signature 实际沿自身 controller 运行，不依赖新增运行包。G4 原始 inconclusive 被自报 length_artifact_only 覆盖并晋升，schema 校验仍 VALID。来源：仓外 policy-workflow-dependency-check.md；源仓纠错提交 1c1890e。

## 开放问题

修复后的真实结果—outcome—claim 链能否拒绝上述错误且允许诚实关闭？新增运行包在有限、独立构造的科研证据裁决任务上，相比单执行者加独立最终裁决，是否增加足够正确判断以抵偿成本？两者都未由工程测试回答。
