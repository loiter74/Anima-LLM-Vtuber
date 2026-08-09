---
name: operate-anima-runtime
description: 安全操作和验收 Animetta 运行时、宿主机 Qwen TTS 与 Docker Compose 生命周期，只负责服务启动、停止、恢复和健康状态，不负责选择或打开直播页面。用户要求启动、停止、重启、查看状态、冒烟运行、健康检查、发布门禁或排查运行时失败时使用。
---

# 操作 Animetta 运行时

只编排仓库的规范生命周期入口，不重新实现进程、租约、轮询或证据逻辑。

## 流程

1. 读取根 `AGENTS.md` 的当前 Docker 启动协议，并确认用户确实要求运行、启动或发布。
2. Windows 首次运行前断言 Python 3.13。
3. 只读状态可直接查询；任何会改变服务状态的操作必须交给唯一专用子智能体。
4. 按 [commands.md](references/commands.md) 使用 `scripts/runtime_lifecycle.py` 的现有动作。
5. 命令返回 `status=in_progress` 时，从输出读取 `run_id`，以相同 profile 和相同 run ID 续跑；不得创建第二个 run。
6. 任一步终态失败立即停止，保留宿主机 Qwen，并报告失败证据和最小恢复动作。
7. 只有协议全部通过后才报告运行时健康结论。
8. 请求还包含打开或显示直播页面时，运行时 ready 后把页面解析与打开交给 `$review-anima-live`；组合顺序固定为运行时就绪、用户要求的 Anima 后台动作、直播页面交接。

## 约束

- 不在主智能体中启动后端或 Compose。
- 不把进程退出、容器 `Up` 或端口监听当成 HTTP 就绪。
- 不直接调用 `docker compose` 绕过生命周期脚本。
- 不恢复 Qwen 容器；宿主服务只允许 `host-tts-stop` 释放。
- 不因代码修改自动启动 Docker；只有显式运行需求或相应高风险边界才触发。
- 不自动重试终态失败，也不同时运行多个生命周期智能体。
- 不读取 Vue Router、选择直播 URL、启动浏览器或配置 OBS。

## 报告

报告动作、run ID、终态、HTTP 就绪、模型身份、日志检查和证据路径。未完成完整协议时不得输出 `[OK]` 固定结论。
