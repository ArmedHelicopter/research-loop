# C5 common digest r1：截止归档暂存

这是提交 `105dfcd321faa3245b9a1605515e1eb147d04c5f` 的隔离 C5 工程检查。watchdog 在冻结截止 `2026-09-15T08:56:20.622818+08:00` 后终止已观察的进程树；`deadline_cleanup_recorded` 记录没有残留已观察进程，也没有已观察 Docker 名称。

最终 checkpoint 只有 46 个 history_build 成功、57 个 target 成功与 61 个 target 未执行（共 164 行）。正常的 JUnit 和 closed 回执没有形成；本归档不会伪造它们。该记录是 deadline-interrupted、未完成的工程证据，不是完整 C5 通过、模型效果、科学有效性、calibration 或 VAL 结论。

公开暂存仅包含 watchdog/冻结源/元数据。`runtime-private-inventory.json` 与 `closure.json` 绑定私有原件副本；完整 runtime bytes（含测试私钥夹具）仅保留在 `retained-private-evidence`，且链接/junction 不会被跟随。
