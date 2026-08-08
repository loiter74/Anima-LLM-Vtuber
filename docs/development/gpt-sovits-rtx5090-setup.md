# GPT-SoVITS on RTX 50系列显卡 (5090D) 部署指南

## 问题背景

RTX 5090D (GB202, Blackwell 架构) 实际 compute capability 为 **sm_120**（不是 sm370！）。标准 PyTorch 发布版（≤2.6）仅编译支持到 sm90。直接运行 GPT-SoVITS 会报错：

```
FATAL: this function is for sm80, but was built for sm370
```

> ⚠️ 这个错误信息中的 `sm370` 是**预编译 CUDA 扩展的构建产物版本号损坏**，不是真实的 NVIDIA 计算能力。真实能力是 sm_120 (12.0)。修复方法是使用支持 sm_120 的 PyTorch cu128 构建。

本指南提供完整的解决方案，包含 **WSL2**（推荐）和 **原生 Windows** 两种方式。

截至 2026 年 5 月，**PyTorch 2.11.0 cu128 已正式支持 Blackwell**，无需使用 nightly 版本。

---

## 核心命令（汇总）

无论哪种方案，核心就是两件事：
1. **安装正确的 PyTorch**: `pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128`
2. **应用 3 个代码补丁**（见下文第 5 节）

---

## 方案一：WSL2（推荐）

### 1. 环境准备

#### 1.1 安装 WSL2

```powershell
# 以管理员身份打开 PowerShell，运行：
wsl --install -d Ubuntu-22.04
```

重启后完成 WSL2 Ubuntu 初始化（设置用户名、密码）。

> ⚠️ **不要**在 `/mnt/` 目录下操作（如 `/mnt/c/`）— 跨文件系统 I/O 性能很差。
> 所有操作在 WSL2 原生文件系统 `~/` 下进行。

#### 1.2 安装 NVIDIA 驱动

确保 Windows 已安装最新的 **NVIDIA Game Ready 或 Studio 驱动**（≥ CUDA 12.8 支持，驱动版本 ≥ 565.90）。

在 WSL2 中验证 GPU 可见性：

```bash
nvidia-smi
```

应能看到 RTX 5090D 信息，且 CUDA Version 列为 12.8。

