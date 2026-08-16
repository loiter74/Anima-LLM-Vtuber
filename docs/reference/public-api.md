# Animetta 公开 API 总览

本文定义 GitHub 仓库 [`loiter74/animetta`](https://github.com/loiter74/animetta) 对外可调用或可扩展的稳定边界。

## API 范围

| 表面 | 调用方 | 协议 / 入口 | 详细文档 |
|------|--------|-------------|----------|
| Animetta 核心服务 | 浏览器、运维工具、自动化客户端 | HTTP，默认 `http://127.0.0.1:12394` | [backend-api.md](backend-api.md) |
| 实时交互 | Dashboard、`/live.html`、桌面客户端 | Socket.IO，默认命名空间 `/` | [socket-api.md](socket-api.md) |
| 宿主机 Qwen TTS | Animetta 后端 | HTTP，固定宿主机入口 `http://127.0.0.1:8767` | [backend-api.md#宿主机-qwen-tts-api](backend-api.md#宿主机-qwen-tts-api) |
| 宿主机 RVC / 分离服务 | 唱歌管线 | HTTP，固定宿主机入口 `http://127.0.0.1:8769` | [backend-api.md#宿主机-rvc-api](backend-api.md#宿主机-rvc-api) |
| 通知服务 | Alertmanager | HTTP，独立 ASGI 应用 | [backend-api.md#通知服务-api](backend-api.md#通知服务-api) |
| 产品工具 | LLM 工具调用 | LangChain Tool schema | [tools.md](tools.md) |
| Bilibili 开发控制器 | 开发智能体 | MCP stdio | [tools.md#bilibili-mcp](tools.md#bilibili-mcp) |
| Provider 扩展点 | Python 插件实现者 | Python ABC + `ProviderRegistry` | [Provider 扩展 API](#provider-扩展-api) |

仓库中的验收 harness、测试夹具、内部服务方法、普通 Python 辅助函数和静态页面不是公开 API。它们即使监听本地端口，也不承诺兼容性。

## 兼容性与真相源

- HTTP 路由的真相源是 `src/animetta/orchestration/server/websocket.py`、`stats_api.py`、`security.py` 与 `program_script_api.py`。
- Socket.IO 名称和字段 schema 的唯一真相源是 `config/socket-events.json`；前端必须使用 `frontend/src/constants/socket-events.ts` 导出的 `Events`，不要复制事件字符串。
- 事件名使用 `module:action`。旧事件名只在声明的兼容适配器边界内有效，不构成第二套公开 API。
- 工具是否真正暴露由 `config/tools.yaml` 决定。函数存在不等于默认启用。
- Provider 配置和实现必须使用相同的 `(category, type)` 注册键。

## 安全模型

核心服务只在 `production` profile 启用共享令牌认证；宿主机 Qwen TTS 与 RVC 使用各自的 Bearer token。端点例外、Cookie、Socket.IO 握手与限流规则分别见 [HTTP 认证](backend-api.md#认证) 和 [Socket.IO 连接](socket-api.md#连接认证与错误)。

## Provider 扩展 API

Provider 是仓库唯一承诺的 Python 扩展边界；Animetta 本身不是一个具有全量稳定导出承诺的通用 Python SDK。

| 类别 | 接口 | 必须实现的核心方法 |
|------|------|--------------------|
| LLM | `LLMInterface` | `chat`、`chat_stream`、`set_system_prompt`、`get_history`、`clear_history`、`handle_interrupt`、`set_memory_from_history`、`close` |
| ASR | `ASRInterface` | `transcribe(audio_data, **kwargs)`、`close` |
| TTS | `TTSInterface` | `synthesize(text, output_path=None, **kwargs)`、`close`；可覆盖 `audio_format`、`sample_rate`、`requires_gpu` |
| VAD | `VADInterface` | `detect_speech`、`reset`、`get_current_state`、`close` |
| VC | `VCInterface` | `convert(audio, output_path=None, **kwargs)`、`close` |
| Separation | `SeparationInterface` | `separate(audio, target=None, output_dir=None, **kwargs)`、`close` |
| Singing 服务契约 | `SingingService` | `process`、`cancel`、`confirm_lyrics`、`get_progress`、`close` |

LLM、ASR、TTS、VAD、VC 与 Separation Provider 需要四个一致的组成部分：

1. 继承对应接口；
2. 定义 Pydantic 配置类，并用 `@ProviderRegistry.register_config(category, type)` 注册；
3. 用 `@ProviderRegistry.register_service(category, type)` 注册实现，并提供 `from_config`；
4. 通过对应 factory 与包 `__init__.py` 暴露。

注册器位于 `src/animetta/config/core/registry.py`。Provider 接口位于 `src/animetta/services/{llm,asr,tts,vad,vc,separation,singing}/interface.py`。

`SingingService` 是注入式管线契约，不通过 `ProviderRegistry` 注册。

## 客户端选择

- 需要请求/响应与资源读取时使用 HTTP。
- 需要流式文本、音频、状态广播或长任务进度时使用 Socket.IO。
- 开发智能体控制唯一 Bilibili 会话时使用 Bilibili MCP，不直接绕过后端连接 Bilibili。
- LLM 内部能力调用使用产品工具，不把开发 MCP 注册进 `config/tools.yaml`。
