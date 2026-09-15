# Headless TRAIN 产物链冻结检查

源码 `4c096f4fa65be10beb3b1dc95fefc64c0f5410ff` 的 91 项检查全部通过，
无失败、错误或跳过，用时 322.563 秒。764 份源码和文档在检查前后字节一致；
`sources.zip` 保存实际受检字节，`before.json`、`closed.json`、`checks.xml`
绑定源码、检查参数和结果。先前开发检查不计入本轮分母。

实际链路为：冻结公共请求 → headless 原始进程/账户观察 → 独立原件读取器
→ TRAIN provider 封存 → 模块或组合单元消费 → 独立评分及最终原件复核。
headless 与 ACP 保留不同的配置和回执格式，失败原件与未知用量保留。

检查包括 24 次合成 MAIN 的单模块 controller、两次各 40 次合成 MAIN 的
M4/M5 四臂八格（正常与末次评分后篡改）、原有 ACP 四臂回归，以及标签隔离。
篡改用例保留已经收到的八份评分，但最终有效评分格为零，结果为 inconclusive。
这不是因单模块阴性而删除组合；四臂及原定分母均保留。

`selected-synthetic-originals.zip` 保存八个选定完整用例目录、3,879 份原始文件。
逐文件摘要、大小及 mtime 在归档前后相同，见 `selected-originals.json`。
选定原件包含正常、后置拒绝、未知用量、损坏及故意修改的副本，不能把它们都
视为获准消费的产物。用例中的认证值、HTTP 返回和模型输出均为合成材料。

检查使用实际本地子进程、受限 Docker 和独立评分进程，未调用真实模型或付费
API，未读取真实 VAL。完整 headless C4/C5 网格及真实 benchmark 效果不在本轮
覆盖范围；单模块、配对、高阶组合、消融和 VAL 验收继续按各自冻结协议执行。
产物追溯契约与覆盖缺口分别见仓库 docs 中的 MODULE-ARTIFACT-PROVENANCE.md
和 MODULE-ARTIFACT-COVERAGE.md。
