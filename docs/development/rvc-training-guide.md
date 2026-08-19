# RVC 角色中文翻唱开发指南

离线训练的唯一工作区是 [`songs/`](../../songs/README.md)，Baseline 固定为 RVC v2 +
RMVPE。本文件只说明它与 Animetta 正式歌唱运行时的边界。

## 开发阶段

1. 在 `songs/manifests/sources.csv` 登记来源、文本和使用权。
2. 格式统一与自动 QC 后逐条人工听审。
3. 按 `source_id` 冻结训练/验证划分；验证集不做增强。
4. 先生成命令计划，再按根目录 GPU 规则完成同 batch 有界峰值探针。
5. 每个 checkpoint 使用同一中文低/中/高音固定集评测，并保留版本与 AB 记录。

详细命令不在两处复制，以 `songs/README.md` 为准。

## 正式运行时边界

RVC 训练产物不是部署完成。通过评测的候选还必须：

- 计算并固定模型与 index 的 SHA-256；
- 统一生成 provider、model、revision、voice 和 sample rate 身份；
- 同步更新 `config/host-rvc.yaml` 与 `config/singing.yaml`；
- 仅通过 `py -3.13 scripts/runtime_lifecycle.py host-rvc-restart` 重启宿主机 `127.0.0.1:8769`；
- 运行严格模型预检，确认 RVC 与 Demucs 身份；
- 在唯一正式入口 `/live.html` 证明真实声线转换、音频响应和持久播放证据。

`scripts.train.deploy` 只生成晋级候选 JSON，故意不自动执行以上生产变更。这样训练、评测和
运行时发布可分别审计，也不会让一次失败实验覆盖当前稳定声线。
