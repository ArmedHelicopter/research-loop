# 首轮只读审查

审查日期：2026-09-21。审查者：本任务的 week1_readonly_review 子代理（Terra / medium）。一个有界只读包；没有修改文件或执行实验。它是代码审查，不是独立实验样本。

结论：未发现会推翻首轮谨慎结论的确定性代码错误。首轮只能定位空账本路径。

- 15/15 比较证明保存的空账本、baseline 模式与原 summary 可重建相同 context。其他请求字段原样冻结；不证明完整运行时或科学任务复现。依据 measure.py:100-121、r1/measurement/checks.json、research_loop/modular/runtime.py:343-387。
- 六条轨迹是同一道 TRAIN synthetic 题，M2/M3 均关闭，账本皆空。M3 非空枚举和 M2 在真实运行中的刷新没有被测到。依据 r1/manifest.json、research_loop/modular/modules/context.py:73-92、runtime.py:352-365。
- ledger_read_validate 的名称需要精确解释：它只覆盖 _JsonlLog.events 的读取、JSON/规范序列化检查；事件 identity、root、claim 等语义检查在 ledger_load_replay 的构造器回放中。空日志不影响现有结论。后续报告将称前者为“读取及规范格式检查”。依据 measure.py:131-136、evidence.py:117-142,275-276。
- B-cache-hit 仍先 build 再 hash，再查字典。它测对象复用路径，不能证明避免了上下文重建。依据 context.py:114-134。现有 README 的解释正确。
- 下一轮应补实际社会科学表格任务的非空证据操作；请求前按事件顺序恢复状态，不使用最终 sidecar 冒充历史状态。至少需要准入、claim 支持/反驳、依赖、撤回刷新、版本变化与上下文调用的可审计记录。AND、替代支持、无关更新、清空缓存、循环等独立正确性边界依简报 D3 检查，不应为了“覆盖”往领域轨迹里伪造业务操作。
- 尽量用三个不同实际任务；这是增加覆盖的建议，不将重复数称为独立研究任务数。已登记的来源组只证明划分规则，仍不能自动证明科学独立性。

主执行者处理：保持首轮结论和原始记录；第二包先验证真实任务可用性，再冻结原始运行机会。未实现 S/C，未改评分器。
