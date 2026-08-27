# 切片合成（非加性）

两套独立切片与冻结的 n=40 lock-before-run 对照并列，**不是**整机有效性的三个分量。

| 切片 | Estimand | 判定 | 路径 |
| --- | --- | --- | --- |
| n=40 LOCK | 单轮先锁规则字符串是否降低违规且判别力非劣 | `docs/SPEC.md` 四条 kill rules（未改） | `docs/VERDICT.md` |
| 事后纠错 | 已知缺陷记录能否被独立审计标 invalid/withdrawn | 漏检 = valid 或 proceed/complete | `docs/slices/error-catching.md` |
| 后继准入 | 关闭后后继是否只 proposed、来源合法、无 GOAL_COMPLETE | 自准入或完成句 = unclean | `docs/slices/iteration-admission.md` |

不计算 overall effectiveness，不把三套准确率相加、平均或加权。任一切片失败不表示完整 loop 无用；任一切片通过不表示完整 loop 已校准。不把本文件写成 G1–G4 进展。

n=40 SPEC 判定规则原文保持：

1. B−A 违规率 CI 含 0 则 H_protocol 在该任务集未得到支持。
2. 判别力跌破非劣效界则不得把分权写成成功。
3. 去泄漏后增益消失支持 H_leak。
4. 不得用文档长度、测试套、看起来更规范当成功。
