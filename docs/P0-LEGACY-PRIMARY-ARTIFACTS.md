# 旧主 benchmark TRAIN 数据包的产物契约

`TrainPacketExporter` 的 DiscoveryBench/BLADE 公共输出现由独立 P0 适配器登记。
实际消费者 `run_train_panel`、`CombinationTrainSource.export` 和
`run_q32_execution_panel` 均在导出后调用 `verify_primary_train_packets`，
使用各自持有的 custody、snapshot、冻结 item_ids 和输出根重新派生预期来源。
返回前的生产检查与消费前检查都已接入。Prospective v2 保留自己的已有契约。

## 独立来源与原件

先校验整个 TRAIN 选择、清单摘要、划分摘要及精确任务绑定，再读取所选公开
源文件。`PrimaryTrainSource` 保存控制器持有的原始 metadata/CSV 缓冲区，
绑定 inventory row、完整任务与分配、明确的 metadata/query selector，重新
计算公开投影及 receipt。该对象不进入模型上下文，消费者不能从待验证包的
receipt 或自述 hash 构造预期答案。

每次尝试在首写前生成独立 UUID，绑定 reservation、目录 run ID、封存及失败
记录。相同任务在不同目录重新运行产生不同尝试编号；已有输出目录不能复用。
实际写入 `data.csv`、`public.json` 时使用独占创建和 fsync，逐项记录摘要、
字节数及生产代码。来源快照包含导出器、适配器及两个 benchmark 的投影代码。
目录有精确文件白名单；路径、祖先、符号链接及 Windows reparse/junction
在读取或创建前检查。

成功读取须同时满足完整原件清单、reservation、精确描述符及父项、配置与源码
绑定、终态、catalogue seal 和 packet seal。随后将实际 CSV、完整 public
task/receipt 与独立源缓冲区逐字节比较。对现有文件及所有封存重算 hash 仍不能
绕过这个来源检查。未启用模块与未知成本的原有语义不被升级。

## 失败边界

第一次写入、CSV/public 部分写入、终态、catalogue seal 或 packet seal 失败
均保留实际字节。独立 `failure.json` 和 `failure.seal.json` 绑定现存文件，
不重试已经部分完成的主目录封存；公共异常信息只有阶段、类型和 `error:null`，
原异常对象保留给直接调用方。失败存储再次失败时仅附加异常类型说明，不覆盖
原异常。缺少完整失败封存的目录保持不完整，任何成功读取都会拒绝。

`inspect_failure` 只授予存储完整性，始终保留 `operation_validated=false`
和 `acceptance_eligible=false`。可读目录中的 run ID 必须对应失败尝试；在
第一次 reservation 已损坏、尚无可读目录时，只能核验 UUID 格式及当前存储，
不能对不存在的独立历史锚点宣称认证。源码与文件完整性不代表科学有效性或
操作系统级权限隔离。

## 冻结验证与归档

`eb33da6797c16ddda521809541af3ca32ac9ba18` 通过 59/59 项集成检查，
40.860 秒，729 份源码及文档字节前后一致，未跳过。包括 46 项新增产物检查、
2 项原 TRAIN 导出检查、10 项标签隔离和 1 项完整普通控制器工程路径。
三个实际消费入口分别覆盖正常与篡改拒绝；实际文件、符号链接、junction 与
合成进程传输均被执行，未调用模型服务、Docker 或真实 VAL。

`results/modular-engineering-20260915/legacy-primary-artifacts-r1/` 的 20 个文件
保留冻结源码和检查、子代理历次失败与修复记录、9 份原始公共目录 ZIP：
2 份成功、6 类仅存储完整的失败、1 份不完整前缀。归档使用测试在导出前写入的
独立 custody 原件和现存 source，另外核对冻结 fixture 常量，不重新运行导出器。
完整 custody 和源文件没有复制到公共产物目录。对失败包的篡改测试使用副本，
原始失败字节仍可复查。

既有完整私有划分/权限台账、跨目录生命周期、资源分摊和真实效果实验仍有各自
未完成事项，见 [覆盖清单](MODULE-ARTIFACT-COVERAGE.md)。所有优化只访问 TRAIN；
这些工程记录不授予 VAL 访问、验证结果反向优化或生产部署权限。
