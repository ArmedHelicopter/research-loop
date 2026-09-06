# Ontology 与受控经验自改进运行时

2026-09-03。新增工程实现，不修改原有科研对照的成功标准。固定模型通过外部经验记忆改变后续行为；模型只返回 JSON，控制器负责版本和研究记录的状态变化。

## 闭环与对象

~~~mermaid
flowchart LR
  Q[外部开发任务 FIFO] --> R[固定规则和版本]
  R --> A[执行与两次独立上下文审计]
  A --> M[反思提出有来源的经验]
  M --> C[候选版本]
  C --> T[先冻结外部任务、标签承诺和标准]
  T --> E[基线与候选配对运行]
  E --> S[独立进程评分]
  S --> P[独立 reviewer 晋升]
  P --> Q
  P --> B[回滚到父版本]
~~~

cycle 自动运行一个开发任务并提出候选，提案不会改变 active version。模型没有生成并准入本轮评价题、写评分回执、修改代码或直接晋升的工具。

| 对象／关系 | 可执行约束 |
| --- | --- |
| Task → Evidence | ID 唯一；类型为 observation/measurement/artifact；scope 一致；公开内容不含隐藏标签字段。 |
| Task → Rule | scope、规则文本和审计项共同哈希；运行另固定整个 task_hash；模型返回的规则哈希必须一致。 |
| Decision → Evidence | 引用非空且已存在的 evidence IDs；状态限于 proceed/closed_negative/withdrawn/invalid。 |
| Audit → Decision | 每项必须覆盖且唯一，pass 必须为布尔；两次逐项一致且合取为真才通过。 |
| Lesson → Run → Evidence | 仅来自已关闭开发运行，记录来源哈希、scope、rule_hash 和证据引用。 |
| Version → Lesson | 候选继承父版本、增加一条经验；执行只取同 scope/规则的最近三条；版本按内容寻址。 |
| Trial → Versions / Tasks / Criteria | 同时固定两版本、任务、准入标准、实现哈希及私有标签文件 SHA256。 |
| Evaluation → Promotion | 评分进程生成封存回执；reviewer 的身份标识与 proposer/evaluator 不同。 |

这是轻量可执行领域模型，不需要 RDF/OWL 或图数据库。它校验结构、引用和状态转换，不自动证明观察真实、科学结论成立或 task family 语义独立。

外部规则在发送给模型前固定；程序无法证明外部作者写规则时没有看过数据。prerequisites 由可信外部流程提供，任一 false 会在模型调用前 withdrawn。audit_valid 与科学 status 分开：审计通过不会把有效阴性变成 proceed。两次调用同一基础模型也不保证错误统计独立。

## 运行与接线

Python 3.11+，运行时只使用标准库。先在仓库根目录验证完整离线演示：

~~~powershell
python -m research_loop demo "$env:TEMP\research-loop-demo-20260903"
python -m research_loop --help
~~~

目标目录必须新建。demo 导出无标签 public/，把合成标签存到相邻 evaluator/，通过多个子进程完成初始化、cycle、冻结、配对运行、评分、晋升、新任务使用经验、回滚及重读状态。demo-result.json 明确标为 engineering_fixture；后端刻意在有／无经验时给出不同输出，只验证线路接通，不是模型效果或泛化实验。

真实调用先导出运行包：

~~~powershell
python -m research_loop export "$env:TEMP\research-loop-public-20260903"
Set-Location "$env:TEMP\research-loop-public-20260903"
python -m research_loop init
$env:RESEARCH_LOOP_BASE_URL = 'https://YOUR_ENDPOINT/v1'
$env:RESEARCH_LOOP_MODEL = 'YOUR_MODEL'
$env:RESEARCH_LOOP_API_KEY = 'YOUR_API_KEY'
python -m research_loop enqueue .\development-task.json
python -m research_loop cycle --proposer researcher-a
python -m research_loop status
~~~

