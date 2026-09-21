# 现有 TRAIN 任务独立复算与缓存支线收尾

2026-09-21。用户授权：落实缓存支线收尾，并先复核 SES，再复核另外两个已有任务。基点 `052b874bd39c83ff2c539fb67cc151ced255076e`，分支 `codex/week1-evidence-cost`。

**结果：三个任务、四条已完成流程的所选数值与结构检查全部通过；没有新增模型调用。停止 C、S 留在实验目录的决定不变。** 数值复算并不补齐原始数据加工、因果识别、代表性或正式 benchmark 评分。

- [审查结论与逐任务边界](REVIEW.md)
- [缓存支线正式收尾与后续决策](CLOSURE.md)
- [独立复算脚本](verify_existing.py)
- [完整复算结果与逐项差异](recomputation-r1.json)
- [公开指标定义及本地证据](SOURCES.md)
- [交付文件清单](MANIFEST.json)

成功标准：核对冻结输入；另写计算而不执行/导入原分析代码；核对样本、分位界限、数值与最终解释；明确不能回答的研究问题；保留失败和原始结果；不增加模型实验、不晋升 S、不实现 C、不修改核心、账本或调度。

运行环境记录在 JSON 中。依赖为 Python、NumPy 与 SciPy；没有安装新依赖。CSV 由标准库读取，分位数、人数、比例、Pearson 相关由标准库独立计算；Logistic 用 score equations 与 HC0 sandwich covariance，OLS 用 normal equations 与 Bartlett HAC。没有使用 pandas、statsmodels 或项目中的分析函数。SciPy 仅提供 Student-t 分布函数。

本次在 reviewing agent 内采用独立实现，已阅读原代码和结果；不是盲法复现，也不是第二位独立人类的审稿。脚本不包含模型、网络或子进程入口，限定读取已冻结 TRAIN 的三份公开导出，不读取正式 VAL 标签。

从任意目录复算，输出必须是不存在的新路径（下列 work 目录需自行选取新文件名，禁止覆盖已有回执）：

```powershell
python -B E:/_ryanDev/AI/research-loop-week1/experiments/week1_evidence_cost/task-correctness-r1/verify_existing.py --source E:/_ryanDev/AI/research-loop-week1 --output E:/_ryanDev/AI/research-loop/work/task-correctness-20260921/recomputation-new.json
```

异机需要取得 `qualification/r4/public-index.json` 所绑定的三个 data.csv 和 public.json，并确保路径与 SHA256 相符。脚本遇到不匹配即失败，不下载替代版本，不把数据缺失当成通过。浮点容差固定为绝对 `5.1e-7`、相对 `1e-10`，整数精确一致；涵盖归档六位小数的舍入误差。

复算结果包含 401 项检查：SES rich 38、SES short 117、监禁 114、世界银行 130、已存 AND 反例结构 2。它们含数组长度、重复的 complete-case 对照及字符串/结构检查，不是 401 个独立统计结果或任务。最丰富 SES 的 8 条主分析统计和 6 条后续统计全部在内。

原六次运行机会、失败控制器、无结果检查、46/60 超时批次、预算和冻结规则全部保留。旧报告中的“统计未经独立验证”描述其当时状态；本目录仅新增有限复算证据，不倒改旧回执，不将 `scientific_validated` 或 `needs_review` 自动晋升。
