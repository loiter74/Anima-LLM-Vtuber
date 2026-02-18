# Anima 启动脚本

本目录包含用于启动 Anima 项目的脚本文件。

## 脚本列表

| 脚本 | 平台 | 说明 |
|------|------|------|
| `start.bat` | Windows CMD | Windows 批处理脚本 |
| `start.ps1` | Windows PowerShell | PowerShell 脚本（推荐） |
| `start.sh` | Linux/macOS | Bash 脚本 |

## 使用方法

### Windows

**方式一：双击运行**
- 直接双击 `start.bat` 文件

**方式二：命令行运行**
```cmd
# CMD
scripts\start.bat

# PowerShell
.\scripts\start.ps1
```

### Linux/macOS

```bash
# 添加执行权限（首次需要）
chmod +x scripts/start.sh

# 运行
./scripts/start.sh
```

## 命令行选项

所有脚本支持以下选项：

| 选项 | 说明 |
|------|------|
| `--skip-backend` | 跳过后端启动 |
| `--skip-frontend` | 跳过前端启动 |
| `--install` | 重新安装依赖 |
| `-h, --help` | 显示帮助信息 |

### 示例

```cmd
# Windows CMD
scripts\start.bat --skip-frontend
scripts\start.bat --install

# Windows PowerShell
.\scripts\start.ps1 -SkipFrontend
.\scripts\start.ps1 -Install

# Linux/macOS
./scripts/start.sh --skip-frontend
./scripts/start.sh --install
```

## 服务地址

启动成功后：

- **后端服务**: http://localhost:12394
- **前端服务**: http://localhost:3000

## 注意事项

1. 确保已安装 Python 3.8+ 和 Node.js 18+
2. 首次运行建议使用 `--install` 选项安装依赖
3. Windows 用户推荐使用 PowerShell 脚本 (`start.ps1`)
4. 服务在独立的终端窗口中运行，关闭窗口即可停止服务