端点需兼容 chat-completions。每次为独立 system/user 消息，无文件、shell 或代码执行工具；温度 0，最多 800 output tokens。只使用显式配置，不自动读取其他工具登录凭据。缺失 usage 会记录不完整计费，不能以零代替。run --limit N 可有限地执行 FIFO 任务，默认 1。

公开任务示例（仅说明格式）：

~~~json
{
  "id": "D001",
  "family": "development-family",
  "scope": "assay",
  "question": "这一有效阴性观察如何更新本阶段假说？",
  "rule": "有效阴性关闭本阶段假说；不得解释成研究计划完成。",
  "prerequisites": {"valid_comparison": true, "artifacts_available": true},
  "evidence": [
    {"id": "obs", "kind": "observation", "scope": "assay", "content": "预注册比较得到有效阴性。"}
  ],
  "checks": ["rule_preserved", "evidence_referenced", "no_program_completion"]
}
~~~

公开内容禁止 gold_*、violation_if、temptation_markers 和 data/labels。原 W/LCK 题格式保持原样；转成新确认性题前仍须独立审查。程序不自行读取 policy-signature 的私有结果或执行生成代码。

## 冻结、评分、晋升

外部提供公开任务数组与私有 task ID → expected status 对照；标签必须在 public/ 之外。

~~~powershell
python -m research_loop freeze-trial --candidate CANDIDATE_HASH --tasks .\evaluation-tasks.json --labels 'E:\private-evaluator\expected.json' --evaluator evaluator-b
python -m research_loop run-trial TRIAL_HASH
python -m research_loop evaluate TRIAL_HASH --labels 'E:\private-evaluator\expected.json'
python -m research_loop promote TRIAL_HASH --reviewer reviewer-c
~~~

freeze-trial 由评分子进程读标签，只返回运行前 SHA256；evaluate 再开独立评分进程。模型执行／反思路径不读取标签，不接收评分回执或逐题正确性信号。

默认工程晋升标准（可用 --criteria 在冻结前指定）：

~~~json
{
  "min_pairs": 20,
  "min_families": 2,
  "min_error_reduction": 1,
  "max_token_ratio": 1.25,
  "max_call_ratio": 1.0
}
~~~

必须同时满足：任务数和 family 数足够；错误至少减少指定数量；协议拒绝事件和过拒不增加；tokens 与调用数不超相对预算。这些是工程筛选默认值，没有统计功效保证，不能替代原 SPEC 的置信区间门槛。真实科研验证需另行预注册。

配对两臂使用相同模型、端点和生成参数，按题交替执行次序。版本和记忆固定；开发或过去 trial 用过的 family 不能重新进入最终评价。重命名不能绕过完全相同内容检查；近重复和语义泄漏仍需外部审查。未过门的候选保留，不部署。提案成本单独记账，不混成部署后节省。

## 持久化与边界

SQLite 事务保存不可变对象、FIFO、当前版本和哈希链。版本、trial、运行封存、评分回执会检查哈希；旧试验不能覆盖已改变的 active version。

运行包源码也参与实现哈希。升级源码后不要继续使用旧包的版本数据库；保留旧运行包以复核旧结果，为新实现建立新数据库。本版没有隐式迁移或忽略实现变化的开关。

~~~powershell
python -m research_loop --approver reviewer-c rollback --reviewer reviewer-c --reason '出现过拒'
python -m research_loop recover INTERRUPTED_DEVELOPMENT_RUN_ID
~~~

回滚是显式 fail-closed 的白名单授权：只有 `--approver`（可重复）列出的 reviewer 才能执行 rollback；默认空白名单 = 回滚禁用，名字格式合法但未授权的 reviewer 一律拒绝。version_rolled_back 事件仍记录 reviewer/reason 供审计。

recover 只关闭已确认中断的开发项，不自动重试可能已经收费的请求，调用前须确认原进程已停止。已完成 trial 重读不重复调用；请求中间中断则缺少封存记录，需调查并结束该 trial，不能删记录挑最好一次。

