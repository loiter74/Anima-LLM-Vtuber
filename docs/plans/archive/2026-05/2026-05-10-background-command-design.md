# Agent 阻塞命令后台执行约定

**日期**: 2026-05-10
**状态**: 已批准

## 问题

当 agent 执行持久命令（服务器启动、bot 运行、watch 循环），bash 工具在命令结束前不会返回，导致 OpenCode 页面卡住，用户无法继续交互。

## 解决方案

**核心原则**: 必须通过原生 `cmd.exe` 调用 `start`，不能在 Git Bash 里用 `start`。

### 工作命令模板（已验证生效）

```bash
powershell -Command "Start-Process -FilePath 'C:/path/to/python.exe' -ArgumentList 'script.py' -WorkingDirectory 'C:/project/root'"
```

**为什么这是最终解**：
- `Start-Process` 是 Windows 原生进程分离，真正 fire-and-forget
- 不经过 Git Bash 的任何 shell 机制
- 新进程完全独立，不受 OpenCode bash 工具生命周期影响
- 秒回，零阻塞

### Step-by-step 3 步法

**Step 1**: 确认命令能在终端正常跑

**Step 2**: 用 `Start-Process` 启动（秒回，不阻塞）

```bash
powershell -Command "Start-Process -FilePath 'C:/Users/30262/miniconda3/python.exe' -ArgumentList 'scripts/start_mc_bot.py' -WorkingDirectory 'C:/Users/30262/Project/Anima'"
```

**Step 3**: 随时看日志

```bash
tail logs/mc_bot2.log
```

### 如果需要设置环境变量

```bash
powershell -Command "$env:PYTHONPATH='src'; Start-Process -FilePath 'C:/Users/30262/miniconda3/python.exe' -ArgumentList 'scripts/start_mc_bot.py' -WorkingDirectory 'C:/Users/30262/Project/Anima'"

### 日志约定

- 所有日志写入项目根目录 `logs/` 下
- 文件名：`<service-name>.log`
- 查看方式：`read("logs/<service-name>.log")`

### 停止服务

```cmd
# 关指定窗口（通过标题）
taskkill /FI "WINDOWTITLE eq <窗口标题>"

# 或直接杀进程
taskkill /F /IM <进程名>.exe
```

### 检查状态

```cmd
# 端口检查
netstat -ano | grep <端口号>

# 日志检查
tail logs/<服务名>.log
```

## 适用范围

- MC 服务器启动
- Anima 后端启动
- Minecraft Bot 启动
- 前端 dev server
- 任何会持续运行的进程

## 示例

```cmd
# 启动 MC Bot
start "MinecraftBot" cmd /k "cd /d C:\Users\30262\Project\Anima && set PYTHONPATH=src && python scripts/start_mc_bot.py > logs/mc_bot.log 2>&1"

# 启动 Anima 后端
start "AnimaBackend" cmd /k "cd /d C:\Users\30262\Project\Anima && set PYTHONPATH=src && python -m anima.core.socketio_server > logs/anima.log 2>&1"
```
