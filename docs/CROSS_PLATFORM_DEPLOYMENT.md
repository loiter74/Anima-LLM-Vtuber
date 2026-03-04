# 跨环境部署快速指南

## 🎯 目标

**点击 `start.ps1` 后自动启动，无需手动配置！**

---

## ✅ 已实现的自动化功能

### 1. 首次运行自动配置

第一次运行 `start.ps1` 时，系统会自动：

- ✅ 检测运行环境（Windows/WSL/Linux）
- ✅ 检测GPU/CUDA可用性
- ✅ 自动生成 `.env` 配置文件
- ✅ 创建数据目录结构
- ✅ 配置模型路径
- ✅ GPU不可用时自动降级到CPU

### 2. 路径自动适配

| 环境 | 数据目录 | 说明 |
|------|----------|------|
| **Windows** | `E:/anima_data/` 或 `C:/Users/xxx/anima_data/` | 优先E盘 |
| **WSL** | `/mnt/e/anima_data/` 或 `~/anima_data/` | 共享Windows数据 |
| **Linux** | `~/anima_data/` | 用户主目录 |

### 3. 依赖自动安装

- ✅ 检测缺失的Python包
- ✅ 自动运行 `pip install`
- ✅ 可选依赖（pydub）自动安装

---

## 🚀 使用方法

### Windows

```powershell
# 第一次运行（自动配置）
.\scripts\start.ps1

# 之后每次启动
.\scripts\start.ps1
```

### WSL/Linux

```bash
# 第一次运行（自动配置）
./scripts/start.sh

# 之后每次启动
./scripts/start.sh
```

---

## 🔧 高级选项

### 强制重新配置

```powershell
# Windows
.\scripts\start.ps1 -AutoConfig

# WSL/Linux
./scripts/start.sh --auto-config
```

### 仅检查环境

```bash
python -m src.anima.utils.auto_config --check
```

### 手动配置

```bash
python -m src.anima.utils.auto_config --setup
```

---

## 📁 自动创建的目录结构

```
E:/anima_data/          # 或 ~/anima_data/
├── models/
│   ├── base_models/    # HuggingFace模型缓存
│   └── checkpoints/    # 训练的LoRA模型
├── vectordb/           # RAG向量数据库
└── histories/          # 对话历史
```

---

## ⚠️ 常见问题

### Q1: 模型路径不存在怎么办？

**A**: 系统会自动创建目录，但你需要下载模型：

```bash
# 方案1: 使用HuggingFace自动下载（首次运行时）
# 系统会自动下载到缓存目录

# 方案2: 手动指定已有模型路径
# 编辑 .env 文件：
ANIMA_BASE_MODEL_PATH=/path/to/your/model
```

### Q2: GPU不可用，速度很慢？

**A**: 系统会自动降级到CPU，但会很慢。建议：

```bash
# 安装CUDA版本PyTorch
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### Q3: WSL访问Windows盘很慢？

**A**: 是的，`/mnt/e/` 比WSL本地文件系统慢。

**解决方案**：

```bash
# 方案1: 数据存储在WSL本地（性能更好，但不共享）
# 编辑 .env：
ANIMA_DATA_DIR=~/anima_data

# 方案2: 符号链接（共享+性能）
ln -s /mnt/e/anima_data ~/anima_data
```

### Q4: 依赖安装失败？

**A**: 手动安装：

```bash
pip install -r requirements.txt
```

---

## 🎛️ 环境检测示例输出

```
========================================
  Anima 环境诊断
========================================
📌 平台: WINDOWS
🐍 Python: 3.10.0

✅ GPU: 可用 (CUDA 11.8)

✅ 数据目录: E:\anima_data

✅ Python依赖: 完整

✅ 配置文件: C:\Users\xxx\Anima\.env

========================================
```

---

## 📝 配置文件说明

### .env 文件（自动生成）

```bash
# 数据目录
ANIMA_DATA_DIR=E:/anima_data

# 模型路径
ANIMA_BASE_MODEL_PATH=E:/anima_data/models/base_models/Qwen1.5-1.8B-Chat
ANIMA_LORA_PATH=E:/anima_data/models/checkpoints/neuro-vtuber-v1

# 向量数据库
ANIMA_VECTOR_DB_PATH=E:/anima_data/vectordb

# 对话历史
ANIMA_HISTORY_PATH=E:/anima_data/histories
```

### 修改配置

直接编辑 `.env` 文件，然后重启服务。

---

## 🔍 故障排查

### 查看详细日志

```yaml
# config/config.yaml
system:
  log_level: DEBUG
```

### 健康检查

```bash
python -m src.anima.utils.auto_config --check
```

### 重置配置

```bash
# 删除 .env 文件
rm .env

# 重新运行（会自动生成）
./scripts/start.sh
```

---

## 💡 最佳实践

1. **首次运行**: 让系统自动配置，不要手动修改
2. **模型存储**: Windows用E盘，WSL用`~/anima_data`（性能更好）
3. **GPU加速**: 安装CUDA版PyTorch
4. **配置备份**: 定期备份 `.env` 文件
5. **环境隔离**: 使用虚拟环境（venv）

---

## 📊 性能对比

| 配置 | 速度 | 说明 |
|------|------|------|
| GPU (CUDA) | ⚡⚡⚡⚡⚡ | 最快（推荐） |
| CPU (高性能) | ⚡⚡ | 可用 |
| CPU (低性能) | ⚡ | 慢但可用 |

---

## 🎉 完成！

现在你只需要：
1. 双击 `start.ps1`（Windows）或运行 `start.sh`（WSL/Linux）
2. 打开浏览器访问 `http://localhost:3000`

**就这么简单！** 🚀
