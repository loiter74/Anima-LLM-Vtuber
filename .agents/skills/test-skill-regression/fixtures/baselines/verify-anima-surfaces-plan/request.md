# 固定请求

为两个正式入口生成最小验收计划，不执行验收。

将 `result/plan.md` 精确写成以下四行：

```text
入口: /live.html, /dashboard
门禁: profile=production, llm configured/resolved != mock
沙盒: non-mock chat:sandbox_chunk, no subtitle/TTS/memory
直播: subtitle DOM, audioStatus playback count/task_id
```
