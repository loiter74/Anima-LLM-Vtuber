# Animetta HTTP API

本文记录仓库当前所有稳定 HTTP 接口。核心服务使用 Starlette + Socket.IO ASGI，默认地址为 `http://127.0.0.1:12394`；Docker 通过 nginx 暴露同源入口。

Socket.IO 实时协议见 [socket-api.md](socket-api.md)，全部公开表面见 [public-api.md](public-api.md)。

## 通用约定

### 认证

核心服务仅在 `production` profile 启用认证。

| 路径 | production 认证 |
|------|-----------------|
| `GET /health` | 不需要 |
| `POST /api/auth/login` | 不需要，以账号密码换取 Cookie |
| `GET /ready`、`GET /metrics` | 需要 |
| 其他 `/api/auth/*` | 各端点自行处理账号或 Cookie |
| 其他 `/api/*` | 需要 |
| `/app/*`、Socket.IO 握手 | 分别由静态路由与 Socket.IO 认证规则处理 |

受保护 HTTP 请求可使用以下任一种凭据：

```http
Authorization: Bearer <ANIMETTA_ACCESS_TOKEN>
```

`ANIMETTA_ACCESS_TOKEN` 仅用于机器客户端。浏览器默认账号为 `admin / animetta`；Compose 只把预计算、随机盐的 `scrypt-v1` 哈希注入容器，不传递明文密码。`ANIMETTA_AUTH_USERNAME` 和 `ANIMETTA_AUTH_PASSWORD_HASH` 可覆盖默认账号，密码哈希由后端 `hash_password` 生成。局域网或公网暴露前必须覆盖默认密码哈希。

登录成功后，浏览器得到 HttpOnly、SameSite=Strict `animetta_session` Cookie。Cookie 值是不可预测的不透明 token；Redis 仅在 `animetta:auth:session:v1:` 命名空间保存 token 的 SHA-256 摘要及签发/过期元数据，固定 8 小时过期且不会滑动续期。登出会撤销当前 Session，多个浏览器 Session 彼此独立。Redis Session 存储不可用时浏览器登录、Cookie HTTP 与 Cookie Socket 以 `AUTH_SESSION_STORE_UNAVAILABLE` 故障关闭，机器 Bearer/Socket token 不受影响。非生产 profile 下认证关闭。

认证错误统一为：

```json
{
  "ok": false,
  "error": { "code": "UNAUTHORIZED", "message": "Authentication required" }
}
```

登录限流返回 HTTP 429、`Retry-After` 响应头和 `RATE_LIMITED` 错误码。

### CORS 与内容类型

允许来源来自有效配置的 `security.allowed_origins`，允许凭据以及 `GET`、`POST`、`PUT`、`DELETE`、`OPTIONS`。JSON 请求使用 `Content-Type: application/json`。除文件与指标端点外，响应为 JSON。

## 核心服务 API

### 基础设施与认证

| 方法 | 路径 | 请求 | 成功响应 | 失败 |
|------|------|------|----------|------|
| GET | `/health` | 无 | `200 {status:"ok", service:"anima", timestamp:number}` | 无远程探测；它只证明进程存活 |
| GET | `/ready` | 无 | 运行时、前端、Provider、内存、观测、必需的 `auth_session` 与 checkpoint 缓存快照 | 未就绪 `503`；快照不可用时 `reason=snapshot_unavailable` |
| GET | `/metrics` | 无 | Prometheus text exposition | production 未认证 `401` |
| POST | `/api/auth/login` | `{username:string,password:string}` | `{ok:true, expires_at:int}` 并设置会话 Cookie | `401`、`429`、`503` |
| GET | `/api/auth/session` | 无 | `{ok:true, authenticated:true, source:string}` | `401`、Session 存储不可用 `503` |
| POST | `/api/auth/logout` | 无 | `{ok:true}` 并撤销 Session、删除 Cookie | Session 存储不可用 `503`（仍删除 Cookie） |
| GET | `/app/*` | 静态路径 | 前端生产构建；仅在 `frontend/dist` 存在时挂载 | `404` |

`/ready` 是发布与依赖就绪门禁；不要把 `/health` 当作 Provider、模型或数据库已就绪的证据。

### 运行时配置

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| POST | `/api/config/reload` | 无请求体要求 | `ReloadResult`；成功 HTTP 200，拒绝或校验失败 HTTP 400 |

`ReloadResult` 字段为 `ok`、`version`、`persona`、`refreshed[]`、`error`、`preserved`、`effective_hash`、`semantic_hash`、`restart_required[]` 与 `applied`。需要重启的配置不会被静默热应用；失败结果保留上一份有效配置。

### 唱歌媒体

| 方法 | 路径 | 响应 |
|------|------|------|
| GET | `/api/singing/audio/{filename}` | 音频文件，按扩展名推断媒体类型；不存在时 404 |
| GET | `/api/singing/subtitle/{filename}` | `text/plain` 附件；不存在时 404 |
| GET | `/api/singing/playlist` | 按直播顺序排列的配置歌单；配置不可用时 500 |
| GET | `/api/singing/recent` | 最近 5 个 `*_final.wav` 结果 |

