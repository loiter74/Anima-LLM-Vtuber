# Animetta 工具 API

本文记录 LLM 可调用的产品工具、外部 MCP 桥接方式，以及开发智能体使用的 Bilibili MCP。工具实现存在不等于默认启用；运行时暴露集合由 `config/tools.yaml` 决定。

## 产品工具模型

工具由 LangChain `@tool` 声明，在 `src/animetta/tools/base.py` 中注册，并由 LangGraph 工具节点执行。当前配置限制每个 LLM turn 最多调用 5 次。

### 内置工具

| 工具 | 参数 | 返回 | 默认启用 |
|------|------|------|----------|
| `web_search` | `query:string`、`num_results:int=5` | 格式化搜索结果字符串 | 是 |
| `get_current_time` | `timezone:string="Asia/Shanghai"` | 带时区的时间字符串 | 是 |
| `calculator` | `expression:string` | 基础算术结果或失败字符串 | 是 |
| `get_weather` | `city:string` | 高德天气或有限 fallback 字符串 | 否 |

`web_search` 优先使用 `TAVILY_API_KEY`，失败后尝试 DuckDuckGo；结果数量最多 10。`calculator` 只支持数值常量、加减乘除、乘方和一元负号，不执行任意 Python。

旧文档曾列出的 `read_file` 与 `list_directory` 已不是内置工具。文件访问由沙箱化 MCP filesystem 替代。

### 可选自定义工具

| 工具 | 参数 | 外部依赖 | 默认启用 |
|------|------|----------|----------|
| `url_preview` | `url:string` | HTTP 网络 | 否 |
| `send_email` | `to`、`subject`、`body` | `SMTP_USER`、`SMTP_PASSWORD`，可选 host/port | 否 |
| `image_gen` | `prompt`、`size="1024x1024"` | `OPENAI_API_KEY` 或 `REPLICATE_API_TOKEN` | 否 |

启用名称放入 `custom_tools.enabled`。这些工具返回字符串，不使用统一结构化错误对象。

## Minecraft 产品工具

Minecraft 对 LLM 只公开两个工具。它们通过同仓、独立进程运行的
`services/mc-mcp` 服务操作资源；Animetta 不直接启动 Mineflayer bot 或
Minecraft Compose。

### `mc_connection`

```text
operation: connect | status | disconnect | shutdown | reattach_viewer
request_id: string，1..128，字符集 [A-Za-z0-9_.:-]
profile?: string，仅 connect 可用
```

- `disconnect` 只断开 bot，保留托管资源。
- `shutdown` 只关闭 `mc-mcp` 自己拥有的托管资源。
- 返回 JSON 字符串形式的连接状态或错误。

### `mc_operate_bot`

| operation | 允许字段 | 说明 |
|-----------|----------|------|
| `execute` | 仅 `execute`，顶层 `request_id?` 必须与内部一致 | 提交 `contract_version="2"` 的 mission 或 atomic 请求 |
| `progress` | `request_id?` 或 `command_id?` 二选一，也可用 `cursor?`、`limit=20`、`projection_kind=commands|missions|activities` | 读取持久化 projection，不直接查询实时世界；activities 只返回调用者范围内的脱敏公开活动 |
| `cancel` | `request_id`、`reason="operator stop"` | 先写 durable stop barrier，再协作取消运行时 |

`execute` 对象：

```json
{
  "contract_version": "2",
  "kind": "mission",
  "request_id": "turn-123",
  "mission": {},
  "requested_budget": {},
  "wait_seconds": 0
}
```

`kind="atomic"` 时使用 `action` 替代 `mission`，只供受信任内部探针。完整 mission、action 与 budget schema 由 `src/animetta/tools/minecraft/voyager/` 的 Pydantic 模型生成，额外字段会被拒绝。

Minecraft 的直播表现由 `minecraft.presentation` 配置控制：`mode=off|visual_only|full`、`tempo=calm|normal|brisk`、确定性字符串 `seed`、`replay_limit` 和 retention。默认语义是 `off`；正式直播配置必须显式启用。环境变量 `MC_MCP_PRESENTATION_FORCE_OFF=true` 只能强制关闭，不能由 LLM 或单次 action 打开。非法枚举值会在配置加载时失败。

`activities` 不暴露工具参数、内部 ID、坐标、receipt 或 reasoning。事件先写入 append-only journal，再 best-effort 广播；已验证终态才允许产生 `succeeded`。表现模式不得改变 action outcome、budget、背包、方块、路径或最终水平位置。

