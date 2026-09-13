# 训练适配评分与候选选择

`research_loop.modular.train_selection.measure_and_select_train` 把完整训练面板的真实机制日志、求解日志和独立签名适配评分组合成一个不可变测量记录。每次只接收一个 Q 的完整变体、arm、任务和 replicate；所有结果必须与冻结面板逐项一致。该入口拒绝 validation，既有 `ExperimentLedger` 的科学验收门槛保持不变。

规则 `FrozenTrainSelectionRule` 必须事先放入面板 `acceptance_criteria.train_adapted_selection`：基线 arm、全部可执行 arm 的平分次序、最低平均改善和每个 benchmark 可容忍的最大下降都绑定到执行过的面板。每个评分回执先验签，再与当前两份日志、实际程序执行及 linked receipt 绑定核对。不能传入任意浮点分数替代回执。

估计按相同任务、变体和 replicate 计算候选减基线，再在来源组内平均、等权汇总来源组，最后等权汇总各 benchmark；输出同时保留各来源组和各 benchmark 的差值。某个来源组包含更多任务，不会增加它在最终均值中的权重。任何执行失败保留为未评分观测；本版冻结缺失策略是选择结果 inconclusive，不把失败记为零分，也不只挑成功任务比较。

完整面板可产生 `selected_for_validation` 记录，绑定训练测量、规则、候选包与所有评分回执。它是训练侧开发选择，没有显著性、机制端点或科学有效性结论，不签发验证租约、不部署候选。与独立校准验收和既有候选冻结生命周期的接线仍需单独完成。所有 arm 都继续出现在 `combination_candidates_retained`，本接口不授权根据单模块得分裁掉组合候选。

验证使用合成公开任务、实际 journal 与签名链、冻结 rubric endpoint 的合成模型响应，以及受控执行传输，覆盖完整两 benchmark 配对、平分顺序、单 benchmark 退化保护、失败分母、缺项/重复/签名/规则/验证域/日志篡改和来源组权重。合成分数用于工程回归，不能当作 benchmark 效果证据；真实 Docker 的 scorer 接线验证另行记录。
