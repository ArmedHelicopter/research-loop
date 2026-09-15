# C5 headless runtime probe 原件暂存

这是只读工程探针原件的公开索引，不是 C5 qualification、完整 controller、评分闭合、选择、注册或真实效果证据。保留了仍存在的 r1–r4 probe/preflight basetemp 与 JUnit；缺失原件在 manifest 中明确列出而未补造。

- r4 产物视图：212 个 catalogue descriptor、311 条真实 parent 边、1 条外层明确 history-build 绑定。
- r4 实际探针：11 次 synthetic solver MAIN；evaluator 调用与 native GET 均为 0。
- 46 个 history build 与 118 个 target/scorer cell 是冻结分母；本 probe 只执行 1 个 history 与 1 个 target。
- 70 个 trace descriptor 仍是 module=null、coverage=uncovered。M8 history 为 not_applied；M9 仅 history。

公开副本逐字节读回并由 `public-manifest.json` 绑定。私有 ZIP 排除 auth、`.key`、以及文件名含 credential/secret/authority 的文件，并排除 reparse points；其成员逐个 CRC/字节回读。输入原件在归档前后比对 SHA-256、字节数和 mtime。

测试源码仅为结束后的 git-object 快照。r1–r3 没有逐次不可变源码副本；fixture 生产源码同样不能被此暂存升级为全程前后冻结证明。
