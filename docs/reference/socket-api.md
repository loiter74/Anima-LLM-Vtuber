# Animetta Socket.IO API

本文是 Dashboard、`/live.html`、桌面客户端与 Animetta 后端之间的完整实时协议目录。默认命名空间为 `/`，Engine.IO 使用标准 `/socket.io` 路径。

事件名和字段 schema 的唯一真相源是 `config/socket-events.json`；后端通过 `animetta.orchestration.socket_events` 读取，前端通过 `frontend/src/constants/socket-events.ts` 的 `Events` 使用。

## 连接、认证与错误

Dashboard、桌面端和机器客户端在 `production` profile 可通过以下任一种方式认证：

```ts
io('/', { auth: { token: '<ANIMETTA_ACCESS_TOKEN>' } })
```

- Socket.IO `auth.token`；
- 握手的 `Authorization: Bearer ...`；
- HTTP 登录得到的 `animetta_session` Cookie。

`/live.html` 使用同一默认命名空间，但无需账号：

```ts
io('/', { auth: { surface: 'live' } })
```

该握手只有在 `Origin` 精确匹配 `security.allowed_origins` 时才建立 `public-live` 身份。机器 token 优先于 Live 标记；Live 标记优先于用户 Cookie，因此从已登录浏览器打开 Live 也不会提升权限。`public-live` 可以接收现有直播广播，但任何客户端主动业务事件都返回 `LIVE_READ_ONLY`，并且不会收到工具审批列表或麦克风启动控制。

连接失败时，服务端以 `ConnectionRefusedError` 返回 `UNAUTHORIZED`、`RATE_LIMITED`、`PASSWORD_CHANGE_REQUIRED`、`ACCOUNT_DISABLED`、`AUTH_SESSION_STORE_UNAVAILABLE` 或 `AUTH_USER_STORE_UNAVAILABLE`。首次改密会话不会建立 Dashboard Socket；机器 token 不受浏览器用户库与 Session 故障影响。认证连接成功后收到 `system:connection_established`，并重发仍待处理的 `tool:approval_required`；匿名 Live 只收到连接确认和直播状态快照。

受保护命令的回调错误形状为：

```json
{
  "ok": false,
  "error": { "code": "RATE_LIMITED", "message": "..." },
  "retry_after": 5
}
```

## Schema 记法

- `C→S`：客户端发送；`S→C`：服务器推送；`C↔S`：同名事件既作为命令也作为结果推送。
- 字段名后的 `?` 表示可选，`A|B` 表示联合类型，`enum(a/b)` 表示枚举。
- `—` 表示 catalog 没有声明字段或 ack；它不表示实现一定忽略额外数据。
- 表中 ack 只列 `config/socket-events.json` 明确定义的回调 schema。其他命令可能有 handler 返回值，但客户端不得把未声明形状当作稳定契约。

黄金路径事件要求关联 ID。`chat:text` 与 `chat:developer_text` 必须提供 UUID 格式的 `message_id`、`conversation_id`、`task_id`；其余 correlated 事件还要求 `turn_id`。同一 turn 的 `turn_id` 与 `task_id` 应相同。

## 事件目录

### Chat

| 事件 | 方向 | payload | ack |
|------|------|---------|-----|
| `chat:text` | C→S | `text:string`、`message_id:uuid`、`conversation_id:uuid`、`task_id:uuid`、`user_id?:string`、`from_name?:string`、`source?:enum(text/livestream)`、`is_inspection?:boolean`、`is_acceptance?:boolean` | — |
| `chat:developer_text` | C→S | 与 `chat:text` 相同，但 `source` 只能为 `text` | — |
| `chat:sandbox_request` | C→S | `text:string`、四个关联 UUID、`history?:object[]` | — |
| `chat:sandbox_cancel` | C→S | 四个关联 UUID | — |
| `chat:sandbox_chunk` | S→C | `text:string`、`seq:int`、四个关联 UUID、`provider:string`、`model?:string`、`is_complete?:boolean`、`error_code?:string` | — |
| `chat:audio` | C→S | `audio:number[]` | — |
| `chat:audio_end` | C→S | — | — |
| `chat:interrupt` | C→S | 四个关联 UUID、`text?:string` | — |
| `chat:sentence` | S→C | `text:string`、`seq:int`、`lang:string`、`is_complete?:boolean`、四个关联 UUID、`metadata?:object` | — |
| `chat:control` | S→C | 四个关联 UUID；`signal?:conversation-start|conversation-end`；媒体降级时含 `type`、`status`、`component`、`phase`、`reason`、`retryable` | — |
| `chat:transcript` | S→C | `text:string`、`is_final:boolean` | — |
| `chat:stop_audio` | S→C | 四个关联 UUID | — |
| `chat:audio_with_expression` | S→C | 四个关联 UUID、`audio_data:base64`、`format:wav`、`volumes:number[]`、`performance?:object` | — |
| `chat:audio_stream_start` | S→C | 四个关联 UUID、`stream_id:uuid`、`format:pcm_s16le`、`sample_rate:24000`、`channels:1`、`emotion`、`performance?:object` | — |
| `chat:audio_stream_chunk` | S→C | 四个关联 UUID、`stream_id:uuid`、`sequence:int`、`audio_data:base64` | — |
| `chat:audio_stream_end` | S→C | 四个关联 UUID、`stream_id:uuid`、`final_sequence:int`、`status:completed|failed|cancelled`、`reason?:timeout|provider_error|cancelled` | — |
| `chat:subtitle_translation` | S→C | 四个关联 UUID、`translation:string`、`target_lang:string` | — |
| `chat:live2d_action` | S→C | 四个关联 UUID、`type:string`、`group:string`、`index:int` | — |
| `chat:expression` | S→C | 四个关联 UUID、`emotion:string` | — |

