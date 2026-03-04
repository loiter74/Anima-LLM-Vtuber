# 🚀 WSL Ubuntu + PyTorch (sm_120) 完整安装指南

## 📋 当前状态

- ✅ WSL2 已安装
- ✅ Ubuntu 发行版正在运行
- ⏳ 需要完成首次设置和安装 PyTorch

## 🔧 完整安装步骤 (请按顺序手动执行)

### 第 1 步：完成 WSL Ubuntu 首次设置

打开 **Windows Terminal** 或 **PowerShell**，运行：

```bash
wsl -d Ubuntu
```

首次运行会提示你创建 UNIX 用户：

```
Installing, this may take a few minutes...
Please create a default UNIX user account. The username does not need to match your Windows username.
For more information visit: https://aka.ms/wslusers
Enter new UNIX username: anima
Enter new UNIX password: [输入密码]
Retype new UNIX password: [再次输入密码]
```

**建议配置**：
- 用户名：`anima` (或任意小写名称)
- 密码：设置一个简单密码（仅本地使用）

### 第 2 步：更新系统

仍在 WSL Ubuntu 中，运行：

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 第 3 步：安装 Python 和工具

```bash
sudo apt-get install -y python3 python3-pip python3-venv git curl wget
```

验证安装：
```bash
python3 --version
pip3 --version
```

### 第 4 步：进入项目目录

```bash
cd /mnt/c/Users/30262/Project/Anima
pwd
```

应该显示：`/mnt/c/Users/30262/Project/Anima`

### 第 5 步：创建 Python 虚拟环境

```bash
python3 -m venv venv_training_wsl
```

### 第 6 步：激活虚拟环境并安装 PyTorch

```bash
source venv_training_wsl/bin/activate
```

你会在命令提示符前看到 `(venv_training_wsl)`，表示虚拟环境已激活。

```bash
# 升级 pip
pip install --upgrade pip

# 安装 PyTorch nightly (支持 sm_120)
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu124
```

**注意**：这一步会下载约 2.5GB 的文件，可能需要 5-10 分钟。

### 第 7 步：验证 sm_120 支持

```bash
python3 << 'EOF'
import torch
print("=" * 60)
print("PyTorch Installation Verification")
print("=" * 60)
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"Compute capability: {torch.cuda.get_device_capability(0)}")
    print(f"Total memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    print(f"\nSupported architectures:")
    arch_list = torch.cuda.get_arch_list()
    for arch in arch_list:
        print(f"  - {arch}")

    if 'sm_120' in arch_list:
        print("\n✅ SUCCESS: sm_120 (RTX 5090 D) is SUPPORTED!")
    else:
        print("\n⚠️ WARNING: sm_120 not found")
        print("This might be because PyTorch nightly for Linux doesn't include sm_120 yet.")

print("=" * 60)
EOF
```

### 第 8 步：测试 GPU 操作

创建测试脚本：

```bash
cat > test_gpu.py << 'EOF'
import torch
print("Testing GPU operations...")

# Test 1: Basic tensor operations
print("\n[1/3] Testing basic tensor operations...")
x = torch.randn(100, 100, device='cuda')
y = torch.randn(100, 100, device='cuda')
z = torch.matmul(x, y)
print(f"✅ Matrix multiplication: {z.shape}")

# Test 2: Neural network
print("\n[2/3] Testing neural network...")
import torch.nn as nn
model = nn.Linear(100, 50).cuda()
input_tensor = torch.randn(10, 100, device='cuda')
output = model(input_tensor)
print(f"✅ Forward pass: {output.shape}")

# Test 3: Training step
print("\n[3/3] Testing training step...")
optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
loss_fn = nn.MSELoss()
target = torch.randn(10, 50, device='cuda')
optimizer.zero_grad()
loss = loss_fn(output, target)
loss.backward()
optimizer.step()
print(f"✅ Training step completed, loss: {loss.item():.4f}")

print("\n" + "=" * 60)
print("🎉 All GPU tests passed!")
print("=" * 60)
EOF
```

运行测试：

```bash
python test_gpu.py
```

## ✅ 成功标志

如果一切正常，你应该看到：

```
================================================================================
PyTorch Installation Verification
================================================================================
PyTorch version: 2.7.0.dev202503xx+cu124
CUDA available: True
GPU: NVIDIA GeForce RTX 5090 D
Compute capability: (12, 0)
Total memory: 23.9 GB

Supported architectures:
  - sm_50
  - sm_60
  - sm_70
  - sm_75
  - sm_80
  - sm_86
  - sm_90
  - sm_120  ← 这个很重要！

✅ SUCCESS: sm_120 (RTX 5090 D) is SUPPORTED!
================================================================================
```

## 🎯 安装完成后的使用方法

每次使用前，在 WSL Ubuntu 中激活环境：

```bash
wsl -d Ubuntu
cd /mnt/c/Users/30262/Project/Anima
source venv_training_wsl/bin/activate
```

然后就可以运行训练脚本了！

## 🔧 故障排除

### 问题 1: `wsl: command not found`

**解决**: WSL 没有安装或没有启用。运行：
```powershell
wsl --install
```

### 问题 2: Ubuntu 提示创建用户名后卡住

**解决**: 这是正常的首次设置流程，按照提示输入用户名和密码即可。

### 问题 3: `sm_120` 不在支持的架构列表中

**原因**: 即使是 Linux 版的 PyTorch nightly，也可能还没有包含 sm_120 支持。

**解决方案**:
1. 等待 PyTorch 官方发布支持 sm_120 的版本（2025年Q2-Q3）
2. 继续使用 CPU 训练（已经验证可用）
3. 尝试从源码编译 PyTorch（复杂）

### 问题 4: CUDA 不可用

**解决**:
1. 确保 Windows NVIDIA 驱动已安装
2. 在 Windows PowerShell 中运行 `nvidia-smi` 检查
3. 确保 WSL2 可以访问 GPU：`dxdiag` 检查 GPU

## 📊 预期时间表

| 步骤 | 预计时间 | 说明 |
|------|---------|------|
| WSL 首次设置 | 2-3 分钟 | 一次性操作 |
| 系统更新 | 2-5 分钟 | 取决于网速 |
| 安装工具 | 1-2 分钟 | Python, pip, git |
| 创建虚拟环境 | 10-20 秒 | 很快 |
| 安装 PyTorch | 5-15 分钟 | 下载 2.5GB |
| 验证测试 | 1-2 分钟 | 运行测试 |
| **总计** | **15-30 分钟** | 大部分时间在等待 |

## 🎉 完成后

安装完成后，你就可以在 WSL Ubuntu 中使用 RTX 5090 D 进行 GPU 训练了！

下一步可以运行训练脚本：
```bash
cd /mnt/c/Users/30262/Project/Anima
source venv_training_wsl/bin/activate
python scripts/training/train_with_gpu_rtx5090.py
```

---

## 💡 提示

1. **保存密码**: WSL Ubuntu 的密码只在你本地使用，可以设置简单的
2. **Windows 访问**: 可以从 Windows 资源管理器访问 `\\wsl$\Ubuntu\`
3. **复制粘贴**: 在 Windows Terminal 中可以直接复制粘贴命令
4. **退出 WSL**: 输入 `exit` 或按 Ctrl+D

祝安装顺利！🚀
