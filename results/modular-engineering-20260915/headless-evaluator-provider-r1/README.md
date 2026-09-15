# 私有 headless evaluator 与主评分工厂检查

冻结源码 `cb93900360779f066bd68e8c11fe257eaa5026c7` 通过 60/60 项检查，
335.5 秒，无失败、错误或跳过；768 份源码/文档在检查前后字节一致。
源字节 ZIP、JUnit、冻结/关闭回执和运行参数均在本目录。

检查覆盖私有 rubric 请求、固定模板与模式、实际本地子进程/合成 HTTP、
两个 benchmark 的 primary 工厂→私有参考解析→native evaluator→签名评分，
以及既有 Codex evaluator、scorer stdio、组合评分和标签隔离回归。
四个完整选定用例的 304 份原件逐文件核对，归档前后字节和 mtime 不变。

启动前拒绝保留 receipt 和未知 MAIN 用量；启动后拒绝保留已知 MAIN 用量
及未消费的原始输出。给类型化 response 末尾加换行也会使后续读取拒绝。
第一次开发检查的测试断言误用了 receipt 属性；失败记录保留，不计入本轮。

这是逐调用读取与 primary 工厂的工程检查，未调用真实 Grok、付费 API 或
读取真实 VAL。完整 controller 的最后一次评分后封存核验，以及 lineage
评分工厂接入尚需各自集成检查；本轮通过不代替它们，也不证明科学效果。
