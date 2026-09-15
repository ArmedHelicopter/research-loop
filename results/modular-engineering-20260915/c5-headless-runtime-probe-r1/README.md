# 一次完整模块链的产物追溯实例

这次工程探针执行了一个 history 构建和一个 target，覆盖 M1–M9 的相应阶段。
它使用 11 次合成 solver 调用与实际 Docker，没有运行 evaluator。冻结计划含
46 个构建和 118 个目标；这次探针没有执行完整 C5 网格，也没有真实效果结论。

从 [逐产物索引](artifact-view/graph.json) 可以定位到每个描述符的原始文件和
行号、输入父引用、源码、配置和输出摘要。索引含 212 个节点、311 条目录父引用
及一条明确的 history→target 构建绑定；父引用不自动等于科学支持关系。

| 模块 | history 节点 | target 节点 | 保留的状态 |
| --- | ---: | ---: | --- |
| P0 | 1 | 1 | 冻结运行入口 |
| M1 | 1 | 1 | 产生 |
| M2 | 14 | 14 | 每阶段包含一条撤回记录 |
| M3 | 6 | 7 | 产生 |
| M4 | 2 | 2 | 产生 |
| M5 | 7 | 7 | 产生 |
| M6 | 14 | 14 | 产生 |
| M7 | 8 | 8 | 产生 |
| M8 | 13 | 14 | history 未启用；target 产生 |
| M9 | 8 | 0 | 只在 history 构建阶段运行 |
| 未归属模块的 trace | 34 | 36 | 保留 uncovered 标记 |

[原件保留清单](retention-manifest.json) 对应私有 ZIP 的 2,304 个成员，保存来源、
摘要、大小和修改时间；凭据及 reparse 路径单独排除。私有档案位于
`E:/_ryanDev/AI/research-loop-modular/retained-private-evidence/c5-headless-runtime-probe-r1/originals-without-credentials.zip`。
九份 [生产源码副本](producer-source-afterrun-manifest.json) 与这 212 个描述符的
源码摘要吻合。公开副本和私有成员已读回比对，原始字节和修改时间保持不变。

旧失败报告与成功报告分别保留。首次收集失败没有现存 basetemp；早期各次
源码快照缺失，现有源码副本只证明运行后内容吻合，不证明全程冻结。
[原始运行说明](c5-headless-runtime-probe-r1-receipt.md)、[暂存清单](public-manifest.json)
和 [补充清单](supplement-manifest.json) 均保持原样。该实例没有打开 VAL；
所有优化仍仅能使用 TRAIN，独立验收及全部问题、组合实验另有完整分母。
