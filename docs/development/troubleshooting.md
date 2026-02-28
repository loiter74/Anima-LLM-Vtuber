# 故障排查指南

> 常见问题和解决方案

---

## 目录

1. [启动问题](#启动问题)
2. [连接问题](#连接问题)
3. [Live2D 问题](#Live2D-问题)
4. [音频问题](#音频问题)
5. [性能问题](#性能问题)

---

## 启动问题

### 问题 1: 端口被占用

**错误信息**:
```
OSError: [Errno 48] Address already in use
```

**解决方案**:
```powershell
# Windows PowerShell
.\scripts\stop.ps1  # 停止所有服务
.\scripts\start.ps1  # 重新启动

# 或手动查找并终止进程
netstat -ano | findstr :12394
taskkill /PID <进程ID> /F
```

```bash
# Unix/macOS
./scripts/stop.sh
./scripts/start.sh

# 或手动查找并终止进程
lsof -ti:12394 | xargs kill -9
```

### 问题 2: 依赖缺失

**错误信息**:
```
ModuleNotFoundError: No module named 'anima'
```

**解决方案**:
```bash
# 安装依赖
pip install -r requirements.txt

# 或使用启动脚本的 --install 参数
.\scripts\start.ps1 -Install
```

### 问题 3: 配置文件错误

**错误信息**:
```
ValidationError: 1 validation error for AppConfig
```

**解决方案**:
```bash
# 验证 YAML 语法
python -c "from anima.config import AppConfig; AppConfig.from_yaml('config/config.yaml')"

# 检查配置文件
cat config/config.yaml
```

---

## 连接问题

### 问题 1: 前端无法连接后端

**症状**: 浏览器控制台显示 `WebSocket connection failed`

**排查步骤**:

1. **检查后端是否运行**:
```bash
# 检查端口是否监听
netstat -an | findstr 12394

# 或访问
curl http://localhost:12394/health
```

2. **检查 CORS 配置**:
```python
# src/anima/socketio_server.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 确保包含前端 URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

3. **检查前端 WebSocket URL**:
```typescript
// frontend/features/connection/services/SocketService.ts
const socket = io("http://localhost:12394", {
  transports: ["websocket"],
  reconnection: true,
})
```

### 问题 2: 频繁断线重连

**症状**: WebSocket 频繁 disconnect/connect

**可能原因**:
- 网络不稳定
- 后端重启
- Keep-alive 超时

**解决方案**:
```yaml
# config/config.yaml
system:
  socketio:
    ping_timeout: 60  # 增加超时时间
    ping_interval: 25  # 调整 ping 间隔
```

---

## Live2D 问题

### 问题 1: 模型加载失败

**症状**: Live2D 画布空白，控制台错误

**排查步骤**:

1. **检查模型文件**:
```bash
# 检查模型文件是否存在
ls public/live2d/hiyori/Hiyori.model3.json

# 检查配置路径
cat config/features/live2d.yaml | grep path
```

2. **检查前端配置**:
```json
// frontend/public/config/live2d.json
{
  "modelPath": "/live2d/hiyori/Hiyori.model3.json"  // 确保路径正确
}
```

3. **检查 CORS**:
```bash
# 模型文件必须通过 HTTP 访问，不能用 file:// 协议
# 确保前端服务运行在 http://localhost:3000
```

### 问题 2: 表情不切换

**症状**: Live2D 模型表情始终为 `idle`

**排查步骤**:

1. **检查表情事件**:
```javascript
// 浏览器控制台
socket.on("expression", (data) => {
  console.log("收到表情事件:", data)
})

// 如果没有日志，检查后端是否发送事件
```

2. **检查前端处理**:
```typescript
// frontend/features/live2d/hooks/useLive2D.ts
const setExpression = (expression: string) => {
  console.log("设置表情:", expression)
  serviceRef.current?.setExpression(expression)
}
```

3. **检查表情映射**:
```yaml
# config/features/live2d.yaml
emotion_map:
  happy: "happy"  # 确保映射正确
  sad: "sad"
```

### 问题 3: 唇同步不工作

**症状**: 嘴部不动或动作不自然

**排查步骤**:

1. **检查音量包络**:
```javascript
// 浏览器控制台
socket.on("audio_with_expression", (data) => {
  console.log("音量包络长度:", data.volumes.length)
  console.log("音量包络前 10 个值:", data.volumes.slice(0, 10))
})

// 应该看到 50 个值/秒的音量数据
```

2. **检查唇同步引擎**:
```typescript
// frontend/features/live2d/services/LipSyncEngine.ts
startWithVolumes(volumes: number[], sampleRate: number) {
  console.log("启动唇同步:", volumes.length, "个音量值")
  // ...
}
```

3. **调整灵敏度**:
```yaml
# config/features/live2d.yaml
lip_sync:
  sensitivity: 1.5   # 增大灵敏度
  smoothing: 0.3     # 降低平滑度
  min_threshold: 0.03  # 降低阈值
```

---

## 音频问题

### 问题 1: ASR 识别失败

**症状**: 语音输入无响应或识别错误

**排查步骤**:

1. **检查 VAD**:
```python
# 检查 VAD 是否检测到语音
logger.info(f"VAD 检测结果: has_speech={has_speech}")

# 如果始终为 False，调整 VAD 阈值
```

2. **调整 VAD 参数**:
```yaml
# config/services/vad/silero.yaml
prob_threshold: 0.5      # 降低概率阈值
db_threshold: 25          # 降低分贝阈值
required_hits: 4          # 减少命中次数
required_misses: 30       # 增加未命中次数
```

3. **检查 ASR 配置**:
```yaml
# config/services/asr/faster_whisper.yaml
asr_config:
  model: "large-v3"      # 尝试更换模型
  device: "cpu"          # 或 "cuda" 如果有 GPU
```

### 问题 2: TTS 合成失败

**症状**: 无音频输出或音频错误

**排查步骤**:

1. **检查 TTS 服务**:
```bash
# 测试 Edge TTS
python -c "from anima.services.tts import EdgeTTSService; import asyncio; asyncio.run(EdgeTTSService().synthesize('测试'))"

# 应该输出音频文件路径
```

2. **检查 API 密钥**:
```bash
# 如果使用 GLM TTS
echo $GLM_API_KEY  # 确保已设置

# 或使用免费服务
# config/config.yaml
services:
  tts: edge  # Edge TTS 免费，无需 API 密钥
```

3. **检查音频文件**:
```bash
# 检查生成的音频文件
ls /tmp/tts_*.mp3

# 使用播放器测试
ffplay /tmp/tts_*.mp3
```

### 问题 3: 音频中断失败

**症状**: 新音频播放时旧音频未停止

**排查步骤**:

1. **检查 AudioPlayer**:
```typescript
// frontend/features/audio/services/AudioPlayer.ts
static stopGlobalAudio() {
  console.log("停止所有音频:", window[AudioPlayer.WINDOW_AUDIO_KEY])
  // ...
}
```

2. **检查中断信号**:
```javascript
// 浏览器控制台
socket.on("control", (data) => {
  if (data.action === "interrupt") {
    console.log("收到中断信号")
  }
})
```

3. **强制停止**:
```javascript
// 手动停止所有音频
window.location.reload()  // 刷新页面
```

---

## 性能问题

### 问题 1: 响应延迟高

**症状**: 发送消息后长时间无响应

**排查步骤**:

1. **检查 LLM 响应时间**:
```python
# 添加性能日志
import time
start = time.time()
response = await agent.chat_stream(text)
elapsed = time.time() - start
logger.info(f"LLM 响应时间: {elapsed:.2f}s")
```

2. **更换 LLM 服务**:
```yaml
# config/config.yaml
services:
  agent: glm  # 或使用更快的模型

# config/services/agent/glm.yaml
llm_config:
  model: "glm-4-flash"  # 更快的模型
```

3. **启用流式输出**:
```python
# 确保 LLM 服务支持流式
async for chunk in agent.chat_stream(text):
    # 每个 chunk 立即发送到前端
    await event_bus.emit(OutputEvent(type="sentence", data=chunk))
```

### 问题 2: 内存占用高

**症状**: 长时间运行后内存持续增长

**排查步骤**:

1. **检查会话清理**:
```python
# src/anima/socketio_server.py
async def cleanup_context(sid: str):
    """清理会话资源"""
    if sid in orchestrators:
        await orchestrators[sid].close()  # 确保关闭
        del orchestrators[sid]
```

2. **检查音频缓存**:
```python
# 定期清理临时音频文件
import os
import time

def cleanup_old_audio_files():
    audio_dir = "/tmp/tts_audio"
    now = time.time()
    for filename in os.listdir(audio_dir):
        filepath = os.path.join(audio_dir, filename)
        if now - os.path.getmtime(filepath) > 3600:  # 1 小时
            os.remove(filepath)
```

3. **监控内存使用**:
```bash
# 检查进程内存
ps aux | grep python

# 或使用内存分析器
pip install memory_profiler
python -m memory_profiler -m anima.socketio_server
```

### 问题 3: CPU 占用高

**症状**: CPU 使用率持续 100%

**排查步骤**:

1. **检查音量分析频率**:
```yaml
# config/features/live2d.yaml
lip_sync:
  sample_rate: 25  # 降低采样率（从 50Hz 到 25Hz）
```

2. **检查 Live2D 渲染频率**:
```typescript
// frontend/features/live2d/services/LipSyncEngine.ts
updateInterval: 50  // 降低更新频率（从 33ms 到 50ms）
```

3. **检查 WebSocket 消息频率**:
```python
# 限制事件发送频率
last_emit_time = 0
emit_interval = 0.1  # 100ms 最小间隔

if time.time() - last_emit_time >= emit_interval:
    await event_bus.emit(event)
    last_emit_time = time.time()
```

---

## 调试技巧

### 启用调试日志

```yaml
# config/config.yaml
system:
  log_level: "DEBUG"  # 或 "TRACE" 获取更多日志
```

### 使用浏览器开发工具

```javascript
// 浏览器控制台
// 监听所有 WebSocket 事件
socket.onAny((event, ...args) => {
  console.log(`[WebSocket] ${event}:`, args)
})

// 检查状态
socket.emit("get_status", {}, (status) => {
  console.log("系统状态:", status)
})
```

### 使用 Python 调试器

```bash
# 使用 pdb 调试
python -m pdb -m anima.socketio_server

# 或使用 VS Code 调试器
# 在代码中添加断点
import pdb; pdb.set_trace()
```

### 性能分析

```python
# 使用 cProfile 分析性能
import cProfile

pr = cProfile.Profile()
pr.enable()

# 运行代码
await orchestrator.process_input(audio_data)

pr.disable()
pr.print_stats(sort="cumtime")
```

---

## 总结

### 常见问题速查表

| 问题 | 可能原因 | 快速解决方案 |
|------|----------|--------------|
| **端口被占用** | 旧进程未终止 | 运行 `stop.ps1` |
| **前端无法连接** | 后端未启动 | 检查端口 12394 |
| **Live2D 不显示** | 模型路径错误 | 检查 `config/features/live2d.yaml` |
| **表情不切换** | 事件未发送 | 检查 `emotion_map` |
| **唇同步失效** | 音量包络为空 | 检查 `volumes` 数据 |
| **ASR 失败** | VAD 阈值过高 | 降低 `prob_threshold` |
| **响应慢** | LLM 模型慢 | 换用 `glm-4-flash` |
| **内存高** | 会话未清理 | 检查 `cleanup_context()` |

### 获取帮助

1. **查看日志**: `logs/anima.log`
2. **查看文档**: `docs/`
3. **检查配置**: `config/config.yaml`
4. **查看 Issues**: GitHub Issues

---

**最后更新**: 2026-02-28