模型调用按角色装配 provider：executor、auditor_1、auditor_2 三个角色的 provider identity 必须两两不同，否则 run 直接拒绝（fail closed）。同一部署的 auditor 会与 executor 共享权重与幻觉模式，`audits[0] == audits[1]` 不能证明事实正确。identity 即隔离边界：HTTP 后端经 `RESEARCH_LOOP_*`（executor）、`RESEARCH_LOOP_AUDITOR_*`（auditor_1）、`RESEARCH_LOOP_AUDITOR2_*`（auditor_2）环境变量装配；同 base_url 下不同 model 名是最低要求，推荐不同 base_url 的独立部署。reflector 沿用 executor provider（它是反思路色，不是审计者），propose 会校验封存 run 的 executor identity；每个 run 记录按角色封存 `providers` 身份映射。

角色名字是可信操作者层面的权限约束，不是账户认证。哈希链能检测意外改写，不能防止拥有写权限的人重写整个数据库。面向不受信操作者部署时，还需要账户与进程隔离保护控制器、标签和数据库。HTTP 模型接口本身没有这些权限。

## workflows 工作审视与交接

- 多源反馈：用户要求落地；代码和 64 个基线测试提供现状；此前文献调研要求区分工程接通、独立验证和成本收益。
- 传递给矛盾分析：缺口是可运行的经验更新与版本转换。
- 主要矛盾：自适应改变行为 vs 固定评价规则，属非对抗性技术矛盾。解决它能同时约束任务泄漏、版本漂移和自批准。
- 应对方法与传递：通过来源／scope／规则哈希约束经验，再进行外部冻结对照，最后独立评分、reviewer 晋升。
- 需监控：经验复用与上下文成本是否上升为主要矛盾。
- 实践验收：CLI 闭环运行、违规转换拒绝、HTTP 请求和计费接线验证、旧测试继续通过。

| 审视项 | 事实与处理 |
| --- | --- |
| 原定目标 | 可持久化、可验证、可回滚的经验自改进 agent，以及可执行 ontology 约束。 |
| 已完成 | 运行包、FIFO、角色 JSON 契约、经验候选、冻结试验、独立评分、晋升回滚、CLI 和测试。 |
| 尚未证明 | 真实科研效果、内部思维链缩短、总成本下降。不能用工程验收替代这些证据。 |
| 方法改进 | 设计接口时就检查谁能在何时改变评价依据，不能把审计留到输出最后一步。 |
| 有效做法 | 通过真实 CLI、子进程及 HTTP 验证接线，并明确标注合成后端。 |
| 下次重点 | 独立任务族、统计门槛、预算、相关模型错误、语义泄漏和经验过度推广。 |

| 严重程度 | 具体问题 | 方法上的根因 | 已落实的改正 |
| --- | --- | --- | --- |
| 必须改正，已处理 | agent.py 的初始 freeze_trial 设计只冻结公开任务，不能阻止事后更换答案。 | 只审视 agent 能看到的输入，没有审视外部评价依据的完整生命周期。 | 运行前标签 SHA256 承诺、evaluate.py 核验、改标签拒绝测试。 |
| 必须改正，已处理 | 最初仅校验 version/trial，未核验已封存 run/receipt 的意外改写。 | 把输入固定误当成整个证据链已固定，输出验证不足。 | store.py 增加事件封存校验，评分和晋升均调用；增加改写拒绝测试。 |

2026-09-03 验收：目标仓库全量 97 个测试通过（原有 64、新增 33），包括独立子进程评分、导出目录中的本地 HTTP 请求与记账。CLI 合成闭环产生 6 条运行记录，完成候选评估、晋升、新任务使用经验、回滚和重读状态。测试与演示不包含真实模型科研效果对照；本轮工程验收没有未处理失败。

5 小时后的唤醒先读本文件与 git diff，从未完成的验证继续；若当前请求已完成，只核对交付状态，不自动扩大研究范围。
