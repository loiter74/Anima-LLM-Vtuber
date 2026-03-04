# 训练脚本目录

**PyTorch Lightning 训练工具** - 简化后的训练脚本集

---

## 📁 脚本列表

### 1. 快速训练脚本

**文件**: `quick_train_lightning.py`

**用途**: 最简单的训练脚本，使用默认配置快速开始

**使用方法**:
```bash
python scripts/training/quick_train_lightning.py
```

**默认配置**:
- 模型: Qwen/Qwen2.5-7B-Instruct
- 数据: datasets/training.jsonl
- 输出: models/lora/quick-model
- 轮数: 3
- 批次大小: 4
- 学习率: 2e-4

**适用场景**:
- ✅ 快速原型验证
- ✅ 新手入门
- ✅ 小数据集训练

---

### 2. 完整训练脚本

**文件**: `train_lightning.py`

**用途**: 完整的训练脚本，支持所有参数配置

**使用方法**:
```bash
# 基础训练
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data datasets/training.jsonl \
    --output models/lora/my-model

# 自定义配置
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data datasets/training.jsonl \
    --output models/lora/my-model \
    --r 32 \
    --lora_alpha 64 \
    --batch_size 8 \
    --epochs 5 \
    --lr 1e-4

# 多 GPU 训练
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data datasets/training.jsonl \
    --output models/lora/my-model \
    --devices 2

# 查看所有参数
python scripts/training/train_lightning.py --help
```

**主要参数**:
- `--model`: 基座模型名称
- `--data`: 训练数据路径
- `--output`: 输出目录
- `--r`: LoRA rank（默认 16）
- `--lora_alpha`: LoRA alpha（默认 32）
- `--batch_size`: 批次大小（默认 4）
- `--epochs`: 训练轮数（默认 3）
- `--lr`: 学习率（默认 2e-4）
- `--devices`: GPU 数量（默认 1）

**适用场景**:
- ✅ 生产环境训练
- ✅ 大数据集训练
- ✅ 多 GPU 训练
- ✅ 自定义配置

---

### 3. 数据采集脚本

**文件**: `collect_data.py`

**用途**: 统一的数据采集工具，支持多种数据源

**使用方法**:
```bash
# B站视频采集
python scripts/training/collect_data.py \
    --source bilibili \
    --type video \
    --url https://www.bilibili.com/video/BV1xx411c7mD

# 本地文件加载
python scripts/training/collect_data.py \
    --source local \
    --file data/raw/conversations.jsonl

# 下载公开数据集
python scripts/training/collect_data.py \
    --source public \
    --dataset VTuber-Conversations

# 合并多个数据集
python scripts/training/collect_data.py \
    --source merge \
    --files data1.jsonl data2.jsonl \
    --output merged.jsonl

# 查看帮助
python scripts/training/collect_data.py --help
```

**数据源类型**:
- `bilibili`: B站视频弹幕采集
- `local`: 本地文件加载
- `public`: 公开数据集下载
- `merge`: 合并多个数据集

**适用场景**:
- ✅ 数据收集
- ✅ 数据预处理
- ✅ 数据集合并

---

### 4. 模型部署脚本

**文件**: `deploy_to_anima.py`

**用途**: 将训练好的 LoRA 模型部署到 Anima 系统

**使用方法**:
```bash
python scripts/training/deploy_to_anima.py \
    --model_path models/lora/my-model \
    --config_name my_lora_model
```

**功能**:
- 复制 LoRA 适配器到 models 目录
- 生成配置文件
- 更新 Anima 配置

**适用场景**:
- ✅ 训练完成后部署
- ✅ 模型测试
- ✅ 生产部署

---

## 🚀 快速开始

### 完整训练流程

```bash
# 1. 采集数据
python scripts/training/collect_data.py \
    --source bilibili \
    --url https://www.bilibili.com/video/BV1xx411c7mD

# 2. 快速训练（使用默认配置）
python scripts/training/quick_train_lightning.py

# 3. 部署模型
python scripts/training/deploy_to_anima.py \
    --model_path models/lora/quick-model

# 完成！
```

### 高级训练流程

```bash
# 1. 采集和合并数据
python scripts/training/collect_data.py --source bilibili --url <url1>
python scripts/training/collect_data.py --source bilibili --url <url2>
python scripts/training/collect_data.py \
    --source merge \
    --files data1.jsonl data2.jsonl \
    --output training.jsonl

# 2. 自定义配置训练
python scripts/training/train_lightning.py \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data training.jsonl \
    --output models/lora/my-model \
    --r 32 \
    --batch_size 8 \
    --epochs 5 \
    --devices 2

# 3. 部署模型
python scripts/training/deploy_to_anima.py \
    --model_path models/lora/my-model

# 完成！
```

---

## 📊 脚本对比

| 脚本 | 代码量 | 功能 | 复杂度 |
|------|--------|------|--------|
| `quick_train_lightning.py` | ~100 行 | 快速训练 | 低 |
| `train_lightning.py` | ~300 行 | 完整训练 | 中 |
| `collect_data.py` | ~300 行 | 数据采集 | 中 |
| `deploy_to_anima.py` | ~150 行 | 模型部署 | 低 |

---

## 📖 相关文档

- **PyTorch Lightning 指南**: `docs/training/PYTORCH_LIGHTNING_GUIDE.md`
- **重构报告**: `docs/training/REFACTOR_REPORT.md`
- **数据收集指南**: `docs/training/QUICK_START_GUIDE.md`

---

## 🎓 最佳实践

### 1. 选择合适的脚本

- **新手/快速原型**: 使用 `quick_train_lightning.py`
- **生产环境**: 使用 `train_lightning.py`
- **数据收集**: 使用 `collect_data.py`
- **模型部署**: 使用 `deploy_to_anima.py`

### 2. 数据准备

- ✅ 至少 1000 条高质量对话
- ✅ 使用 JSONL 格式
- ✅ 验证数据格式正确
- ✅ 划分训练/验证集（自动）

### 3. 训练配置

- **小数据集 (< 1000 条)**: r=8, lr=2e-4, epochs=3
- **中等数据集 (1000-10000 条)**: r=16, lr=2e-4, epochs=5
- **大数据集 (> 10000 条)**: r=32, lr=1e-4, epochs=10

### 4. 监控训练

```bash
# TensorBoard
tensorboard --logdir models/lora/my-model/logs

# 浏览器打开
http://localhost:6006
```

---

## ✅ 总结

**精简后的训练工具集**（4 个脚本）:
1. ✅ `quick_train_lightning.py` - 快速训练
2. ✅ `train_lightning.py` - 完整训练
3. ✅ `collect_data.py` - 数据采集
4. ✅ `deploy_to_anima.py` - 模型部署

**对比旧版本**:
- 脚本数量: 4 个 vs 18 个（**-78%**）
- 代码总量: ~850 行 vs ~2000 行（**-58%**）
- 功能: 更强大（多 GPU、早停、高级日志）

**开始使用**:
```bash
pip install pytorch-lightning
python scripts/training/quick_train_lightning.py
```

**享受简洁高效的训练体验！** 🚀
