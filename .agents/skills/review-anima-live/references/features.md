# 评审功能选择

| 需求 | feature | 重点证据 |
|---|---|---|
| 打开、显示或获取真实直播页面 | `live` | 使用 `--print-url` 只解析 feature 路由 |
| 直播页面与弹幕布局 | `live` | 状态、弹幕、布局、控制台、截图 |
| 真实直播 TTS 播放 | `live` | 播放计数、最后 task_id、持久播放状态、控制台 |
| Live2D 性能和稳定性 | `live2d-performance` | 帧率、边界、动作、资源与控制台 |
| TTS 主备切换 | `tts-failover` | 音频、通知、状态转换、布局与日志 |
| Minecraft 直播展示 | `minecraft-gameplay` | 游戏画面、任务状态、OBS 与日志 |

规范入口：

```powershell
pnpm -C frontend run review -- --feature <id>
```

只解析页面地址时使用：

```powershell
pnpm --silent -C frontend run review -- --feature <id> --base-url <当前前端源> --print-url
```

该模式只输出 URL，不启动 Vite、浏览器、OBS 或评审证据写入。

需要人工通过、调整或重做时增加 `--interactive`；只显示浏览器而不等待人工门禁时增加 `--headed`。稳定轮次不要增加 `--no-obs`。
