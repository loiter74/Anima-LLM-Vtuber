# PyTorch Lightning 训练指南

**简化训练流程，更少的代码，更多的功能**

---

## 📖 概述

我们使用 **PyTorch Lightning** 重构了训练脚本，提供了以下优势：

- ✅ **代码简洁**: 训练代码减少 70%
- ✅ **自动化**: 自动处理训练循环、验证、检查点
- ✅ **多 GPU 支持**: 一行代码启用多 GPU 训练
- ✅ **高级功能**: 混合精度、梯度累积、早停等
- ✅ **易于调试**: 内置日志和可视化

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements-training.txt
```

**核心依赖**:
- `pytorch-lightning>=2.1.0` - 训练框架
- `transformers>=4.36.0` - 模型和分词器
- `datasets>=2.15.0` - 数据集处理
- `peft>=0.7.0` - LoRA 适配器

### 2. 准备数据

数据格式（JSONL）:
```jsonl
{"conversation": [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！我是 AI 助手"}]}
{"conversation": [{"role": "user", "content": "今天天气怎么样？"}, {"role": "assistant", "content": "抱歉，我无法获取实时天气信息"}]}
```

保存到: `training_data/training.jsonl`

### 3. 开始训练

#### 方式 1: 快速训练（推荐新手）

```bash
python scripts/training/quick_train_lightning.py
```

**默认配置**:
- 模型: Qwen/Qwen2.5-7B-Instruct
- 数据: training_data/training.jsonl
- 输出: model_ckpt/lora/quick-model
- 轮数: 3
- 批次大小: 4
- 学习率: 2e-4

#### 方式 2: 完整训练脚本

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --r 16 \
    --lora_alpha 32 \
    --batch_size 4 \
    --epochs 3 \
    --lr 2e-4
```

#### 方式 3: Python 代码（3 行）

```python
from training.models import SimpleLightningModule, LightningDataModule
import pytorch_lightning as pl

# 1. 创建模型和数据
model = SimpleLightningModule(model_name="Qwen/Qwen2.5-7B-Instruct")
data = LightningDataModule(data_path="training_data/training.jsonl", tokenizer=model.tokenizer)

# 2. 训练
trainer = pl.Trainer(max_epochs=3, precision="bf16")
trainer.fit(model, data)

# 3. 保存
model.save_model("model_ckpt/lora/my-model")
```

---

## ⚙️ 配置参数

### 模型参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--model` | 必填 | 基座模型名称或路径 |
| `--tokenizer` | 与 model 相同 | 分词器名称 |
| `--r` | 16 | LoRA rank（越大参数越多） |
| `--lora_alpha` | 32 | LoRA alpha（缩放因子） |
| `--lora_dropout` | 0.05 | Dropout 比率 |

### 数据参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--data` | 必填 | 训练数据路径（.jsonl） |
| `--max_length` | 512 | 最大序列长度 |
| `--batch_size` | 4 | 批次大小 |
| `--num_workers` | 4 | 数据加载线程数 |

### 训练参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--epochs` | 3 | 训练轮数 |
| `--lr` | 2e-4 | 学习率 |
| `--weight_decay` | 0.01 | 权重衰减 |
| `--warmup_steps` | 100 | 预热步数 |
| `--gradient_clip_val` | 1.0 | 梯度裁剪 |

### 高级参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--devices` | 1 | GPU 数量 |
| `--precision` | bf16 | 精度（32/16/bf16） |
| `--accumulate_grad_batches` | 4 | 梯度累积步数 |
| `--logger` | tensorboard | 日志类型（wandb/tensorboard/none） |
| `--checkpoint_dir` | output/checkpoints | 检查点目录 |

---

## 🎯 多 GPU 训练

### 2 个 GPU

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --devices 2
```

### 4 个 GPU

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --devices 4
```

### 自动检测所有可用 GPU

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --devices -1
```

---

## 📊 监控训练

### TensorBoard（默认）

```bash
# 启动 TensorBoard
tensorboard --logdir model_ckpt/lora/my-model/logs

# 浏览器打开
http://localhost:6006
```

### Weights & Biases (WandB)

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --logger wandb \
    --project my-project \
    --run_name my-experiment
```

---

## 🔧 高级功能

### 1. 早停（Early Stopping）

自动启用，监控验证损失，3 个 epoch 无改善则停止训练。

### 2. 模型检查点

自动保存最佳 3 个模型（基于验证损失）。

### 3. 混合精度训练

默认使用 BF16 精度，加速训练并减少显存占用。

### 4. 梯度累积

默认累积 4 步梯度，等效批次大小 = batch_size × accumulate_grad_batches

### 5. 学习率调度

默认使用 Cosine 退火调度器。

---

## 📈 性能对比

### 代码量对比

| 方式 | 代码行数 | 功能 |
|------|----------|------|
| **Transformers Trainer（旧）** | ~500 行 | 基础训练 |
| **PyTorch Lightning（新）** | ~150 行 | 基础 + 高级功能 |

**减少 70% 代码量！**

### 功能对比

| 功能 | Transformers | Lightning |
|------|--------------|-----------|
| 基础训练 | ✅ | ✅ |
| 多 GPU | ❌ 需要额外配置 | ✅ 一行代码 |
| 混合精度 | ✅ | ✅ |
| 梯度累积 | ✅ | ✅ |
| 早停 | ❌ 需要手动实现 | ✅ 自动 |
| 检查点 | ✅ | ✅ |
| 日志 | ❌ 基础 | ✅ WandB/TensorBoard |
| 调试 | ❌ 困难 | ✅ 简单 |

---

## 🐛 故障排查

### 1. CUDA Out of Memory

**解决方案**:
- 减小批次大小: `--batch_size 2`
- 增加梯度累积: `--accumulate_grad_batches 8`
- 减小序列长度: `--max_length 256`
- 使用更小的 LoRA rank: `--r 8`

### 2. 训练速度慢

**解决方案**:
- 增加批次大小: `--batch_size 8`
- 增加数据加载线程: `--num_workers 8`
- 启用混合精度: `--precision bf16`
- 使用多 GPU: `--devices 2`

### 3. 验证损失不下降

**解决方案**:
- 检查数据质量和格式
- 调整学习率: `--lr 1e-4`
- 增加 LoRA rank: `--r 32`
- 增加训练轮数: `--epochs 5`

---

## 📚 代码示例

### 完整训练流程

```python
from training.models import SimpleLightningModule, LightningDataModule
import pytorch_lightning as pl
from transformers import AutoTokenizer

# 1. 加载分词器
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct", trust_remote_code=True)

# 2. 准备数据
data_module = LightningDataModule(
    data_path="training_data/training.jsonl",
    tokenizer=tokenizer,
    batch_size=4,
    max_length=512
)

# 3. 创建模型
model = SimpleLightningModule(
    model_name="Qwen/Qwen2.5-7B-Instruct",
    lora_r=16,
    lora_alpha=32,
    learning_rate=2e-4
)

# 4. 训练
trainer = pl.Trainer(
    max_epochs=3,
    precision="bf16",
    devices=1,
    log_every_n_steps=10
)
trainer.fit(model, data_module)

# 5. 保存模型
model.save_model("model_ckpt/lora/my-model")
```

### 自定义训练循环

```python
from training.models import LoRALightningModule, LightningLoRAConfig

# 自定义配置
config = LightningLoRAConfig(
    model_name="Qwen/Qwen2.5-7B-Instruct",
    r=32,
    lora_alpha=64,
    lora_dropout=0.1,
    learning_rate=1e-4,
    weight_decay=0.01,
    max_seq_length=1024
)

# 创建模型
model = LoRALightningModule(config)

# 训练
trainer = pl.Trainer(max_epochs=5, precision="bf16")
trainer.fit(model, data_module)
```

---

## 🎓 最佳实践

### 1. 数据准备

- ✅ 使用高质量、多样化的对话数据
- ✅ 至少 1000 条对话样本
- ✅ 避免数据泄露（训练集/验证集分离）

### 2. 超参数调优

- **小数据集 (< 1000 条)**: r=8, lr=2e-4
- **中等数据集 (1000-10000 条)**: r=16, lr=2e-4
- **大数据集 (> 10000 条)**: r=32, lr=1e-4

### 3. 训练监控

- 观察 train_loss 和 val_loss
- 验证损失不再下降时停止训练
- 保存最佳模型（基于 val_loss）

### 4. 模型评估

- 在测试集上评估最终模型
- 使用人工评估对话质量
- 检查是否过拟合（train_loss << val_loss）

---

## 🔗 相关文档

- **数据收集**: `docs/training/QUICK_START_GUIDE.md`
- **LoRA 技能**: `docs/training/LORA_TRAINING_SKILL.md`
- **环境设置**: `docs/training/WSL_PYTORCH_INSTALL_GUIDE.md`

---

## ✅ 总结

**使用 PyTorch Lightning，训练 LoRA 模型从未如此简单！**

```bash
# 3 步开始训练
pip install pytorch-lightning
python scripts/training/quick_train_lightning.py
# 完成！
```

**优势**:
- 代码减少 70%
- 功能更加丰富
- 易于调试和维护
- 支持分布式训练

**开始使用 PyTorch Lightning，享受高效训练！** 🚀
