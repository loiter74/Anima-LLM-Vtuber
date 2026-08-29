# 运行时入口

所有 Windows 命令使用 `py -3.13`。

| 需求 | 动作 |
|---|---|
| 启动或确认宿主 TTS | `scripts/runtime_lifecycle.py host-tts-up` |
| 查询宿主 TTS | `scripts/runtime_lifecycle.py host-tts-status` |
| 启动或确认宿主 RVC | `scripts/runtime_lifecycle.py host-rvc-up` |
| 查询宿主 RVC | `scripts/runtime_lifecycle.py host-rvc-status` |
| 停止 Animetta，保留宿主 TTS 与 RVC | `scripts/runtime_lifecycle.py anima-down` |
| 从当前源码构建并启动 Animetta | `scripts/runtime_lifecycle.py anima-up` |
| 拉取并启动流水线验证镜像 | `scripts/runtime_lifecycle.py anima-deploy --image <GHCR镜像>` |
| 完整停止宿主 TTS | `scripts/runtime_lifecycle.py host-tts-stop` |
| 完整停止宿主 RVC | `scripts/runtime_lifecycle.py host-rvc-stop` |

冒烟启动在当前 PowerShell 进程设置 `ANIMETTA_PROFILE=smoke`。若 `anima-up` 返回进行中，复用输出中的 run ID：

```powershell
py -3.13 scripts/runtime_lifecycle.py --run-id <run-id> anima-up
```

不得手写循环替代生命周期脚本。最终验收仍以根 `AGENTS.md` 当前协议声明的健康页、前端、日志和宿主模型身份为准。

`anima-deploy` 只接受 `ghcr.io/loiter74/animetta` 的 `main`、完整 commit SHA
标签或 `sha256` digest。私有包必须先用具备 `read:packages` 权限的凭据执行
`docker login ghcr.io`；Skill 不读取或保存该凭据。
