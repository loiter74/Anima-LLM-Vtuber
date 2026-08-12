---
name: verify-anima-surfaces
description: 验收 Animetta 唯一两个正式产品入口 /live.html 与 /dashboard 的真实运行功能、Provider 身份、私密/公开链路隔离和关键交互。用户要求检查两个页面、排查 mock Provider、确认直播播放或系统性回归后台功能时使用。
---

# 验收 Animetta 双页面

只用新鲜证据判断两个正式入口是否可用，不用单测、Vite 预览或容器存活替代真实 URL 验收。

## 流程

1. 读取根目录与 `frontend/AGENTS.md`，确认目标 URL；未指定时使用 `http://localhost/live.html` 和 `http://localhost/dashboard`。
2. 使用 `$operate-anima-runtime` 检查或启动运行时；改变状态时交给唯一专用子智能体，不直接调用 Docker Compose。
3. 请求 `/ready` 并执行强制门禁：
   - `profile` 必须是用户要求的 Profile；正式本地使用默认为 `production`。
   - LLM `configured` 与 `resolved` 均不得是 `mock`；若为 mock，停止功能验收，先修复 Profile 并重启。
   - TTS、ASR、VAD 的 mock 是否允许由目标场景决定；真实直播音频验收禁止 mock TTS。
   - 对声明为启用的模型工具核对其运行时依赖；需要外部 Token 或 CLI 的工具在两者都不存在时不得注册给 LLM。浏览器正常回复不能抵消工具执行错误。
4. 按 [matrix.md](references/matrix.md) 选择最小功能集；页面交互使用 `$qa-testing-playwright`，直播页面证据使用 `$review-anima-live`。
5. 后台对话必须分别验证：
   - “现场”开发者输入产生 `actor_role=developer` 的真实回合，执行检查器显示非 mock LLM Provider。
   - “验证 / 对话沙盒”返回 `chat:sandbox_chunk`，显示非 mock Provider；同一 task 不得产生公开字幕、TTS 播放或记忆提交。
6. `/live.html` 公开回复必须验证字幕 DOM 与 TTS 持久播放证据；Socket 收到句子或服务端合成成功均不算播放通过。
7. 完成交互后重新检查当前时段的服务端 `ERROR` / Traceback；区分预期降级与能力声明错误，后者必须修复或明确列为失败。
8. 每个失败都记录入口、动作、期望、实际与证据路径；不要以其他模块通过抵消失败。

## 边界

- 自动测试负责路由、事件 Schema、功能归属和隔离调用契约；本 Skill 负责真实 Provider、浏览器、音频与运行时证据。
- 不把 Dashboard 私密沙盒接入 LangGraph、公开字幕、TTS 或记忆写入。
- 不修改 `text-boundaries`、`sparse` 场景名称、消息或精确断言。
- 不因某个外部依赖不可用而改用 mock 后宣称正式功能通过。

## 报告

报告 Profile 与 Provider、两个实际 URL、执行的矩阵项、关键断言、失败项和证据目录。明确区分自动契约测试、浏览器诊断与真实运行验收。
