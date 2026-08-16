---
name: run-anima-live-singing
description: 诊断 Animetta 唱歌模型与依赖，并在唯一正式入口 /live.html 发起真实唱歌处理、验证生成音频和持久播放证据。用户要求检查唱歌模型、跑通唱歌功能、在 live 模式调用唱歌或验收直播唱歌播放时使用。
---

# 运行 Animetta 直播唱歌

使用仓库的确定性冒烟入口，保持模型诊断、产品调用和浏览器播放证据属于同一个 `task_id`。

## 流程

1. 读取根目录、`frontend/`、`src/animetta/services/` 和 `src/animetta/orchestration/` 的 `AGENTS.md`。
2. 使用 `$operate-anima-runtime` 确认正式运行时 ready；改变服务状态时交给其要求的唯一专用子智能体。
3. 正式实例启用账号会话鉴权时，先确认验收浏览器已有有效 HttpOnly 会话，且 `/live.html` 的 `#socketStatus` 已连接，再启动耗时唱歌任务。`ANIMETTA_ACCESS_TOKEN` 只可用于独立 HTTP / Socket 客户端，不能代替页面自身的浏览器 WebSocket 会话；当前脚本若仍创建全新浏览器上下文且没有会话引导，应停止页面验收并请用户先登录，不得通过重复等待、附加 Bearer 头或强制 polling 试探。
4. 运行严格模型预检。它必须同时验证宿主 RVC 进程、固定模型身份、宿主 Demucs、GPU 推理资产和客户端配置；不可用时明确记录，不把兼容音轨当成目标声线已经生效：

   ```powershell
   py -3.13 .agents/skills/run-anima-live-singing/scripts/model_preflight.py --require-voice
   ```
5. 运行：

   ```powershell
   pnpm -C frontend run live:sing-smoke -- --base-url http://127.0.0.1 --audio-file <音频路径> --lyrics <歌词> --duration-seconds 12
   ```

   整首歌曲必须先让短 smoke 通过，再运行容量契约测试；不要等长任务超时后才检查代理、Socket、上传解码和 RVC 的逐层限制：

   ```powershell
   py -3.13 -m pytest tests/deployment/test_runtime_topology.py::test_production_proxy_accepts_the_bounded_whole_song_socket_payload tests/core/test_socketio_server.py::test_run_server_uses_the_bounded_singing_websocket_frame_limit tests/orchestration/server/test_websocket.py::TestWebSocketServerInit::test_init_creates_sio_and_asgi tests/services/singing/test_rvc_host_app.py::test_host_rvc_rejects_decoded_audio_over_the_bounded_limit -q
   ```

6. 只在输出同时满足以下条件时判定跑通：
   - `sing:complete.task_id` 与本轮一致；
   - `voice_conversion_applied=true`；
   - `voice_provider`、`voice_model`、`voice_revision`、`voice_name` 与预检身份完全一致；
   - `sing:progress` 不含 `Voice conversion skipped`；
   - 宿主预检中 `separation_ready=true` 且 `separation_model` 与配置一致；
   - 生成音频 HTTP 200 且字节数大于 WAV 头；
   - `/live.html` 不显示播放器卡片，隐藏的 `#singingAudio` URL 等于本轮输出、`currentTime > 0` 且未暂停；
   - `/dashboard` 中可见的唱歌播放器属于本轮 `task_id`，显示 RVC 声线身份，并提供“RVC 混音 / RVC 纯人声 / 原始音频”试听切换；
   - 点击 Dashboard 的 RVC 混音播放按钮后，其音频 `currentTime > 0` 且未暂停；
   - `#audioStatus[data-playback-count]` 递增；
   - `data-last-audio-task-id` 等于本轮 `task_id`；
   - `data-last-audio-kind=singing`；
   - 最终状态为 `playing` 或 `completed`，且没有浏览器播放失败。
7. 若还需常规直播布局证据，再使用 `$review-anima-live` 的 `live` feature；不得用评审夹具代替真实唱歌调用。

## 约束

- 正式入口固定为 `/live.html`。
- 默认只截取短音频做冒烟，避免把长模型推理当成连通性测试。
- Windows 下直接调用上述脚本并把路径作为独立参数传入；不要在 PowerShell 字符串中内嵌 JavaScript 或拼接通配路径。
- 生产实唱不允许退回 FFmpeg 兼容分离；它会把整首混音送入 RVC，只能用于明确标注的结构测试。
- 不调整声线参数；只保留 `model_name`、`index_path`、`f0_method` 等配置入口供后续调音。
- 不直接启动 Docker、宿主 TTS、宿主 RVC 或第二套直播页面。

## 报告

报告宿主 RVC 与 Demucs 身份、是否真实转换、降级阶段、`task_id`、生成音频响应、live 隐藏播放状态、Dashboard 可见播放器及 A/B 音轨、点击后的 `currentTime`、播放计数变化和证据路径。
