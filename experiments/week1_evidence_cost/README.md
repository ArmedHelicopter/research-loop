> 最新整轮决定见 [MENTOR-DECISION.md](MENTOR-DECISION.md)、[逐项验收](REQUIREMENTS.md) 和 [最终数据](FINAL-SYNTHESIS.json)。下文为保留的历史阶段报告。

# 首轮成本定位：当前证据上下文接口

日期：2026-09-21。执行单：C:/Users/Administrator/Downloads/week1_research_brief.md。
本包只完成 D1–D2 的有限成本定位；一周目标未宣布完成。旧 grok 补跑调度已暂停。

## 决定

当前证据不足以进入新候选开发。缓存存在“先完整构造再查命中”的结构，但现有选中轨迹均未启用 M2/M3，运行时账本为空，无法代表有依赖更新的证据工作负载。这是覆盖缺口，不是“证据处理无瓶颈”的结论。后续只能先补足同领域真实状态/调用覆盖，再决定是否进入 S/C；本轮未实现任何优化。

## 样本与范围

采用三个明确命名的既有运行目录作有界清查，不宣称穷尽仓库。
共发现 21 条轨迹：11 条不在所选领域，10 条 DiscoveryBench TRAIN；其中 1 条未完成，9 条有 final_decision 且无 model_failure。
每个系列按路径选前三条完整领域轨迹，共 6 条；余下 3 条完整轨迹保留在清单分母。
选择没有读取评分结果。final_decision 仅用于判断协议是否收尾，不表示科学任务成功。

6 条均是同一道题的不同条件，独立任务数和来源组数均为 1：
- task_id: synth:test:futuristic-technology_0_0
- group_id: 559992c9a1d1795fb4c563efd3ef76b48642919049d829706240a06118041d5e
- dataset_version: 3a9864afcd052cd315aa40c1c8c15e17a3326bd7a80889ec845f4ee451189388
- split_id: 311aab673d5f116b40fc3835dfb83b00d507b899325588a7db90c83c9ed9941e
- 来源为 DiscoveryBench synthetic 数据；原名含 synth:test，但本项目归属 TRAIN，未读取正式 VAL 参考答案。
- 内容是城市技术培训、专利申请与政府投入的表格分析；只作为社会经济技术采用的有限代理，不代表真实社会科学任务覆盖。
- 完整轨迹 ID、模块条件、文件字节数与 SHA256 见 r1/manifest.json；原始副本见 r1/inputs/。

## 已核实的实际调用链

所有源码相对 E:/_ryanDev/AI/research-loop-week1/：
- research_loop/modular/runtime.py：RunSession 持有 EvidenceLedger、ClaimLedger、ContextCache；invoke 在 M2 开启时刷新依赖，调用 ContextCache，再把 public_data 包成 FrozenRecord，装入完整模型请求。
- research_loop/modular/modules/evidence.py：_JsonlLog.events 读取、解码并检查规范序列化；两个账本构造器回放事件；refresh_after_withdrawal 扫描支持/反驳并传播依赖。
- research_loop/modular/modules/context.py：ContextBuilder.build 读取 evidence.version 与 claims.snapshot().content_hash；后者再次读取 evidence.version。ContextCache.get_or_build 先 build、再计算完整 bundle 的哈希、最后查字典。
- research_loop/modular/contracts.py：FrozenRecord 规范化、反序列化与已有大记录摘要缓存保留原样。
- research_loop/ontology.py：canonical 与 digest。
- research_loop/modular/admission_prediction_exploration_driver.py：运行阶段向 session 传递 _transition；验证阶段重放临时账本并逐项比较请求。模块状态和运行时 context 是不同输入部分。

读过的范围文档：docs/MODULAR-EVIDENCE.md、docs/MODULAR-BENCHMARKS.md、仓库 AGENTS.md。
历史公共材料映射读取自 E:/_ryanDev/AI/research-loop-modular/work/actual-m4m5-train-material-map-r1.json。
公开 public.json 和 data.csv 的真实路径及哈希在 manifest.public_data。
本轮没有重建模块上下文、重放 Docker 工具、重跑模型或评分器，也没有验证整条科学任务的正确性。

## 方法与结果

Python 3.12.6，Windows 11，单个工作进程；30 个重复批次，每批每项执行 20 次，方案顺序由固定种子随机化。
共 1,620 条批次计时。每条轨迹只对首个请求计时；该轨迹所有保存请求均另做内容一致性检查。
下面范围是六条轨迹各自的批次中位数范围，不是置信区间，也不表示六个独立任务。

