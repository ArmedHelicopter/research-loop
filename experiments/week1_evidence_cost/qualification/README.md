# 第二个任务包：真实领域输入资格核查

2026-09-21。结果：三个真实社会科学表格任务已经通过实验目录内的适配器成功导出，原生 TRAIN 包验证器与审计链检查通过。没有生成新模型轨迹；没有开始 S/C，也没有完成 D2 的真实非空账本成本测量。

## 已有运行覆盖

对 work/ 中全部直接 actual-*-run-* 目录做有界元数据清查：14 个目录、53 条 trace 首行、其中 30 条 DiscoveryBench TRAIN，非空运行时 evidence/claims 账本数量为 0。详见 existing-trace-coverage.json。读取范围是身份首行与文件大小，没有用评分选样。另行找到的非空账本来自合成测试夹具，不能作为领域实验样本。

## 三个真实任务

| 任务 ID | 公开研究问题 | CSV 字节 |
|---|---|---:|
| real:test:nls_ses | 学士学位完成与社会经济地位的关联 | 679598 |
| real:test:worldbank_education_gdp | 不同地区教育支出与人均 GDP 的关系 | 6773 |
| real:test:nls_incarceration | 曾被监禁人群中，不同年份的性别财富差异 | 343144 |

三题均已在既有冻结分区中归入 TRAIN，未重新划分。名称中的 real:test 是上游命名，不是本项目 VAL。
清单的三个 group token 不证明三个科学独立来源；两题均来自 NLS，另一题来自世界银行，共两类宽泛来源。
相应 dataset_version、split_id、group_id、metadata 哈希、公开文件路径与 CSV 哈希见 r4/public-index.json 及 r4/request.json。
上游 commit 仍 unknown，当前版本绑定的是既有本地快照及逐文件字节哈希。没有将快照存在等同于科学有效性或数据许可已获独立审查。

## 尝试分母

- r1：70 项 original_train DiscoveryBench 输入整体导出失败，尚未发布任何任务。逐项诊断 64 项能投影，6 项抛出 UnicodeDecodeError。没有猜测编码或改原始字节。
- r2：预先选择 NLS SES、世界银行教育/GDP、移民/离岸外包就业三题。三题都是实际嵌套 queries，原投影器只接受平铺 queries，整体失败、零发布。就业任务另外需要两份 .dta 文件，不符合本包限定的单 CSV 接口。
- r3：换为 NLS 监禁任务；增加实验内固定 /queries/0/0 选择。三题又因真实元数据的 columns.raw 结构与原平铺列接口不同而失败，零发布。
- r4：显式允许这两项已观察到的结构转换，三个任务全部导出成功；耗时 41.438 秒。没有放宽数据分区、文件完整性或公开字段检查。

前三次失败的精确 producer、request、result、原生 exports.jsonl 与诊断均保留在 r1–r3。r4 同样保留。
这些是导出/兼容性尝试，不算新模型实验，不冒充四次模型结果。

## 适配边界与实际验证

qualify_domain.py 中 RealSingleCsvExporter 继承现有 PrimaryProspectiveTrainExporter。只重写实验所需的公开字段投影，保留继承的分区重算、eligibility、输入哈希、路径/reparse 检查、源验证、暴露前登记、发布前验证与原子发布。
限定真实 DiscoveryBench、单 CSV、固定第一组第一题，以及仅有 raw 的列描述。源字节保持不变。
每个来源选择器记录 metadata_file、metadata_sha256、query_group_index=0、query_index=0、query_json_pointer=/queries/0/0 与 data_file；没有模糊扁平化整个问题列表。

原生 verify_train_export_artifacts 通过；逐字节 SHA256 与索引一致；全部 public payload 不含 hypotheses、true_hypothesis、intermediate、domain_knowledge、workflow 键。
三份 CSV 均为 UTF-8 可读，所有描述列都存在于原始表头。NLS SES 的 CSV 有 9 列、公开描述 8 列，额外列没有被静默删去。
导出审计链的 6 个事件已复算，末项 export_completed；模型调用、评分调用、VAL 导出均为 0。
r4/verification.json 是这些明确检查的证据，不是统计发现或完整领域工作流已完成的证据。

代码只增加在 experiments/week1_evidence_cost/，没有修改核心导出器或评分器。新增 CSV 仍位于 r4/public-index.json 记录的本地公共 TRAIN 目录；这里归档输入索引和来源哈希。

## 调用与预算校准

从 E:/_ryanDev/AI/research-loop-week1 执行：

    python -B experiments/week1_evidence_cost/qualify_domain.py

每次 producer 固定自己对应的全新 work/week1-domain-export-20260921-rN 目录；r1–r4 不覆盖。复算用对应 producer，并保留原输出；跨机器需要原冻结托管快照，不能只靠本目录重建输入。

第二包同时完成一次 Terra / medium 只读审查，记录见 ../review-r1.md。
官方 CLI 周用量在本包前后显示 4% → 7%；这是同一账户的合并增量，无法从中分离本包、审查和可能的共享使用，界面取整也限制精度。首包无可靠前值，所以不能宣布三包校准完成。
用户已确认沿用同一账户，以先前 97% 剩余额度的 60% 冻结本轮上限；保守在已用 61% 时停止新增派发。零新增付费，不充值，窗口重置不自动扩额。账号细节和官方查询原始回执保存在仓外工作记录。
本周到目前：实现包 2/8、只读审查包 1/6、新领域模型轨迹 0/6、Grok 审查 0/4。

## 下一包的验收目标

按这三题冻结最多三条官方客户端原始运行机会，串行记录包前后额度。首次只生成三条，失败与未知不重用机会。
必须在实际模型请求前由 M2/M3 的真实状态构造上下文，保存源数据、操作、证据 ID、claim revision、输入/输出与工具执行链。不能把 CLI 完成后的账本补记，误称为模型当时实际收到的上下文。
领域任务的支持/反驳/撤回必须由实际操作产生；D3 的人为边界情况另作正确性测试。
继续分别测 R 语义参照与 B 现有完整缓存路径的成本，核对逐请求内容；如果真实负载不支持瓶颈判断，就保留缺口或停止候选开发，不用空账本或合成夹具替代。
