# 当前 headless 场景接入缺口（r1）

审计时间：2026-09-15；源码基线：`artifact-evidence-provenance` 的
`ab244b8a461e7d47a9c1705d255c7f9c7771976f`。本报告只读代码和测试
源；没有读取 benchmark payload、VAL、凭据或运行产物，也没有启动测试、
模型、API 或 Docker。

## 已有可复用的运行接入

| 共享入口 | 当前事实 | 对下一次真实运行的含义 |
| --- | --- | --- |
| `research_loop/modular/train_provider_preflight.py:34-91`，`native_provider_preflight` | `NATIVE_SCHEMAS` 已为 11 个 native family 登记；`validate_native_declaration` 明确接受 `grok-acp-public-train-v1` 和 `grok-headless-public-train-v1`，随后要求相应的精确运行时 wrapper。 | 这不是“只能 ACP/Codex”的共同阻断点。新配置必须用已登记 family 的 native schema，不能给旧 schema 仅改 provider_kind。 |
| `research_loop/modular/phase_provider.py:20, 111-125`，`PhaseProviderSession` | 共享 phase ledger 的封闭 provider 集合已含 `GrokHeadlessTrainProvider`；每次 session 验证配置和原始调用。 | native family 若经 preflight，已有同一份 allocation、scope、原件绑定路径。 |
| `research_loop/modular/ordinary_provider.py:9-17, 42-89` | 普通 family 的共享 preflight 走 `native_provider_preflight`，并在 cell 后执行 `bind_runtime_originals` 与最终 provider gate。 | 解决 provider 原件/已知 MAIN 账本，不等价于 evaluator 的最终闭合。 |

已有专项覆盖也支持上述结论：`tests/test_headless_train_provider.py:19-44`
覆盖 headless wrapper + phase seal；`tests/test_headless_train_controllers.py:38-55`
覆盖一个 singleton 的 headless native controller；`tests/test_headless_m4_m5_controller.py:44-80`
覆盖 M4/M5 的 headless 配置拒绝和最终闭合。它们不能替代下一场景的集成验证。

## 48 个模型主机会的现有实际场景

`research_loop/modular/admission_prediction_exploration_controller.py` 是一个具体、
共享架构上的下一场景候选：它冻结 16 个 panel cell，每 cell 三个 model slot，
因而 native declaration 要求 48 个 MAIN opportunities（`:126-145`）；receipt 也以
`48 - actual_docker_attempts` 作为 Docker 分母（`:368-374`）。它执行真实的 source、
phase、Docker、score 调用序列（`:280-338`），并有最终 provider provenance gate
（`:339-369`）。这只是工程运行定义，不是任何实验效果的证据。

该 family 的 native protocol 已登记为
`admission-prediction-exploration-combination-train-config-v3`
（`train_provider_preflight.py:14-27`），配置对象通过
`native_source_fields(..., family='admission_prediction_exploration')` 和
`validate_native_declaration` 接受该协议（`admission_prediction_exploration_controller.py:63-145`）。
所以它**不**是只接受旧 Codex/Grok ACP 的入口：v3 可以接受严格声明的
`GrokHeadlessTrainProvider`。

## 实际缺口：headless evaluator 没有终结核验

这个 48-MAIN 场景没有 opt-in 的 evaluator declaration/provider 字段，也没有
headless evaluator finalization。

* `run_admission_prediction_exploration_train_panels` 只要求已有的
  `CombinationScorerProcessClient` 并做普通 scorer preflight
  （`:220-240`）；每 cell 只调用 `score_combination` 和单收据验签
  （`:306-316`）。
* 结束时只写 native provider gate、历史 score digest、`scorer_usage_unknown` 和
  `admission-prediction-exploration-train-receipt-v2`（`:339-374`）。其中没有
  `evaluator_final_verification`、已签 closure、完整 panel scope 或 evaluator known
  MAIN 下界。
* 这与已实现的 M4/M5 opt-in 路径形成精确对照：仅
  `m4-m5-train-controller-config-v6` 调用
  `finalize_headless_evaluator`，以 authority keys、panel、`ScorerConfig`、provider、
  nonce 和**有序** score-receipt digest 独立验证 closure，并把失败降为
  inconclusive（`combination_train_controller.py:511-545`）。C5 另有独立消费端
  verifier：`research_loop/modular/joint_train_evaluator_verification.py:1-55`。

现有 `tests/test_admission_prediction_exploration_controller.py` 是广泛的 synthetic
controller/scorer/篡改覆盖，但配置 fixture 仍是 v2（`:110-151`）；该测试文件没有
headless native v3 + signed final closure 的集成 case。故不能据其声称本场景已有
headless evaluator 终结证据。

## 至多一个最小实施建议

保留 v1/v2/v3 的既有语义，新增此 family 的**显式 opt-in schema revision**，在
`ordinary_provider.py` 放入一个内部、可由多个 ordinary controller 调用的
“finalize + verify + full-panel-set/unique-count eligibility + retained inconclusive
envelope/known-MAIN-lower-bound” helper。新 revision 冻结
`evaluator_usage` 与 `evaluator_provider`（其中 configuration digest 必须相等）；
controller 在所有 cell 后按其唯一 panel 的实际 receipt 顺序调用该 helper，并在
receipt/journal 写 `evaluator_final_verification`。旧 v1/v2/v3 不添加默认字段也不
走此路径，从而不能把未声明 headless pool 当作有效 evaluator。

最小必要回归是一个 synthetic native 16-cell panel：完整签名 closure 可消费；缺一
receipt、部分 scope、provider/config/authority/digest 篡改、finalization/usage 失败都
保留已签原始证据并使 receipt inconclusive。该回归仍只是工程接线验证，不能量度
真实效果。

## 边界

本次没有宣称所有 48Q/48-call family 都已逐一验证，也没有把 M4/M5 或 C5 的测试
外推为 admission-prediction-exploration 的运行证明。结论仅是当前共享 provider/phase
seam 已接受严格 headless provider，而该具体 48-MAIN controller 缺少声明式
headless evaluator 终结核验，适合作为下一次接入的单一优先缺口。

