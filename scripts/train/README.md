# 角色中文翻唱工具

本目录只提供 `songs/` 工作区的确定性工具：

- `workspace.py`：校验清单、按来源冻结划分、生成 RVC 命令计划。
- `prepare_data.py`：统一为 48 kHz 单声道 PCM WAV，并写入自动 QC 指标。
- `materialize_dataset.py`：按 `split.csv` 物化训练集和固定验证集。
- `cli.py`：带 GPU 证据门禁的 fail-fast RVC v2 + RMVPE runner。
- `deploy.py`：生成包含模型/index 哈希的晋级候选，不直接改生产配置。

完整顺序、清单字段和制作流程见 [`songs/README.md`](../../songs/README.md)。Windows 下统一从
仓库根目录用 `py -3.13 -m scripts.train.<module>` 调用。数据未通过人工复核和冻结划分前，
不要执行训练；GPU 峰值探针不满足空闲预算时，不要提高 batch 或启动长任务。
大批量预处理可向 `prepare_data` 传入 `--workers 4`；该参数只并行处理互不依赖的音频条目，
不会改变清单排序、QC 算法或训练划分。
