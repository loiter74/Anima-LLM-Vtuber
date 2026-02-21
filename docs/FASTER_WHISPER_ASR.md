# Faster-Whisper ASR 使用说明

## 简介

Faster-Whisper 是一个开源免费的语音识别方案，基于 OpenAI Whisper 模型的优化实现，完全离线运行，无需 API 密钥或付费服务。

## 特点

- ✅ **完全免费** - 无需 API 密钥，无使用配额限制
- ✅ **开源** - https://github.com/guillaumekln/faster-whisper
- ✅ **离线运行** - 模型下载后无需网络连接
- ✅ **多语言支持** - 支持 90+ 种语言，包括中文
- ✅ **高准确率** - 基于 Whisper 模型，识别准确率高
- ✅ **速度快** - 比 OpenAI Whisper 快 4 倍以上

## 已安装的依赖

```bash
pip install faster-whisper
```

## 配置文件

配置文件位置: `config/services/asr/faster_whisper.yaml`

```yaml
type: faster_whisper
model: distil-large-v3      # 推荐模型（支持多语言，速度快）
language: zh                  # 语言代码
device: auto                  # 设备（auto/cpu/cuda）
compute_type: default        # 计算精度
beam_size: 5                 # 束搜索大小（1-10）
vad_filter: true             # 启用 VAD 过滤
```

## 模型选择

| 模型 | 大小 | 速度 | 准确率 | 推荐场景 |
|------|------|------|--------|----------|
| tiny | ~40 MB | 最快 | 较低 | 实时测试 |
| base | ~140 MB | 快 | 中等 | 平衡选择 |
| small | ~460 MB | 中等 | 较高 | 日常使用 |
| medium | ~1.5 GB | 较慢 | 高 | 正式场合 |
| **distil-large-v3** | ~1.5 GB | **快** | **很高** | **强烈推荐** |
| large-v3 | ~3 GB | 慢 | 最高 | 追求准确率 |

## 切换到 Faster-Whisper ASR

### 方法 1: 修改配置文件

编辑 `config/config.yaml`:

```yaml
services:
  asr: faster_whisper   # 从 mock 改为 faster_whisper
  tts: edge
  agent: glm
  vad: silero
```

### 方法 2: 使用不同模型

编辑 `config/services/asr/faster_whisper.yaml`:

```yaml
# 快速模式（适合测试）
model: tiny
beam_size: 1

# 推荐模式（平衡速度和准确率）
model: distil-large-v3
beam_size: 5

# 高精度模式（追求准确率）
model: large-v3
beam_size: 5
```

## 性能优化

### CPU 模式优化

```yaml
device: cpu
compute_type: int8        # 使用量化加速
model: distil-large-v3
beam_size: 5
```

### GPU 模式（如果有 NVIDIA 显卡）

```yaml
device: cuda
compute_type: float16    # 使用半精度加速
model: distil-large-v3
beam_size: 5
```

## 首次使用

首次使用时会自动下载模型（约 1.5 GB for distil-large-v3）：

```bash
# 模型会下载到:
# Windows: C:\Users\<用户>\.cache\huggingface\hub\
# Linux/Mac: ~/.cache/huggingface/hub/
```

下载进度会显示在日志中。

## 性能参考

在 CPU (Intel i5) 上的性能：

| 音频长度 | 处理时间 | 实时率 |
|---------|---------|--------|
| 5 秒 | ~2 秒 | 2.5x 实时 |
| 10 秒 | ~4 秒 | 2.5x 实时 |
| 30 秒 | ~12 秒 | 2.5x 实时 |

## 测试

运行测试脚本：

```bash
python test_faster_whisper.py
```

预期输出：
```
[OK] 配置类导入成功
[OK] 配置实例创建成功
[OK] 服务类导入成功

所有测试通过! Faster-Whisper ASR 集成成功!
```

## 与其他 ASR 对比

| ASR 类型 | 优点 | 缺点 | 价格 |
|---------|------|------|------|
| **Faster-Whisper** | 免费、离线、开源 | CPU 占用较高 | 免费 |
| GLM ASR | 准确率高、速度快 | 需要付费 | 按量付费 |
| Mock ASR | 快速测试 | 不识别真实语音 | 测试用 |

## 故障排查

### 问题 1: 模型下载失败

```bash
# 手动下载模型
huggingface-cli download guillaumekln/distil-whisper-large-v3
```

### 问题 2: 内存不足

切换到更小的模型：
```yaml
model: small  # 或 tiny
compute_type: int8  # 使用量化
```

### 问题 3: CPU 占用过高

1. 使用更小的模型（tiny/base）
2. 启用量化：`compute_type: int8`
3. 减小 beam_size：`beam_size: 1`

## 相关链接

- Faster-Whisper GitHub: https://github.com/guillaumekln/faster-whisper
- Whisper 论文: https://arxiv.org/abs/2212.04356
- 模型列表: https://github.com/guillaumekln/faster-whisper#model-comparison

## 开源许可

Faster-Whisper 使用 MIT 许可证，可自由使用和修改。