Minecraft 工具仅在 `minecraft.enabled=true` 且以下任一入口可用时加载：
`mcp.auth_token_env` 指向的环境变量、配置/PATH 中的 `mc-mcp` CLI，或仓内
`services/mc-mcp/src/mcp/cli.js`。环境 token 优先于所有 CLI；仓内入口通过 PATH
中的 `node` 执行，只调用 `service ensure` 来取得服务描述符；它不直接启动 bot
或 Compose。

首次克隆后先执行：

```powershell
npm ci --prefix services/mc-mcp
```

运行请求不会自动联网安装依赖。缺少 Node、仓内 CLI 或服务依赖时，桥接层分别
返回 `MC_MCP_NODE_NOT_FOUND`、`MC_MCP_REPO_CLI_NOT_FOUND` 或
`MC_MCP_DEPENDENCIES_NOT_INSTALLED`。`mcp.cli_command` 可写成字符串；需要固定多个
argv 时使用 YAML 列表，例如 `['node', 'path/to/cli.js']`。

## 外部 MCP 桥

产品运行时的 MCP 客户端支持三种 transport：

| transport | 必需配置 | 可选配置 |
|-----------|----------|----------|
| `stdio` | 原生模式使用 `command`；Docker 模式使用 `sandbox.type=docker` 与 `sandbox.image` | `args[]`、`env`；Docker 模式还支持 mounts、memory、cpus |
| `sse` | `url` | `headers`、`timeout`、`sse_read_timeout` |
| `streamable_http` | `url` | `headers`、`timeout` |

`MCPManager` 会连接 `config/tools.yaml` 的 `mcp_servers`，读取工具 schema，并转换为 LangChain Tool。当前 filesystem 示例在 Docker 沙箱中只挂载 `./data:/data:rw`。开发智能体 MCP 不得放入这份产品配置。

## Bilibili MCP

`tooling/bilibili_mcp` 是开发智能体使用的 stdio MCP。它只控制本机 Animetta 后端持有的唯一直播会话，不启动 Animetta，也不直接连接 Bilibili。后端 URL 来自 `ANIMETTA_MCP_URL`，只允许 `127.0.0.1`、`localhost` 或 `::1` 的 HTTP(S) URL，禁止 URL 内凭据、query 和 fragment。

| MCP 工具 | 参数 | 行为 |
|----------|------|------|
| `bilibili_get_status` | 无 | 返回最后一个权威 `bilibili:danmaku_status` |
| `bilibili_connect` | `room_id:int`、`timeout_seconds=30` | 从 stopped/error 连接房间并等待 prelive/live/error |
| `bilibili_switch_room` | `room_id:int`、`timeout_seconds=30` | 使用 generation 乐观并发原子切房 |
| `bilibili_disconnect` | `timeout_seconds=10` | 停止后端直播会话，不关闭 MCP transport |
| `bilibili_wait_for_state` | `target_state:string`、`timeout_seconds=30` | 等待指定状态推送 |
| `bilibili_get_recent_events` | `limit=50`、`event_types?:string[]` | 返回当前 generation 最近的规范化直播事件；limit 1..100 |

统一结果：

```json
{
  "ok": true,
  "error_code": null,
  "message": "...",
  "status": {},
  "events": []
}
```

失败时 `ok=false`，`error_code` 可能为 `backend_unavailable`、`status_unavailable`、`invalid_room_id`、`invalid_timeout`、`invalid_state`、`invalid_limit`、`invalid_event_types`、`protocol_error`、`command_rejected`、`timeout` 或后端会话错误码。

房间命令的 Socket.IO ack 只代表“已接受”。MCP 会继续等待 generation 增加并到达目标状态后才返回成功，因此调用方不需要自行拼接 ack 与状态推送。

## 添加工具

1. 产品工具放在 `src/animetta/tools/`，使用 `@tool` 与精确 schema；按需加入 `config/tools.yaml`。
2. Minecraft 能力必须保持 `mc_connection` 与 `mc_operate_bot` 两工具表面，扩展 typed 内部契约而不是增加随意命令。
3. 开发能力放在 `tooling/<capability>_mcp/`，使用中文工具描述和用户消息，不注册到产品运行时。
4. 对有副作用的工具提供幂等 ID、明确错误码和可查询进度，不把“请求已接收”描述成“操作已完成”。
