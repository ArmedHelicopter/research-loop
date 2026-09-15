# C5 probe producer-source 补充

`producer-source-afterrun.zip` 是从 212 节点视图中每个 `producer_source` 指向的 9 个实际源码文件生成的 after-run matching snapshot。每个文件在归档时都与对应 descriptor 的 SHA-256 和字节数匹配，ZIP 成员已逐一读回。

这不是 r1–r4 或 r4 probe 的全程源码冻结证明：探针结束后才进行匹配快照，且不会复制整个仓库。`retention-manifest.json` 是私有原件保留清单的逐字节公开索引副本，列出 archive 路径、成员 origins、排除项及原件 before/after stamps；原件内容仍只在私有 ZIP。
