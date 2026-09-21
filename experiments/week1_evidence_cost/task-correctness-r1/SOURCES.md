# 来源与核验层级

本地材料均来自 `E:/_ryanDev/AI/research-loop-week1` 的 `052b874bd39c83ff2c539fb67cc151ced255076e`。读取的具体文件、输入内容 SHA256、脚本 SHA256、运行版本与逐项比较见 recomputation-r1.json。

## 冻结公开输入

`../qualification/r4/public-index.json` 给出预先分配的 TRAIN 身份、问题、字段说明及三个 CSV/public.json 的绝对路径和 SHA256。数据源任务标识中的 `real:test` 是上游名称，本项目冻结身份为 `domain=train`；本轮没有重新划分或读取正式 VAL 标签。

- SES：CSV `a90d12869a4c8b7058e68f0671dabe5b07ad952566295b4a69fe71d0b4f073a3`。
- World Bank：CSV `6d0b74fa37e75b2686c62075a11ab754fdf878ac400dfcbd4bf9a6a64bfaf4f1`。
- Incarceration：CSV `4071aede2c154022af2a6e08c2ba82fef7b911b7b1ede912bea2131e6a353fe3`。

public metadata 是本次供给的字段契约；不是原始队列 codebook 或完整数据清理血缘。没有据此声称源论文结果被复现。

## 既有代码、输出与解释

- `../domain-rich-r2/week1-rich-domain-1-r2/runtime/analysis-{1,2,3}.py` 与 `final/{request,response}.json`：最丰富 SES；最终 request 的 execution_feedback 保留三个程序的标准输出。
- `../domain-pilot-r3/week1-domain-1-r3/runtime/analysis-{1,2}.py` 与 `final/{request,response}.json`：短 SES。
- `../domain-pilot-r2/week1-domain-2-r2/runtime/analysis-{1,2}.py` 与 `final/{request,response}.json`：World Bank。
- `../domain-pilot-r2/week1-domain-3-r2/runtime/analysis-{1,2}.py` 与 `final/{request,response}.json`：Incarceration。

仅阅读/哈希这些程序；独立 verifier 不导入或执行它们，不调用原有计算函数。三个 profile 属于观察输入状态，数值复算不依赖 profile 里的计数作为自己的计算输入。rich 的事实 key、人数和成功数从冻结输出取 expected，actual 则从 CSV 独立计算。

## 外部公开定义

2026-09-21 只读核查两个世界银行官方页面；没有下载新数据替换冻结 CSV，没有查 benchmark reference answers。

1. [GNI per capita (constant 2015 US$)](https://data.worldbank.org/indicator/NY.GNP.PCAP.KD)：确认指标代码与名称。
2. [Adjusted savings, education expenditure (% of GNI)](https://databank.worldbank.org/metadataglossary/world-development-indicators/series/NY.ADJ.AEDU.GN.ZS)：确认经常性教育支出及 GNI 分母，资本投资不包含在该支出口径内。

这些页面仅支持指标解释，不验证本 CSV 的下载年份、地域加工或数值版本。NLS 的上游 BA 构造、SES 加工、财富复合方法和缺失码还没有完整材料可供核验；报告据此保留边界，而非自行推断已验证。