`chat:sentence` 的结束帧固定为 `text=""` 且 `is_complete=true`，并保留序号、语言和关联 ID。流式音频必须依次处理 start、递增 sequence 的 chunk、end；合成成功不等于客户端已播放，播放验收应记录实际消费证据。

### History 与配置

| 事件 | 方向 | payload | ack / 结果 |
|------|------|---------|------------|
| `history:list` | C→S | — | handler 返回历史摘要列表 |
| `history:fetch` | C→S | `history_uid?:string` | handler 返回选定历史 |
| `history:clear` | C→S | — | handler 返回清理结果 |
| `history:create` | C→S | — | handler 返回新历史 |
| `config:switch` | C→S | `config_name?:string`、`file?:string` | 结果事件 `config:switched` |
| `config:log_level` | C→S | `level:string` | 结果事件 `config:log_level_changed` |
| `config:get` | C→S | — | 结果事件 `config:data` |
| `config:switched` | S→C | `type?:string`、`config_name:string`、`message:string` | — |
| `config:log_level_changed` | S→C | `type?:string`、`success:boolean`、`level:string`、`message:string` | — |
| `config:data` | S→C | 配置公开快照；catalog 不约束内部字段 | — |
| `config:heartbeat_ack` | S→C | 心跳确认；catalog 不约束内部字段 | — |

### System、任务与工具审批

| 事件 | 方向 | payload | ack |
|------|------|---------|-----|
| `system:heartbeat` | C→S | — | 服务端心跳确认 |
| `system:connection_established` | S→C | `message:string`、`sid:string`、`server_time:string` | — |
| `system:model_status` | S→C | `service:string`、`name:string`、`status:string`、`error?:string` | — |
| `system:error` | S→C | `type`、`message`、四个关联 UUID、`component`、`phase`、`retryable:boolean`、`terminal:boolean` | — |
| `task:status` | C→S | `kind:string`、`task_id:string`、`scope_context?:object` | `{ok:boolean, data?:object, error?:object}` |
| `task:snapshot` | S→C | `kind`、`task_id`、`status`、`progress?`、`result?`、`error?`、`reused:boolean`、`created_at:number`、`updated_at:number` | — |
| `tool:approval_list` | C→S | — | `{ok:boolean, approvals?:object[], error?:object}` |
| `tool:approval_decide` | C→S | `approval_id:string`、`decision:string` | `{ok:boolean, data?:object, error?:object}` |
| `tool:approval_required` | S→C | `schema_version`、`approval_id`、`thread_id`、可选任务/会话 ID、owner、retention、`expires_at`、`tools[]`、可选 kind/status | — |
| `tool:approval_resolved` | S→C | `approval_id`、`task_id`、`status`、`decision`、`reason?` | — |

`system:error.type` 为 `validation_error`、`processing_error`、`timeout`、`interrupted` 或 `internal_error`。`component` 与 `phase` 是稳定分类字段，客户端不应通过错误文案判断恢复策略。

### Desktop

| 事件 | 方向 | payload |
|------|------|---------|
| `desktop:register` | C→S | `client_type:string` |
| `desktop:live2d_action` | C→S | handler 定义的动作对象 |
| `desktop:chat_message` | C→S | handler 定义的消息对象 |
| `desktop:voice_start` | C→S | handler 定义的语音参数 |
| `desktop:voice_stop` | C→S | handler 定义的语音参数 |
| `desktop:registered` | S→C | `client_id:string`、`client_type:string` |
| `desktop:action_queued` | S→C | 动作队列结果对象 |
| `desktop:voice_started` | S→C | 语音启动结果对象 |
| `desktop:voice_stopped` | S→C | 语音停止结果对象 |

