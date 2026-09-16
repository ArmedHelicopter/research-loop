本地 Qwen2.5-7B-Instruct Q4_K_M 独立系列：4 次 CPU 推理、6 次实际 Docker 输入案例，新增 API 费用为 0。前3次保留 JSON 无效、硬编码示例和缺失值总行数错误。第4次的原程序通过2/2输入案例，但其自报预期输出把A组2行说成3行，因此仅为部分可用性证据，不是整体验收通过。

所有提示修正在公开合成 TRAIN 可用性样例上完成；没有打开实际 VAL，没有 benchmark 效果结论。请求、响应、程序、输入、stdout、Docker回执、模型digest与原生START/JOIN均保留；与Grok/Icompify结果不合并。