`/api/singing/playlist` 返回数组，每个条目包含稳定的 `id`、`title`、`performer`、编排位置 `role`、制作提示 `note` 与 Bilibili `url`。数组顺序就是推荐演出顺序，真相源为 `config/singing.yaml`。

`/api/singing/recent` 的每个条目包含 `session_id`、`audio_url`、可为空的 `vocals_url`、`original_url`、`subtitle_url`、`tts_audio_url`、本地 ISO 时间 `created_at` 和当前固定为 `0.0` 的 `duration_sec`。

### 观测与统计

| 方法 | 路径 | 查询参数 | 成功响应 |
|------|------|----------|----------|
| GET | `/api/stats/overview` | 无 | 版本化总览对象 |
| GET | `/api/stats/nodes` | 无 | `OperationAggregateDTO[]` |
| GET | `/api/stats/traces` | `limit=50`、`offset=0` | `TraceSummaryDTO[]` |
| GET | `/api/stats/traces/{trace_id}` | 无 | `TraceDetailDTO` |
| GET | `/api/stats/traces/{trace_id}/tree` | 无 | 与详情相同的规范操作层级 |
| GET | `/api/stats/traces/{trace_id}/events` | 无 | 版本化事件列表 |
| GET | `/api/stats/live` | `limit=20` | 直播控制台总览与最近 turn |
| GET | `/api/stats/live/turns/{trace_id}` | 无 | 确定性的公开执行时间线 |
| GET | `/api/stats/observation-health` | 无 | 观测账本健康 DTO |
| GET | `/api/stats/inspection/latest` | 无 | `{api_version:"2", ...report}` |

未知 trace/turn 或尚无检查报告时返回 HTTP 404。观测查询未配置或查询失败时返回 HTTP 500：`{"error":"..."}`。公开字段由 `src/animetta/observability/dto.py` 统一裁剪，不应依赖账本内部列。

## 节目脚本、运行与重放 API

### 脚本与草稿

| 方法 | 路径 | 请求体 | 成功 |
|------|------|--------|------|
| GET | `/api/program-scripts` | 无 | `{scripts: PublishedProgramScript[]}` |
| POST | `/api/program-scripts/drafts` | `{script: ProgramScript}` | `201 ProgramScriptDraft` |
| GET | `/api/program-scripts/drafts/{script_id}` | 无 | `ProgramScriptDraft` |
| PUT | `/api/program-scripts/drafts/{script_id}` | `{revision:int, script:ProgramScript}` | 更新后的草稿 |
| POST | `/api/program-scripts/drafts/{script_id}/validate` | 无 | `{valid:boolean, issues:ValidationIssue[]}` |
| POST | `/api/program-scripts/drafts/{script_id}/publish` | `{revision:int}` | `201 PublishedProgramScript` |
| GET | `/api/program-scripts/{script_id}/versions/{version}` | 无 | `PublishedProgramScript` |
| POST | `/api/program-scripts/{script_id}/versions/{version}/duplicate` | `{new_id?:string, title?:string}` | `201 ProgramScriptDraft` |
| POST | `/api/program-scripts/{script_id}/archive` | 无 | `{ok:true}` |

核心 DTO：

- `ProgramScriptDraft = {revision, script}`。
- `PublishedProgramScript = {version, content_hash, created_at, builtin, script}`。
- `ValidationIssue = {path, message, code}`。
- `ProgramScript` 是 strict schema，拒绝额外字段；包含 `id`、`title`、`description`、`template`、`disclosure`、`opening`、`closing`、`defaults`、`option_sets` 与 `beats`。完整约束由 `src/animetta/services/program_script/models.py` 定义。

### 运行控制

| 方法 | 路径 | 请求体 / 查询 | 成功 |
|------|------|---------------|------|
| POST | `/api/program-runs/start` | `{script_id, version:int, room_id:int, creator_id?:string, task_id?:string}` | `202 ProgramRun` 快照 |
| GET | `/api/program-runs/current` | `room_id`，默认 `1` | `{run: ProgramRun|null}` |
| GET | `/api/program-runs/{run_id}` | 无 | `ProgramRun` 快照 |
| POST | `/api/program-runs/{run_id}/choice` | `{beat_id, option_id, creator_id?, command_id?}` | `202 ProgramRun` 快照 |
| POST | `/api/program-runs/{run_id}/control` | `{action, creator_id?, command_id?}` | `ProgramRun` 快照 |

运行 `action` 为 `pause`、`resume`、`retry` 或 `stop`。`ProgramRun.state` 为 `idle`、`running`、`paused`、`completed`、`stopped` 或 `failed`；快照还包含当前 beat、槽位、turn 记录、错误与脚本不可变身份。

