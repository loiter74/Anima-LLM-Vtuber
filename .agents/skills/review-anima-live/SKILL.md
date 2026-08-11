---
name: review-anima-live
description: 打开、显示或评审 Animetta 真实直播页面、OBS Browser Source、Live2D 性能、TTS 故障转移和真实 Bilibili 数据，并采集需要的新鲜证据。用户要求打开真实直播、显示 OBS 页面或场景、检查直播界面、视觉回归、Live2D 表现或音频故障转移时使用。
---

# 评审 Animetta 直播

复用统一 review CLI 声明的 feature 路由和通用 Playwright 规则，不从 Vue Router 推断直播入口。

## 模式

- **display**：用户只要求打开、显示或获取直播页面时，运行
  `pnpm --silent -C frontend run review -- --feature <id> --base-url <当前前端源> --print-url`，再用用户指定或当前浏览器打开其唯一输出。不得启动 OBS、评审浏览器或写评审证据。
- **review**：用户要求检查、截图、OBS、视觉、音频或性能证据时，执行下述完整评审流程。

## 流程

1. 读取 `frontend/AGENTS.md`，并按 [features.md](references/features.md) 选择唯一 feature。
2. 请求还包含启动、停止或恢复 Animetta 时，先使用 `$operate-anima-runtime`；等待运行时 ready，完成用户要求的 Anima 后台动作，再进入 display 或 review 模式。
3. display 模式只解析并打开 CLI 返回的 URL；不得读取前端路由器或使用兼容重定向入口。
4. review 模式在需要浏览器证据时加载 `$qa-testing-playwright`。
5. 使用 `pnpm -C frontend run review -- --feature <id>` 采集当前页面、控制台、请求、截图和摘要；不要为同一场景启动重复浏览器。
6. 修改背景、层级、缩放或位置时，进入最终门禁和运行时部署前先用 `--no-obs` 做一次目标视口浏览器诊断；同一份新证据必须同时确认背景资源已加载、Live2D 关键区域不被面板覆盖、弹幕标题与正文不被模型覆盖。任一方向失败都留在本地修正，不得先部署再补另一方向。
7. 稳定评审需要 OBS 时使用专用场景和 Browser Source；`--no-obs` 只能用于浏览器诊断。
8. 使用真实 Bilibili 数据时调用项目 Bilibili MCP 控制现有会话，不直接启动 `DanmakuService` 或第二条网关连接。
9. 只根据本轮新证据判断通过、调整或重做。
10. 验收真实 TTS 播放时，不等待“声音播放中”等瞬时文案。触发前记录
    `#audioStatus[data-playback-count]`，触发后断言计数递增、
    `data-last-audio-task-id` 等于本轮 `task_id`，且最终
    `data-playback-state` 为 `playing` 或 `completed`；同时检查控制台没有播放失败。

## 不变量

- 保留 `text-boundaries` 与 `sparse` 的名称、消息、弹幕文案和精确断言；只能新增场景，不得替换这些固定夹具。
- 不复用旧截图、旧控制台或旧健康证据。
- 不把页面加载成功当成视觉、音频或 Live2D 行为通过。
- 不通过修改评审夹具来掩盖产品回归。
- 真实直播事件可能包含未脱敏身份；只在当前评审需要时读取，不另行持久化。

## 报告

报告 feature、运行模式、页面与 OBS 来源、关键断言、证据路径和失败点。明确区分浏览器诊断结果与稳定评审结果。
