---
name: operate-anima-runtime
description: 安全操作和验收 Animetta 运行时、宿主机 Qwen TTS、宿主机 RVC 与 Docker Compose 生命周期，只负责服务启动、停止、恢复和健康状态，不负责选择或打开直播页面。用户要求启动、停止、重启、查看状态、冒烟运行、健康检查、发布门禁或排查运行时失败时使用。
---

# 操作 Animetta 运行时

只编排仓库的规范生命周期入口，不重新实现进程、租约、轮询或证据逻辑。

## 流程

1. 读取根 `AGENTS.md` 的当前 Docker 启动协议，并确认用户确实要求运行、启动或发布。
2. Windows 首次运行前断言 Python 3.13。
3. 只读状态可直接查询；任何会改变服务状态的操作必须交给唯一专用子智能体。
4. 按 [commands.md](references/commands.md) 使用 `scripts/runtime_lifecycle.py` 的现有动作。
5. 命令返回 `status=in_progress` 时，从输出读取 `run_id`，以相同 profile 和相同 run ID 续跑；不得创建第二个 run。
6. 任一步终态失败立即停止，保留宿主机 Qwen 与 RVC，并报告失败证据和最小恢复动作。
7. 只有协议全部通过后才报告运行时健康结论。
8. 请求还包含打开或显示直播页面时，运行时 ready 后把页面解析与打开交给 `$review-anima-live`；组合顺序固定为运行时就绪、用户要求的 Anima 后台动作、直播页面交接。

## 生产验收收敛

只有明确要求 production 发布、恢复或持久化验收时执行以下顺序：

1. 先用目标测试和最小能力探针消除已知风险，再冻结待部署差异；冻结前不得运行 affected、full 或正式生命周期。
2. Redis 或外部镜像能力异常时，先复现 Compose 的实际启动命令并检查官方 entrypoint；替换镜像或自建镜像前，必须验证 `FT.CREATE`、`JSON.SET` 和官方 `AsyncRedisSaver` 初始化。不得从 `PING` 或绕过 entrypoint 的容器推断模块缺失。
3. 在 affected 前覆盖正式入口的静态代理契约，至少包含 `/health`、`/ready`、`/metrics`、`/api/**` 和 Socket.IO，避免只验证直连后端。
4. 差异冻结后只运行一次 affected 门禁；通过后才执行一次 production 生命周期和一次 interrupt → restart → `Command(resume=...)` 恢复验收。
5. production 发现源码或配置缺陷时立即终止本轮验收；修复后重新冻结、运行相关目标测试和一次新的 affected，再使用新的生命周期 run ID。不得在代码继续变化时并行验收旧镜像。
6. 临时 token 与密码必须在承载整个续跑和验收的同一子进程中生成并保留；禁止输出完整环境、`Config.Env`、密钥值或含密钥的 URL，只查询白名单状态字段。
7. 从隔离 Git 工作树部署时，`COMPOSE_ENV_FILES` 只负责 Compose 插值，不能代替生命周期前置宿主步骤所需的进程环境。启动前在同一专用子进程中安全导入 `QWEN_TTS_API_KEY`、`ANIMETTA_REDIS_PASSWORD`、`ANIMETTA_ACCESS_TOKEN` 等必需值，并先运行不回显配置的 `docker compose config --quiet`；缺值时一次性停止，不得逐项失败后重试。

## 约束

- 不在主智能体中启动后端或 Compose。
- 不把进程退出、容器 `Up` 或端口监听当成 HTTP 就绪。
- 不直接调用 `docker compose` 绕过生命周期脚本。
- 不恢复 Qwen 或 RVC 容器；宿主服务只允许各自的 `host-tts-stop`、`host-rvc-stop` 释放。
- 不因代码修改自动启动 Docker；只有显式运行需求或相应高风险边界才触发。
- 不自动重试终态失败，也不同时运行多个生命周期智能体。
- 不读取 Vue Router、选择直播 URL、启动浏览器或配置 OBS。

## 报告

报告动作、run ID、终态、HTTP 就绪、TTS/RVC 模型身份、日志检查和证据路径。未完成完整协议时不得输出 `[OK]` 固定结论。