### Bilibili 直播

| 事件 | 方向 | payload | ack |
|------|------|---------|-----|
| `bilibili:connect` | C→S | `room_id:number`、`expected_generation_id?:number` | `BilibiliCommandAck` |
| `bilibili:disconnect` | C→S | `expected_generation_id?:number` | `BilibiliCommandAck` |
| `bilibili:update_room` | C→S | `room_id:number`、`expected_generation_id?:number` | `BilibiliCommandAck` |
| `bilibili:danmaku` | S→C | `text`、`user_name`、`user_id`、`timestamp`、`is_gift`、`is_super_chat`、`meta`、`source_message_id?` | — |
| `bilibili:danmaku_status` | S→C | `state`、`connected`、`room_id`、`desired_room_id`、`retry_count`、`error_code`、`generation_id`、`message`、`updated_at` | — |
| `bilibili:live_event` | S→C | `room_id`、`generation_id`、`sequence`、`offset_ms`、`event_type`、`actor_id`、`text`、`payload` | — |
| `bilibili:danmaku_ai_reply` | S→C | `danmaku_text`、`reply_text`、`user_name`、`character_name`、`timestamp`、`source_message_id?`、`reply_id?` | — |

`BilibiliCommandAck = {accepted:boolean, state:string, error_code:string|null, message:string}`。命令只表示已接受；调用方应继续等待 `bilibili:danmaku_status` 到达目标 generation 与状态。

直播状态为 `stopped`、`connecting`、`prelive`、`live`、`reconnecting`、`stopping` 或 `error`。修改命令应携带最后观察到的 `expected_generation_id` 以进行乐观并发检查。

### Minecraft

| 事件 | 方向 | payload |
|------|------|---------|
| `minecraft:connect` | C→S | `request_id:string`、`profile?:string` |
| `minecraft:status` | C↔S | 请求可含 `request_id?`；结果含 schema/generation/state/mode/profile/server/bot/viewer/error |
| `minecraft:disconnect` | C→S | `request_id:string` |
| `minecraft:shutdown` | C→S | `request_id:string` |
| `minecraft:reattach_viewer` | C→S | `request_id:string` |
| `minecraft:viewer_status` | S→C | `status`，以及可选 schema、username、error、mode、reason、binding_state、confirmed、target、attempt、retry_in_ms |
| `minecraft:command_transition` | S→C | `event`、`event_id`、`transition_id`、`command_id`、`from_state?`、`to_state`、`reason_code`、`occurred_at_ms` |
| `minecraft:skill_trust` | S→C | `event`、`event_id`、`revision_hash`、`environment_fingerprint`、`status`、`source_command_id` |
| `minecraft:mission_projection` | S→C | 公共 projection envelope |
| `minecraft:objective_projection` | S→C | 公共 projection envelope |
| `minecraft:proposal_projection` | S→C | 公共 projection envelope |
| `minecraft:discovery_projection` | S→C | 公共 projection envelope |
| `minecraft:skill_validation` | S→C | 公共 projection envelope |
| `minecraft:advancement_projection` | S→C | 公共 projection envelope |
| `minecraft:stage_projection` | S→C | 公共 projection envelope |
| `minecraft:bot_state` | S→C | 可选 health、food、position、dimension、biome、time、weather、action、action_target、held_item、inventory |

公共 projection envelope 为 `schema_version`、`event`、`event_id`、`projection_kind`、`projection_version:number`、`occurred_at_ms:number`、`mission_id?:string`、`entity_id:string`、`payload:object`。连接类命令通过后续 `minecraft:status` 推送返回结果。

### Translation 与 Persona

| 事件 | 方向 | payload |
|------|------|---------|
| `translation:configure` | C→S | `enabled?:boolean`、`target_language?:string` |
| `translation:status` | S→C | `target_language:string`、`enabled:boolean` |
| `persona:list` | C→S | —；ack 返回可用人格 |
| `persona:set` | C→S | `persona_name:string` |
| `persona:set_mode` | C→S | `mode:string` |
| `persona:updated` | S→C | `persona_name:string`、`mbti?:object` |
| `persona:personality_updated` | S→C | `mode:string` |

### Memory V2

Memory 查询与变更使用统一 ack：成功 `{ok:true, data:object}`，失败 `{ok:false, error:{code,message}}`。常见错误码为 `INVALID_REQUEST`、`NOT_FOUND`、`UNAVAILABLE`、`IDEMPOTENCY_CONFLICT`、`RESOURCE_BUSY` 与 `STALE_MEMORY_VERSION`。