#### 1.3 安装 Miniconda

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
source ~/.bashrc
```

#### 1.4 创建 Python 3.10 环境

```bash
conda create -n gpt-sovits python=3.10
conda activate gpt-sovits
```

### 2. 安装 PyTorch (CUDA 12.8)

**使用稳定版（推荐）：**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

如果需要最新特性，可使用 nightly：
```bash
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
```

#### 验证 CUDA 可用性

```bash
python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'CUDA version: {torch.version.cuda}')
print(f'Arch list: {torch.cuda.get_arch_list()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'Compute Capability: {torch.cuda.get_device_capability(0)}')
    # 实际 CUDA 运算测试
    x = torch.randn(1000, 1000, device='cuda')
    y = torch.randn(1000, 1000, device='cuda')
    z = x @ y
    print(f'CUDA matmul test: PASSED ({z.shape})')
"
```

预期输出：
```
PyTorch: 2.11.0+cu128
CUDA available: True
CUDA version: 12.8
Arch list: ['sm_50', 'sm_60', ..., 'sm_120']  ← sm_120 在列表中就对了
GPU: NVIDIA GeForce RTX 5090D
CUDA matmul test: PASSED (torch.Size([1000, 1000]))
```

> 📌 **关键检查点**: `sm_120` 必须在 arch list 中，否则 PyTorch 版本错了。

### 3. 克隆 GPT-SoVITS

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS

# ⚠️ 50系用户注意：如果有 nvidia50 专用整合包（如 GPT-SoVITS-v2pro-20250604-nvidia50），优先使用
# 否则后续可能出现 ZeroDivisionError 等问题
```

### 4. 安装依赖

⚠️ **重要**：安装前先修改 requirements.txt，移除 torch 版本锁定：

```bash
# 先解除 torch 版本锁定，避免 pip 降级 torch
sed -i '/^torch==/d' requirements.txt
sed -i '/^torchvision==/d' requirements.txt
sed -i '/^torchaudio==/d' requirements.txt

# 安装依赖
pip install -r requirements.txt
pip install -r extra-req.txt --no-deps

# 安装 triton-windows（Windows 下需要）
pip install triton-windows

# ⚠️ 不要安装 xformers！它会强制降级 PyTorch，破坏 sm_120 支持
```

#### ONNX Runtime 兼容性

如果遇到以下错误：
```
[ONNXRuntimeError] Slice_12: CUDA error cudaErrorNoKernelImageForDevice
```

这是 `onnxruntime-gpu 1.23.x` 与 Blackwell 的兼容问题。解决方案：

```bash
# 方案 A: 降级到 1.22.0（已验证可用）
pip install onnxruntime-gpu==1.22.0

# 方案 B: 升级到 1.23.2+（官方已修复）
pip install onnxruntime-gpu>=1.23.2
```

### 5. 应用代码补丁

#### Patch 1: Tuple 类型注解

**文件:** `GPT_SoVITS/AR/modules/patched_mha_with_cache.py`

在文件**第一行**添加：
```python
from typing import Tuple
```

> **为什么？** PyTorch 2.7+ 移除了某些旧版类型注解的隐式导入，导致 `Tuple` 名称未定义。

#### Patch 2: `add_safe_globals` + `weights_only=False`

**文件:** `GPT_SoVITS/inference_webui.py`

在文件开头 imports 区域添加：
```python
from torch.serialization import add_safe_globals
from utils import HParams
add_safe_globals([HParams])
```

修改 `torch.load()` 调用：
```python
# 修改前
dict_s2 = torch.load(sovits_path, map_location="cuda")

# 修改后
dict_s2 = torch.load(sovits_path, map_location="cuda", weights_only=False)
```

**文件:** `GPT_SoVITS/TTS_infer_pack/TTS.py`

同样添加 add_safe_globals 和 weights_only=False：
```python
from torch.serialization import add_safe_globals
from utils import HParams
add_safe_globals([HParams])

# 在 init_vits_weights 方法中
dict_s2 = torch.load(weights_path, map_location=self.configs.device, weights_only=False)
```

> **为什么？** PyTorch 2.6+ 将 `weights_only` 默认值从 `False` 改为 `True`，不设置会导致模型加载失败。

#### Patch 3: 所有 `torch.load()` 调用（批量）

快捷方式（在 GPT-SoVITS 根目录执行）：
```bash
grep -rl "torch\.load" --include="*.py" . | xargs sed -i 's/torch\.load(\(.*\)weights_only=[A-Za-z]*\(.*\))/torch.load(\1weights_only=False\2)/g'
grep -rl "torch\.load" --include="*.py" . | xargs sed -i 's/torch\.load(\([^,)]*\)\(,*\)$/torch.load(\1, weights_only=False)/g'
```

### 6. 下载预训练模型

```bash
# 创建模型目录
mkdir -p GPT_SoVITS/pretrained_models/gsv-v2final-pretrained

# 从 HuggingFace 下载
pip install huggingface-hub
huggingface-cli download RVC-Boss/GPT-SoVITS-pretrained-models --local-dir GPT_SoVITS/pretrained_models/ --include "gsv-v2final-pretrained/*"
```

### 7. 配置 api_v2.py

创建或编辑 `GPT_SoVITS/configs/tts_infer.yaml`：

```yaml
custom:
  device: cuda
  is_half: true
  version: v2
  t2s_weights_path: GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt
  vits_weights_path: GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth
```

### 8. 启动 GPT-SoVITS API 服务

```bash
conda activate gpt-sovits
cd ~/GPT-SoVITS
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

应看到 uvicorn 启动，监听 `http://127.0.0.1:9880`，无 CUDA 错误。

### 9. 测试 TTS 服务

```bash
curl -X POST "http://127.0.0.1:9880/tts" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好，我是你的AI助手。",
    "text_lang": "zh",
    "ref_audio_path": "/home/yourname/voice/my_reference.wav",
    "prompt_text": "这是参考音频的文字内容。",
    "prompt_lang": "zh",
    "media_type": "wav",
    "streaming_mode": 0
  }' \
  --output test_output.wav
```

如果能生成 `test_output.wav` 并正常播放，说明 GPT-SoVITS 部署成功！

---

## 方案二：原生 Windows

如果你不想用 WSL2，可以直接在 Windows 上安装。截至 2026 年 5 月，cu128 稳定版在 Windows 上的兼容性已经很好。

### 步骤

```powershell
# 1. 安装 Visual Studio 2017+ Build Tools（需要 C++ 编译器和 CUDA 12.8）
#    从 https://developer.nvidia.com/cuda-12-8-0-download-archive 下载 CUDA 12.8

# 2. 创建干净环境
python -m venv gptsovits_5090
.\gptsovits_5090\Scripts\Activate.ps1
pip install --upgrade pip wheel setuptools

# 3. 安装 PyTorch cu128（必须最先安装）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# 4. 安装 triton-windows
pip install triton-windows

# 5. 克隆并修改 requirements.txt 解除 torch 版本锁定
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
# 手动编辑 requirements.txt，删除 torch==, torchvision==, torchaudio== 行

# 6. 安装其余依赖
pip install -r requirements.txt
pip install -r extra-req.txt --no-deps

# 7. 应用代码补丁（同方案一第 5 节）
# 8. 下载模型（同方案一第 6 节）
# 9. 启动 api_v2.py
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

### 已知问题 & 解决

| 问题 | 原因 | 解决 |
|------|------|------|
| `torio` FFmpeg 扩展加载失败 | PyTorch nightly 的 torchaudio 缺少 FFmpeg DLL | 使用 cu128 **稳定版**而非 nightly |
| `xformers` 强制降级 PyTorch | xformers 依赖旧版 PyTorch | **不要安装 xformers** |
| ONNX Runtime `Slice_12` 错误 | onnxruntime-gpu 1.23.x 不兼容 Blackwell | `pip install onnxruntime-gpu==1.22.0` |
| `ZeroDivisionError` 训练失败 | 使用了非 nvidia50 整合包 | 使用 `GPT-SoVITS-v2pro-*-nvidia50` 整合包 |

---

## 环境变量（如需编译 CUDA 扩展）

```powershell
# 如果从源码编译 CUDA 扩展，需要指定 sm_120：
set TORCH_CUDA_ARCH_LIST=8.6;9.0;12.0    # Windows CMD
$env:TORCH_CUDA_ARCH_LIST="8.6;9.0;12.0"  # PowerShell
export TORCH_CUDA_ARCH_LIST="8.6;9.0;12.0"  # WSL2/Linux
```

---

## 配置 Anima 连接

在 GPT-SoVITS 服务正常运行后，配置 Anima 使用它：

### 修改 `config/animetta.yaml`

```yaml
providers:
  tts:
    gpt-sovits:
      type: gpt_sovits
      base_url: "http://127.0.0.1:9880"
      ref_audio_path: "/home/yourname/voice/my_reference.wav"
      prompt_text: "这是参考音频的文字内容"
      prompt_lang: "zh"
      text_lang: "zh"
profiles:
  smoke:
    services:
      tts: gpt-sovits
```

### 启动 Anima

```bash
ANIMETTA_PROFILE=smoke python -m animetta.core.socketio_server
```

查看日志确认 TTS 初始化成功：
```
[ServiceContext] Initializing TTS: gpt_sovits/default
GPT-SoVITS HTTP client initialized (base_url=http://127.0.0.1:9880)
```

---

## 验证清单

- [ ] WSL2/Windows + NVIDIA 驱动 ≥ 565.90
- [ ] `nvidia-smi` 显示 CUDA 12.8 + 5090D
- [ ] `torch.cuda.is_available()` = True，arch list 包含 `sm_120`
- [ ] 已解除 requirements.txt 中 torch 版本锁定
- [ ] `patched_mha_with_cache.py` Tuple 补丁已应用
- [ ] 所有 `torch.load()` 已添加 `weights_only=False`
- [ ] `onnxruntime-gpu` 版本正确（1.22.0 或 ≥1.23.2）
- [ ] 未安装 xformers
- [ ] 预训练模型已下载
- [ ] `api_v2.py` 成功启动，无 CUDA 错误
- [ ] curl 测试可生成有效 wav 文件
- [ ] Anima 配置正确，日志无报错

---

## 常见错误速查

| 错误信息 | 根因 | 修复 |
|---------|------|------|
| `sm_120 is not compatible with the current PyTorch installation` | 使用了 cu124 或更旧的 PyTorch | `pip install torch ... --index-url https://download.pytorch.org/whl/cu128` |
| `FATAL: this function is for sm80, but was built for sm370` | 预编译 CUDA 扩展版本不匹配 | 安装 cu128 PyTorch，使用 nvidia50 整合包 |
| `no kernel image is available for execution on the device` | GPU 执行了未为 sm_120 编译的 kernel | 同上 — cu128 PyTorch |
| `Slice_12: CUDA error cudaErrorNoKernelImageForDevice` | onnxruntime-gpu 不兼容 | `pip install onnxruntime-gpu==1.22.0` |
| `ZeroDivisionError` 训练失败 | 非 nvidia50 整合包 | 使用 `GPT-SoVITS-v2pro-*-nvidia50` |
| `ImportError: cannot import name 'add_safe_globals'` | PyTorch 太旧 (<2.4) | 安装 cu128 PyTorch (≥2.7) |

---

## 参考链接

- [GPT-SoVITS Issue #2026 — WSL2 方案](https://github.com/RVC-Boss/GPT-SoVITS/issues/2026)
- [GPT-SoVITS Issue #2192 — CUDA 12.8 sm_120 兼容性](https://github.com/RVC-Boss/GPT-SoVITS/issues/2192)
- [GPT-SoVITS Issue #2514 — no kernel image 解决](https://github.com/RVC-Boss/GPT-SoVITS/issues/2514)
- [PyTorch cu128 安装指南](https://pytorch.org/get-started/locally/)
