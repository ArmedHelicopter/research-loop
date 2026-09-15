# 谱系评分工厂与单格评分封存

冻结源码 `67d38e1148a9342fdb447c65c4a3eceee4fc33bb` 通过 41 项检查，
无失败、错误或跳过，用时 146.594 秒；774 份源码及文档字节未变。
[关闭回执](closed.json)、[JUnit](checks.xml)与[源码清单](source-members.json)
分别保留。检查使用合成 OS/HTTP 模型响应及实际受限 Docker，没有真实 Grok、
付费 API 或 VAL 调用。

工厂以明确声明绑定 evaluator 的完整配置、私有目录、源码、rubric 和分配，
headless MAIN 用量使用独立契约；失败后的已知用量仍保留，标题与结算未知。
多个 panel 共用的参考材料单独核对，各 worker 的不同私有配置保留各自声明。

lineage 专用封存逐项核对外层签名评分、嵌套 primary 评分、原始调用、派生
维度及谱系端点。参考材料摘要必须等于该任务的冻结 reference pin；只重算
摘要并重新签名不能替换它。重复读取、重启后原件修改和未知用量拒绝都在
本次检查范围；封存尝试之后不再接收评分。primary 封存与标签隔离同时回归。

[原件清单](selected-originals.json)保留 11 个完整用例、823 份文件，ZIP
成员与原件内容、摘要及 mtime 均核对。故意修改的原件仍按拒绝用例保存。

这里验证了实际单格 driver→Docker→签名输入→worker→native evaluator→
封存的路径。client 回包验证和 pool 配置也有局部检查，但新的完整四 panel
stdio 流程及外层 TRAIN 控制器尚未接入最终 gate；不能据此宣称 34 格 headless
实验或模块效果已经完成。此前子代理的分段检查不叠加到这 41 项分母。
