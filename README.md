# research-loop

科研 agent 的分权协议：提案、锁定后执行、二元审计三者权力不相交；执行者不能在见到结果后改判定规则。

本仓库有两件并行的事，不要混成一句：

1. **协议文本。** 从 `policy-signature` 抽出，供三人共用和修改。源仓继续用它当控制，G1–G4 研究不停。
2. **第一项研究。** 这个协议作为干预，是否比单 agent 更少出现目标替换、事后改门槛和假完成，同时不降低对预注册终点的判别力。这项研究按顶会标准做：先调查、再锁 SPEC、标签与提示隔离、预注册证伪器、完整报告阴性结果。对照完成前，协议不是已证明的方法。

本仓不是 `policy-signature` 的替代，也不是 AGI 项目。源仓 programme 句仍由那边的测试 hash 锁定。

## 仓库里有什么

```text
protocol/research-loop.md   源协议（含源仓绑定，阅读时区分）
docs/DESIGN.md              被测干预是什么、不是什么
docs/SPEC.md                第一项研究的预注册对照
docs/survey.md              occupied / open
experiments/sep_of_powers/  评分器与提示渲染（看不到 labels/）
data/tasks/                 任务公开面
data/labels/                隐藏标签；跑臂的工作树不得挂载
tests/                      标签隔离与评分器测试
```

## 第一项研究（一句）

> 在科研决策任务上，把提案 / 锁定后执行 / 二元审计分给不同 agent，并禁止见结果后改规则，是否比单 agent 循环更少出现目标替换、事后改门槛和假完成，同时不降低对预注册终点的判别力？

细节见 [`docs/SPEC.md`](docs/SPEC.md)。和 Zheng et al. ACL 2026 的差别：他们预测哪份训练代码更好；我们测的是科研**决策**上的协议违规，不用预测分数替换 FIFO。

## 现在不承诺的

- 可发顶会、提高发现率、通向 AGI。
- 源仓 PSB 上的准确率（存在从产物读判定的循环）。
- 「LOCK 已在源码里由 hash 强制」——源仓实现与文档不一致；本仓对照按意图实现并单独标明。

## 本地检查

```text
python -m pytest tests -q
```

确认性跑臂在 SPEC 冻结、且 `data/labels` 不进入模型工作树之后才开始。