| 操作 | 中位耗时范围（微秒/次） |
|---|---:|
| 空账本读取与校验入口（含 _JsonlLog 构造） | 125.84–130.65 |
| 空账本加载/回放入口（包含上述读取） | 128.22–133.37 |
| 无状态变化的依赖刷新 | 0.285–0.310 |
| R：直接完整构造，仅作诊断 | 41.75–42.55 |
| B：现有缓存，新建缓存对象 | 54.31–55.94 |
| B：现有缓存，命中 | 53.50–56.31 |
| bundle 摘要（含序列化） | 11.63–12.05 |
| bundle 序列化 | 10.13–10.36 |
| 原样完整请求 FrozenRecord 构造 | 67.46–93.48 |

B 保留现有缓存。R 不是新基线或改进方案，不能用 B/R 差异声称新方法加速。
分项有嵌套关系，不能相加或直接相减解释独占成本。cProfile 独占/累计时间另存，未与未插桩计时混合。
六次诊断各执行 100 次 B 命中，均调用 100 次 build；每次 profile 中 evidence.version 被调用 200 次。
账本为空，因此“读取校验”和“回放”不包含非空事件解析成本，“刷新”只是额外诊断的空操作，原轨迹 M2 关闭时不调用它。

15/15 个历史请求的 context 规范字节相同；把重建 context 放回其余字段冻结的历史请求后，15/15 完整请求规范字节相同。
未删除字段、规范化时间戳或改变提示长度。其他请求字段来自原记录，故不称为整条流程重新执行的一致性。
源文件、输入账本在运行前后哈希不变。命中返回同一个缓存对象。
一次新建缓存对象调用的 Python 新分配峰值为 11,423–11,567 字节；不包含进程 RSS、既有对象或全系统峰值。
文件系统缓存未清空，故所谓“冷”仅指新建缓存对象；CPU 未绑核，宿主并发负载未控制。本结果是成本定位，不是正式性能排名。

历史工具记录 wall_seconds 为 0.625–1.110 秒；与本次本地计时分开保存，未用于推算端到端加速。
历史模型等待、token 成本、依赖非空更新、证据完整展开、索引建立维护及失效、S/C、总系统收益均未测量。
未启动新订阅客户端、外部模型请求或子代理，新增付费为 0。Codex 本次交互自身的额度消耗未能核实，不等于 0。
官方可用额度、重置和月度到期均 unknown；尚未完成 D1 额度登记，也不据窗口重置扩大发送规模。

## 可重放与原始记录

工作树：E:/_ryanDev/AI/research-loop-week1；分支：codex/week1-evidence-cost。
基点：be693ae30cfd6ef5f7619234c73082fa241cdb7f。
本包全部新增文件位于 experiments/week1_evidence_cost/，核心代码未改。

实际运行命令（从工作树根目录）：

    python -B experiments/week1_evidence_cost/measure.py freeze --run r1
    python -B experiments/week1_evidence_cost/measure.py run --run r1

首条命令在任何计时前冻结清单和代码哈希；第二条启动限时 60 秒的单工作进程。
实际工作进程 argv、退出码、标准输出和错误见 r1/execution_receipt.json。
原始批次计时：r1/measurement/raw_timings.jsonl。
逐轨迹汇总：r1/measurement/summary.json。
一致性、内存和历史工具时间：r1/measurement/checks.json。
插桩诊断：r1/measurement/profile.json。
环境与 manifest 哈希：r1/measurement/environment.json。
清单 SHA256：0c2db19bb5112d883af3c60d84bdd4f00a40f79abdba709f503656445d0777e2。

已有 r1 不得覆盖。另行测量用新的 --run 名称并保持选择规则；不自动派发后续实验。
脚本遇非空账本会停止，因为当前实现没有事件对齐的历史状态回放；不能拿最终状态替代历史请求状态。

执行中曾尝试不存在的 modular/ontology.py、modular/trace.py、exploration_scheduler_driver.py，并纠正到上述实际源码；未据失败路径得出结论。
首次 apply_patch 因隔离工作树不在默认可写范围而未写入；随后经自动审批以 PowerShell 写入限定目录。
这些定位/写入失败未产生模型实验机会或被记作算法负结果。
