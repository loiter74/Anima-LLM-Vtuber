# 固定请求

为默认弹幕姬日常模拟生成执行计划，但不要执行。

将 `result/plan.md` 精确写成以下六行：

```text
场景: daily
seed: 20260813
输入: 合成 JSONL
链路: program replay -> Bilibili -> LLM/TTS -> Socket.IO
真实房间: 不连接
证据: 后端、页面、播放分层报告
```
