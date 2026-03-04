# Anima 训练系统

**基于 PyTorch Lightning 的简化训练系统**

---

## 📁 目录结构

```
Anima/
├── training_data/                     # 训练数据集
│   ├── raw/                     # 原始数据
│   ├── processed/               # 处理后的数据
│   │   ├── train.jsonl
│   │   ├── validation.jsonl
│   │   └── test.jsonl
│   └── metadata/                # 数据集元信息
│
├── memory_db/                      # 记忆数据库
│   └── memories.db              # 长期记忆存储
│
├── config/
│   └── training/                # 训练配置文件
│       └── default.yaml         # 默认训练配置
│
├── scripts/
│   └── training/                # 训练脚本
│       ├── train_lightning.py   # 完整训练脚本
│       ├── quick_train_lightning.py  # 快速训练脚本
│       ├── collect_data.py      # 数据采集脚本
│       ├── deploy_to_anima.py   # 模型部署脚本
│       └── README.md            # 脚本使用说明
│
├── src/anima/
│   └── training/                # 训练模块
│       ├── model_ckpt/              # 模型定义
│       │   ├── lightning_module.py   # Lightning 模块
│       │   └── lightning_data.py     # Lightning 数据模块
│       └── dataset/             # 数据集管理
│           └── manager.py       # 数据集管理器
│
└── docs/
    └── training/                # 训练文档
        ├── README.md            # 本文档
        ├── PYTORCH_LIGHTNING_GUIDE.md  # 使用指南
        ├── REFACTOR_REPORT.md   # 重构报告
        └── WSL_PYTORCH_INSTALL_GUIDE.md  # 环境安装
```

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

**数据格式**（JSONL）:
```jsonl
{"conversation": [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！我是 AI 助手"}]}
{"conversation": [{"role": "user", "content": "今天天气怎么样？"}, {"role": "assistant", "content": "抱歉，我无法获取实时天气信息"}]}
```

保存到: `training_data/training.jsonl`

### 3. 开始训练

#### 方式 1: 快速训练（推荐）

```bash
python scripts/training/quick_train_lightning.py
```

#### 方式 2: 完整训练

```bash
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training_data/training.jsonl \
    --output model_ckpt/lora/my-model \
    --r 16 \
    --batch_size 4 \
    --epochs 3
```

---

## 📝 训练配置

### 配置文件

编辑 `config/training/default.yaml`:

```yaml
# 实验信息
experiment:
  name: "neuro-vtuber-v1"
  description: "Neuro-sama character model"

# 模型配置
model:
  base_model: "Qwen/Qwen2.5-7B-Instruct"

# LoRA 配置
lora:
  r: 16
  alpha: 32
  dropout: 0.1

# 训练参数
training:
  num_epochs: 3
  per_device_train_batch_size: 4
  learning_rate: 0.0002

# 数据配置
data:
  train_path: "training_data/processed/train.jsonl"
  validation_path: "training_data/processed/validation.jsonl"
  max_length: 512
```

---

## 🔧 训练流程

### 完整训练流程

```bash
# 1. 采集数据
python scripts/training/collect_data.py \
    --source bilibili \
    --url https://www.bilibili.com/video/BV1xx411c7mD

# 2. 快速训练
python scripts/training/quick_train_lightning.py

# 3. 部署模型
python scripts/training/deploy_to_anima.py \
    --model_path model_ckpt/lora/quick-model
```

---

## 📚 文档索引

- **[PyTorch Lightning 指南](./PYTORCH_LIGHTNING_GUIDE.md)** - 完整使用指南
- **[重构报告](./REFACTOR_REPORT.md)** - 代码重构说明
- **[环境安装](./WSL_PYTORCH_INSTALL_GUIDE.md)** - WSL + PyTorch 环境配置
- **[脚本使用说明](../../scripts/training/README.md)** - 训练脚本详细说明

---

## 🎯 训练模式

### 1. LoRA 微调（默认）

**适用场景**: 角色扮演、对话风格定制

**特点**:
- 训练参数少（~1%）
- 显存需求低（7B 模型只需 ~16GB）
- 训练速度快

**配置**:
```yaml
lora:
  r: 16        # Rank（越大参数越多）
  alpha: 32    # 缩放因子
  dropout: 0.1 # Dropout 比例
```

---

## 📊 监控训练

### TensorBoard

```bash
# 启动 TensorBoard
tensorboard --logdir model_ckpt/lora/my-model/logs

# 浏览器打开
http://localhost:6006
```

### WandB

```bash
python scripts/training/train_lightning.py \
    --logger wandb \
    --project my-project \
    --run_name my-experiment
```

---

## 🔍 故障排查

### 常见问题

#### 1. CUDA Out of Memory

**解决方案**:
```bash
# 减小批次大小
python scripts/training/train_lightning.py --batch_size 2

# 增加梯度累积
python scripts/training/train_lightning.py --accumulate_grad_batches 8

# 减小 LoRA rank
python scripts/training/train_lightning.py --r 8
```

#### 2. 训练速度慢

**解决方案**:
```bash
# 增加批次大小
python scripts/training/train_lightning.py --batch_size 8

# 多 GPU 训练
python scripts/training/train_lightning.py --devices 2
```

#### 3. 验证损失不下降

**解决方案**:
- 检查数据质量
- 调整学习率: `--lr 1e-4`
- 增加 LoRA rank: `--r 32`
- 增加训练轮数: `--epochs 5`

---

## ✅ 最佳实践

### 1. 数据准备

- ✅ 至少 1000 条高质量对话
- ✅ 使用 JSONL 格式
- ✅ 验证数据格式正确
- ✅ 划分训练/验证集

### 2. 超参数调优

- **小数据集 (< 1000 条)**: r=8, lr=2e-4
- **中等数据集 (1000-10000 条)**: r=16, lr=2e-4
- **大数据集 (> 10000 条)**: r=32, lr=1e-4

### 3. 训练监控

- 观察 train_loss 和 val_loss
- 验证损失不再下降时停止
- 保存最佳模型（基于 val_loss）

---

## 🎉 总结

**Anima 训练系统的优势**:

1. ✅ **简单**: 只需 3 行代码即可开始训练
2. ✅ **快速**: PyTorch Lightning 自动优化
3. ✅ **强大**: 支持多 GPU、混合精度、早停等
4. ✅ **灵活**: 易于自定义和扩展

**开始使用**:
```bash
pip install pytorch-lightning
python scripts/training/quick_train_lightning.py
```

**享受高效的训练体验！** 🚀
