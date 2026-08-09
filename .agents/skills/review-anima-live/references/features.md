# 评审功能选择

| 需求 | feature | 重点证据 |
|---|---|---|
| 直播页面与弹幕布局 | `live` | 状态、弹幕、布局、控制台、截图 |
| Live2D 性能和稳定性 | `live2d-performance` | 帧率、边界、动作、资源与控制台 |
| TTS 主备切换 | `tts-failover` | 音频、通知、状态转换、布局与日志 |
| Minecraft 直播展示 | `minecraft-gameplay` | 游戏画面、任务状态、OBS 与日志 |

规范入口：

```powershell
pnpm -C frontend run review -- --feature <id>
```

需要人工通过、调整或重做时增加 `--interactive`；只显示浏览器而不等待人工门禁时增加 `--headed`。稳定轮次不要增加 `--no-obs`。