| 事件 | 方向 | payload / 结果 |
|------|------|----------------|
| `memory:list` | C→S | `cursor?:string`、`limit?:number`、`scope?:string` |
| `memory:get` | C→S | `id:string` |
| `memory:search` | C→S | `query:string`、`limit?:number` |
| `memory:pin` | C→S | `id:string`、`pinned:boolean` |
| `memory:forget` | C→S | `id:string` |
| `memory:change` | C→S | `id:string`、`summary:string`、`task_id?:string`、`expected_version:int` |
| `memory:job` | C→S | `job_id:string` |
| `memory:organize` | C→S | `task_id?:string`；ack 返回接受或复用的 job |
| `memory:list_pages` | C→S | `session_id:string`；兼容页面列表 ack |
| `memory:changed` | S→C | `revision:number`、`reason:string`、`atom_id?:string` |
| `memory:organize_progress` | S→C | `job_id`、`text`、`progress`、`status` |
| `memory:organize_result` | S→C | `job_id`、`status`、`message`、`revision?` |

`memory:change` 使用 `task_id` 做幂等控制，并用 `expected_version` 做乐观并发控制。`memory:list_pages` 是兼容入口，新客户端优先使用 V2 查询事件。

### Singing

| 事件 | 方向 | payload |
|------|------|---------|
| `sing:process` | C→S | 输入来源四选一：`url?`、`file_data?`、`file_name?`、`local_path?`；另有 `task_id?`、`lyrics_text?`、`auto_confirm?` |
| `sing:confirm_lyrics` | C→S | `ass_content:string`、`task_id?:string` |
| `sing:cancel` | C→S | `task_id?:string` |
| `sing:subtitle_sync` | C→S | — |
| `sing:progress` | S→C | `stage`、`progress:number`、`message`、`task_id` |
| `sing:complete` | S→C | `task_id`、媒体 URL、标题/时长、声音身份、`voice_conversion_applied`、`lyrics[]`、`volumes[]` |
| `sing:error` | S→C | `task_id?:string`、`error:string` |
| `sing:lyrics_ready` | S→C | `message:string` |
| `sing:subtitle_line` | S→C | `text`、`translation`、`lang`、`target_lang` |

`sing:complete` 的声音身份字段为 `voice_provider`、`voice_model`、`voice_revision`、`voice_name`；媒体字段为 `audio_url`、`subtitle_url`、`tts_audio_url`、`vocals_url` 与 `original_url`。

### Meme review

| 事件 | 方向 | payload / 结果 |
|------|------|----------------|
| `meme:add` | C→S | `text` 必填；可选 source、context_hint、tags、source_url、format 与 render 字段；ack `{ok,meme}` |
| `meme:list` | C↔S | 请求 `source_platform?`、`limit?`；结果 `{memes:[...]}` |
| `meme:review` | C↔S | 请求 `meme_id`、`status:good|bad`；结果 `{ok,feedback?|error?}` |
| `meme:dataset` | C↔S | 请求无字段；结果 `{memes:[...]}` |
| `meme:collect` | C↔S | `task_id?:string`、`source?:string`；结果含 ok、task_id、status/count/candidates 或 error |

`meme:collect.task_id` 是幂等键；同键不同请求返回 `IDEMPOTENCY_CONFLICT`，已有任务可返回 `reused=true`。

## 兼容别名

以下别名只供协议迁移适配器使用。新代码必须发送 canonical 名称，服务器也只为单次请求选择 canonical 或 legacy 输出之一，禁止双发。

| canonical | legacy alias |
|-----------|--------------|
| `chat:text` | `text_input` |
| `chat:interrupt` | `interrupt_signal` |
| `chat:sentence` | `sentence` |
| `chat:control` | `control` |
| `chat:stop_audio` | `stop_audio` |
| `chat:audio_with_expression` | `audio_with_expression` |
| `chat:audio_stream_start` | `audio_stream_start` |
| `chat:audio_stream_chunk` | `audio_stream_chunk` |
| `chat:audio_stream_end` | `audio_stream_end` |
| `chat:subtitle_translation` | `subtitle.translation` |
| `chat:live2d_action` | `live2d.action` |
| `chat:expression` | `expression` |
| `system:error` | `error` |

## 客户端规则

1. 从 `Events` 常量读取事件名，不复制字符串。
2. 对声明 ack 的命令设置超时，并同时处理断线、malformed ack 与业务错误。
3. 重连后重新查询 `task:status`、`tool:approval_list`、Bilibili status 或 memory job，不从最后一次 UI 状态猜测结果。
4. 通过 `task_id`、`command_id`、`request_id` 与 `expected_version/generation_id` 使用服务端幂等和并发控制。
5. 将 `system:error` 的 `retryable`、`terminal`、`component`、`phase` 作为恢复依据，不解析自然语言消息。