`task_id` 与 `command_id` 是幂等键。相同键和相同请求复用已有结果；相同键但不同请求返回 `IDEMPOTENCY_CONFLICT`。

### 弹幕重放

| 方法 | 路径 | 请求体 | 成功 |
|------|------|--------|------|
| POST | `/api/program-replays/start` | 见下方 | `202 ReplayRun` 快照 |
| GET | `/api/program-replays/{replay_id}` | 无 | `ReplayRun` 快照 |
| POST | `/api/program-replays/{replay_id}/control` | `{action, creator_id?, speed?, command_id?}` | `ReplayRun` 快照 |

启动重放的公共字段为 `source`、`room_id`、`creator_id?`、`speed?`、`task_id?`。当 `source="script"` 时还需 `script_id`、`version`，可选 `selections` 对象；当 `source="jsonl"` 时需 `jsonl` 字符串。

控制 `action` 为 `pause`、`resume`、`step`、`speed`、`restart` 或 `stop`。`ReplayRun.state` 为 `idle`、`running`、`paused`、`completed`、`stopped` 或 `failed`。

### 节目 API 错误

| 情况 | HTTP | 响应 |
|------|------|------|
| Pydantic schema 失败 | 422 | `{error_code:"validation_error", message:"配置格式无效", issues:[...]}` |
| JSON 类型、缺失字段或数值转换失败 | 400 | `{error_code:"invalid_request", message:string}` |
| 领域错误 | 错误自身的状态码 | `{error_code:string, message:string}` |

## 宿主机 Qwen TTS API

固定宿主机地址为 `http://127.0.0.1:8767`。该服务不进入 Docker 生命周期。

| 方法 | 路径 | 认证 | 响应 |
|------|------|------|------|
| GET | `/health` | 无 | `{status:"ok", service:"qwen-tts", api_version:"v1"}` |
| GET | `/ready` | Bearer | 身份快照；未就绪 503 |
| GET | `/v1/identity` | Bearer | 与 `/ready` 相同 |
| POST | `/v1/audio/speech` | Bearer | 音频或 PCM 流 |

合成请求：

```json
{
  "input": "你好",
  "model": "与 /ready 一致",
  "voice": "与 /ready 一致",
  "language": "zh",
  "response_format": "wav",
  "stream": false,
  "request_id": "可选调用方 ID"
}
```

`model`、`voice`、`response_format` 与服务身份必须精确匹配；`language` 省略时使用服务配置。非流式成功返回音频以及 `x-animetta-provider`、`x-animetta-model`、`x-animetta-voice`、`x-request-id`。`stream=true` 返回 `audio/pcm`，并额外返回格式、采样率和声道头。

错误 JSON 为 `{category, request_id?, field?}`；主要状态为 401 `authentication`、422 `unsupported_identity`、429 `busy`、503 `not_ready`、504 `timeout`、502 `generation_failed` 或 `invalid_audio`。

## 宿主机 RVC API

固定宿主机地址为 `http://127.0.0.1:8769`。除 `/health` 外均要求 Bearer token。

| 方法 | 路径 | 请求 | 成功 |
|------|------|------|------|
| GET | `/health` | 无 | `{status:"ok", service:"rvc", api_version:"v1"}` |
| GET | `/ready` | 无请求体 | 身份与分离就绪快照；未就绪 503 |
| GET | `/v1/identity` | 无请求体 | 与 `/ready` 相同 |
| POST | `/v1/convert` | JSON，见下方 | `audio/wav` |
| POST | `/v1/separate` | 原始音频 bytes + 请求头 | `application/zip` 的 `stems.zip` |

转换请求字段：

```json
{
  "model": "与 /ready 一致",
  "audio_base64": "base64 WAV",
  "request_id": "可选",
  "f0_method": "rmvpe",
  "f0_up_key": 0,
  "index_rate": 0.0,
  "filter_radius": 3,
  "rms_mix_rate": 0.5,
  "protect": 0.5
}
```

转换输入上限 64 MiB。分离请求体上限 128 MiB，并使用 `X-Separation-Model` 指定精确模型、可用 `X-Request-ID` 传递关联 ID。错误 `category` 包括 `unauthorized`、`invalid_json`、`not_ready`、`model_mismatch`、`invalid_audio`、`timeout`、`conversion_failed`、`separation_failed` 与 `empty_audio`。

## 通知服务 API

`animetta.notifier.server:create_notifier_app` 是独立 ASGI 应用，监听地址由部署者决定。

| 方法 | 路径 | 请求 | 响应 |
|------|------|------|------|
| GET | `/health` | 无 | `{status:"ok", service:"anima-notifier"}` |
| POST | `/api/v1/alerts` | Alertmanager webhook JSON | `{status:"ok", channels:object}`；无效 JSON 400，派发失败 500 |

通知应用本身没有认证中间件，部署时应限制网络边界或在反向代理层鉴权。
