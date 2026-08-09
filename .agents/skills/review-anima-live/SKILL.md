---
name: review-anima-live
description: 评审 Animetta 直播页面、Live2D 性能、TTS 故障转移和 OBS 呈现，并采集新鲜浏览器与运行证据。用户要求检查直播界面、视觉回归、OBS 场景、Live2D 表现、音频故障转移或真实 Bilibili 直播数据时使用。
---

# 评审 Animetta 直播

复用统一 review CLI 和通用 Playwright 规则，保持直播评审证据可重复。

## 流程

1. 读取 `frontend/AGENTS.md`，并在需要浏览器证据时加载 `$qa-testing-playwright`。
2. 按 [features.md](references/features.md) 选择唯一 review feature；不要为同一场景启动重复浏览器。
3. 使用 `pnpm -C frontend run review -- --feature <id>` 采集当前页面、控制台、请求、截图和摘要。
4. 稳定评审需要 OBS 时使用专用场景和 Browser Source；`--no-obs` 只能用于浏览器诊断。
5. 使用真实 Bilibili 数据时调用项目 Bilibili MCP 控制现有会话，不直接启动 `DanmakuService` 或第二条网关连接。
6. 只根据本轮新证据判断通过、调整或重做。

## 不变量

- 保留 `text-boundaries` 与 `sparse` 的名称、消息、弹幕文案和精确断言；只能新增场景，不得替换这些固定夹具。
- 不复用旧截图、旧控制台或旧健康证据。
- 不把页面加载成功当成视觉、音频或 Live2D 行为通过。
- 不通过修改评审夹具来掩盖产品回归。
- 真实直播事件可能包含未脱敏身份；只在当前评审需要时读取，不另行持久化。

## 报告

报告 feature、运行模式、页面与 OBS 来源、关键断言、证据路径和失败点。明确区分浏览器诊断结果与稳定评审结果。
