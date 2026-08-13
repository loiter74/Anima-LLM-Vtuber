# 场景目录

所有身份和消息均为合成数据。同一个场景与 seed 生成逐字节一致的 JSONL；不同 seed 会稳定更换昵称和同义消息。

| 场景 | 事件 | 用途 |
|---|---:|---|
| `daily` | 7 | 默认日常聊天：入场、问候、追问、点赞、话题互动与关注 |
| `quiet` | 5 | 冷场与长间隔：验证等待后的回复、页面状态与节奏 |
| `crowd` | 10 | 短时高峰：连续弹幕、点赞与关注；会产生多次真实 Provider 调用 |
| `support` | 7 | 支持互动：普通弹幕、礼物与醒目留言文本、点赞及后续追问 |

事件时间为相对 `offset_ms`。重放链路会等待每个可回复事件完成后再处理下一条，因此 LLM/TTS 延迟可能让实际总耗时长于时间轴；`crowd` 用于链路积压和恢复观察，不代表精准并发压测。

## 选择建议

- 不清楚选什么：`daily`。
- 调试长时间无输入后的状态恢复：`quiet`。
- 调试短时间多条消息的队列、页面滚动或错误恢复：`crowd`。
- 调试礼物、醒目留言文本的主播回应：`support`。当前重放会把页面原始消息归一成普通弹幕，不用于验收礼物或醒目留言的 UI 标记。
- 只验证输入：先 `render` 并检查 JSONL，不调用运行时。
- 验证真实页面和声音：先连接 `/live.html`，再 `start --wait`，并按直播评审 Skill 取新鲜证据。

## JSONL 契约

每行至少包含：

```json
{"offset_ms":0,"event_type":"danmaku","actor_id":"合成观众","text":"晚上好，今天准备聊什么？","payload":{"user_id":10001}}
```

支持的 `event_type` 为 `danmaku`、`gift`、`super_chat`、`enter`、`follow`、`like_batch`、`popularity_snapshot`、`connection_state`、`unknown`。时间轴必须非负且单调。只有 `danmaku`、`gift`、`super_chat` 进入 AI 回复链路。
