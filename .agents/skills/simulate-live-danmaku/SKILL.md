---
name: simulate-live-danmaku
description: 在 Animetta 正式运行时与 /live.html 中生成并重放可复现的合成直播弹幕，覆盖日常聊天、冷场、弹幕高峰、礼物与醒目留言文本等真实场景，并通过现有节目重放 API 驱动 Bilibili、LLM、TTS 和 Socket.IO 链路。用户要求使用弹幕姬、模拟观众、压测弹幕、复现直播互动、调试主播回复或日常验收直播链路时使用。
---

# 弹幕姬

通过仓库已有的节目重放 API 注入合成观众事件，不连接真实直播间，不直接伪造服务端输出事件。

## 流程

1. 明确验收层级：
   - 只需要样本或复现输入：执行 `render`，不启动运行时。
   - 需要后端回复链路：在当前正式实例执行 `start --wait`。
   - 需要页面、Live2D 或真实音频证据：先用 `$review-anima-live` 打开或评审 `live`，页面连接后再注入。
2. 读取 [scenarios.md](references/scenarios.md)，选择覆盖目标的最小场景；未指定时用 `daily`、`--seed 20260813`、`--speed 1`。
3. 用户要求实际执行而运行时不可用时，使用 `$operate-anima-runtime` 启动并等待 ready；只要求生成或计划时不得启动服务。
4. 从仓库根目录运行：

   ```powershell
   $env:PYTHONUTF8 = '1'
   py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py list
   py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py render daily --seed 20260813
   py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py start daily --base-url http://127.0.0.1 --room-id 1 --seed 20260813 --speed 1 --wait
   ```

5. 根据目标收集证据：
   - 后端：最终 `state=completed`、`cursor=total_events`、`error=null`。
   - 页面弹幕：本轮合成昵称与消息确实出现在 `/live.html`，且控制台没有链路错误。
   - TTS：按 `$review-anima-live` 的持久播放证据验收播放计数、最后 `task_id` 和最终播放状态；不得以重放完成、合成成功或收到 socket 事件代替真实播放证据。
6. 若中途失败或用户取消，只停止本 Skill 创建的 `replay_id`；报告场景、seed、room、速度、游标、失败事件与最短复现命令。

## 控制运行

使用启动结果中的 `replay_id`；同一运行保持默认 Creator，除非启动时显式改过：

```powershell
py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py status <replay_id> --base-url http://127.0.0.1
py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py control <replay_id> pause --base-url http://127.0.0.1
py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py control <replay_id> resume --base-url http://127.0.0.1
py -3.13 .agents/skills/simulate-live-danmaku/scripts/danmaku_simulator.py control <replay_id> stop --base-url http://127.0.0.1
```

暂停后才能 `step`；`speed` 动作必须同时传 `--speed`。速度范围为 `(0, 100]`，它只缩放事件时间轴，LLM/TTS 处理时间仍可能拉长实际耗时。

## 边界

- 使用合成身份与合成文案；不要把真实观众身份复制进固定样本或持久化证据。
- 不调用 Bilibili MCP、不启动 `DanmakuService`、不连接或切换真实房间。
- API 返回 `room_input_active` 或 `replay_already_active` 时立即停止并报告；不得接管、断开或停止现有真实弹幕、节目或他人的重放。
- `crowd` 会触发多次真实 LLM/TTS 调用；日常诊断先用 `daily`，仅在确需高负载时使用 `crowd`。
- 重放上下文使用临时保留策略，但仍会调用当前实例配置的真实 Provider；报告 Provider 失败，不静默换成 mock。
- 不修改 `data/`、`evidence/`、`text-boundaries` 或 `sparse` 夹具。需要保存 JSONL 时只写用户明确指定的 `render --output` 路径。
- 只把 `danmaku`、`gift`、`super_chat` 视为可回复事件；`enter`、`follow`、`like_batch` 只验证直播事件传输。
- 当前节目重放会把 `gift` 与 `super_chat` 的文本送入真实回复链路，但页面原始消息会被归一成普通弹幕；不得用 `support` 验收礼物或醒目留言的 UI 标记。

## 报告

报告实例 URL、场景、seed、room、速度、事件数、最终游标和状态。分开说明后端重放、页面显示与真实音频播放各自是否经过验证；不要把未执行的层级写成通过。
