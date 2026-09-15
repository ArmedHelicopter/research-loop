# 实际 Headless Review r2 归档

## 范围与来源

本目录保存提交 `02959f51896332037cfeb46ed9ebb548039b85b1` 的已关闭 TRAIN 诊断 review r2 的公开元数据、闭包、独立回放和审计辅助脚本。r2 与先前 r1 相关联，不能作为独立样本。

## 已冻结的运行事实

- 预留了 86 个 MAIN 机会；85 个 native MAIN receipt 被接受。最后 1 个机会在 MAIN 启动前被 prelaunch guard 拒绝，因此没有产生第 86 个 MAIN 进程。
- 最终拒绝时，三个账户观测均已完成，但最早观测到快照完成时的年龄是 `12.237717` 秒，超过冻结上限 `5` 秒。原始记录没有保存底层 guard 异常文本；本归档不推断其具体异常类型。
- 已记录 25 个仅供诊断的评分。标题 token 与 all-call settlement 均为未知，不能将已知 MAIN token 用作完整结算。
- 独立回放得到完全一致的结果与 journal；回放前后 2,156 个原始文件元数据未变。这证明该回放的一致性，不证明科学效果。
- 私有原始证据 ZIP 保留 2,159 个成员。该 ZIP 不在公开目录；这里的 `private-run-inventory.json` 只保留成员路径、大小、mtime 和散列等元数据，实际保留路径和摘要见 `run-summary.json` 的 `private_retention`。
- 总配额 180：r1 已用 11，r2 预留/计入 86，累计 97，剩余 83。

## 证据边界

这是相关联的 TRAIN 诊断运行记录。它不构成科学有效性、正式 calibration、VAL 使用或 VAL 验收声明；`calibration_eligible=false`、`validation_eligible=false`，且科学有效性未测量。公开目录不包含原始 prompt、认证材料、私钥或私有 native 原始输出。

`run-summary.json` 汇总运行与配额，`parent-closure.json` 绑定闭包，`independent-readback.json` 保存独立回放元数据，`private-run-inventory.json` 绑定私有保留物的元数据。`manifest.json` 对本目录的精确公开文件集合（包括本 README）和除自身外每个公开文件的散列进行登记。
