---
name: connect-bilibili-live
description: 连接、切换、查询或断开 Animetta 后端持有的唯一真实 Bilibili 直播弹幕会话，区分开播前 prelive 与真实 live，并在正式 /live.html 验收弹幕、LLM 回复与 TTS 实际播放。用户要求连接 B 站直播、启动弹幕姬、开播前测试、把默认直播间接到 Animetta、切换直播间或检查真实弹幕链路时使用。
---

# 连接 B 站直播

复用现有 Bilibili 控制面连接真实房间，不直接启动 `DanmakuService`，不创建第二条网关连接。

## 流程

1. Windows 首次执行前断言 Python 3.13，并在当前进程设置 `PYTHONUTF8=1` 与运行时使用的 `ANIMETTA_ACCESS_TOKEN`。生产环境下，脚本以 Bearer 令牌检查 `/ready`，再通过 Socket.IO `auth.token` 建立控制连接；不得打印令牌。若令牌为临时值，生成、运行时操作、连接与验收必须保持在同一子进程内。
2. 用户要求连接时先使用 `$operate-anima-runtime` 检查 `/ready`；未就绪时按其规范启动。冷启动耗时单独报告，不计入 60 秒热启动指标。
3. 使用 `$review-anima-live` 的 `live` feature 解析并打开当前正式 `/live.html`；不得启动 OBS。记录：
   - `#audioStatus[data-playback-count]` 基线；
   - 页面打开后热启动计时起点。
4. 从仓库根目录执行最小动作：

   ```powershell
   $env:PYTHONUTF8 = '1'
   py -3.13 .agents/skills/connect-bilibili-live/scripts/bilibili_live.py status
   py -3.13 .agents/skills/connect-bilibili-live/scripts/bilibili_live.py connect
   py -3.13 .agents/skills/connect-bilibili-live/scripts/bilibili_live.py switch --room-id 123456
   py -3.13 .agents/skills/connect-bilibili-live/scripts/bilibili_live.py disconnect
   ```

5. `connect` 默认读取 `config/bilibili.local.yaml`（本机真实房间，已 gitignore）的 `room_id`，不存在时回落到模板 `config/bilibili.yaml`；只有用户明确给出临时房间时才传 `--room-id`。当前会话已在其他房间时停止并报告，只有明确要求“切换”才执行 `switch`。
6. 连接成功必须同时满足：
   - CLI 返回 `ok=true`、`state=prelive|live`、目标 `room_id`、`elapsed_ms<60000`；
   - 页面 `#socketStatus[data-state=connected]`；
   - 页面 `#livestreamStatus[data-state]` 与 CLI 一致；未开播时必须是 `prelive`，不得报告为 `live`；
   - 从页面热启动计时起到以上断言全部成立小于 60 秒。
7. `prelive` 表示弹幕网关已连接、B 站房间尚未开播；`live` 只来自房间信息与 `LIVE` / `PREPARING` 权威事件。保持直播会话运行，不在验收后自动断开。脚本退出只关闭本地控制连接。
8. 用户要求开播前模拟时，必须先确认同一目标房间为 `prelive`，再使用 `$simulate-live-danmaku` 的 `smoke` 场景。真实 `live`、其他房间连接或节目活动时仍拒绝模拟；模拟结束后真实弹幕网关继续保持 `prelive`。
9. 用户要求完整链路验收时加载 `$qa-testing-playwright`，等待第一条真实可回复弹幕并按同一 ID 链路断言：
   - `.danmaku-item[data-message-id="<source_message_id>"]` 存在；
   - `#livestreamStatus[data-last-bilibili-source-message-id="<source_message_id>"]`；
   - `data-last-bilibili-reply-id` 提供本轮 `reply_id`；
   - `#audioStatus[data-playback-count]` 相比基线递增；
   - `data-last-audio-task-id` 等于该 `reply_id`；
   - `data-playback-state` 最终为 `playing` 或 `completed`，控制台没有播放失败或链路错误。
10. 等待窗口内没有真实可回复弹幕时报告 `awaiting_real_danmaku`。开播前模拟证据必须明确标为合成，不得宣称真实链路通过。

## 控制参数

- `--base-url` 默认为 `http://127.0.0.1`。
- `--timeout-seconds` 默认为 30，最大 60；连接总预算仍以 60 秒热启动指标为准。
- `status`、`connect`、`switch`、`disconnect` 始终只输出一份 JSON，包含 `ok`、`state`、`room_id`、`generation_id`、`elapsed_ms`、`error_code`、`message`。

## 边界

- 不读取、打印或改写 `sessdata`；登录态仍由 Animetta 后端配置持有。
- 不修改全局 Codex MCP 配置，不安装插件，不启动 OBS。
- 不把 Bilibili 连接成功、Socket 收到回复或 TTS 合成成功当成页面实际播放通过。
- 不持久化真实观众身份、消息或浏览器证据；只读取本轮验收所需的页面状态。

## 报告

分别报告冷启动耗时、热连接耗时、房间号、generation、后端状态、页面状态和真实弹幕链路状态。没有观察到真实弹幕时明确标为未验收，不得写成通过。
