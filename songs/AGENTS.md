# 角色翻唱工作区规则

本目录保存角色中文翻唱的可复现配置、清单和制作协议，不保存受版权保护的原始音频、
模型权重、索引、分轨、DAW 工程或导出音频。

## 不可变边界

- `audio/raw/` 只接收来源明确、使用权已记录的原始副本，不覆盖源文件。
- 人工复核必须发生在固定划分之前；`split.csv` 一旦冻结，不得用新增数据静默重算。
- 同一 `source_id` 的切片和增强版本只能属于同一个集合；验证集不做音高增强。
- Baseline 固定为 RVC v2 + RMVPE。改变模型家族时保留同一验证集并建立独立版本。
- GPU 训练前执行仓库根规则要求的进程归属检查和有界峰值探针；不得凭总显存猜 batch。
- 训练产物只能先进入 `runs/`。正式晋级必须同时更新模型、index、哈希、宿主身份、
  `config/host-rvc.yaml`、`config/singing.yaml`，再经规范生命周期重启和正式入口验收。
- 不提交 `audio/`、`runs/`、`evaluation/audio/`、`evaluation/renders/`、`production/` 中的媒体产物。

清单协议和操作顺序见 [README.md](README.md)。
