# Animetta 工具系统使用说明

## 概述

Animetta 工具系统为 AI Agent 提供工具调用能力，支持 LLM（如 GLM-4）调用外部工具获取实时信息或执行操作。

## 支持的功能

1. **内置工具**: 预定义的工具（web_search, get_weather, read_file, get_current_time 等）
2. **LangChain 集成**: 与 LangChain 工具生态无缝集成
3. **MCP 桥接**: 通过 MCP 协议连接外部工具服务器（实验性）

## 目录结构

```
src/animetta/tools/
├── __init__.py          # 模块导出
├── base.py              # 内置工具定义和注册表
├── config.py            # 工具配置加载器
├── langchain_tools.py   # LangChain 工具适配
├── mcp_bridge.py        # MCP 协议桥接（实验性）
└── custom_tools.py      # 自定义工具示例
```

## 内置工具

| 工具名称 | 功能 | 参数 | 需要密钥 |
|---------|------|------|---------|
| `web_search` | 互联网搜索 | `query: str`, `num_results: int = 5` | ❌ |
| `get_weather` | 查询天气 | `city: str` | ❌ |
| `read_file` | 读取文件 | `file_path: str`, `max_length: int = 2000` | ❌ |
| `get_current_time` | 获取当前时间 | `timezone: str = "Asia/Shanghai"` | ❌ |
| `list_directory` | 列出目录 | `directory: str = "."` | ❌ |
| `calculator` | 数学计算 | `expression: str` | ❌ |

> 注：所有内置工具都设计为不需要 API 密钥，使用公开数据源或模拟数据。

## 配置文件

`config/tools.yaml`:

```yaml
# 启用的内置工具
builtin_tools:
  - web_search
  - get_current_time
  - calculator

# MCP 服务器配置（实验性）
mcp_servers:
  - name: "filesystem"
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "./data"]

# 工具调用设置
tool_settings:
  enable_tools: true  # 是否启用工具调用
  max_tool_calls_per_turn: 5
  tool_execution_timeout: 30
```

## LangGraph 集成

工具调用已完全集成到 LangGraph 状态图中。

### 数据流

```
用户输入 → [route_input]
              ↓
          [llm_node] → LLM 决定是否调用工具
              ↓
         (有 tool_calls?)
              ├─ 是 → [tool_node] → 执行工具 → 返回 ToolMessage
              │                              ↓
              └──────────────────────────────┤
                                             ↓
                                        [llm_node] → LLM 基于工具结果生成回复
                                             ↓
                                        [tts_node] → [output_node]
```

### 启用工具调用

1. 在 `config/tools.yaml` 中设置 `enable_tools: true`
2. 在 `builtin_tools` 中列出要启用的工具
3. 重启后端

### 配置说明

工具配置通过 `SessionManager._load_tools_config()` 加载：

```python
# src/animetta/server/session.py
tools_config = load_tools_config()
enable_tools = tools_config.get("tool_settings", {}).get("enable_tools", False)

# 存储到 ConfigStore 供 llm_node 使用
ConfigStore.set(session_id, "enable_tools", enable_tools)
ConfigStore.set(session_id, "chat_model", chat_model)
```

## 使用示例

### 测试工具调用

启动后端后，在聊天窗口输入：

```
现在几点了？
```

预期行为：
1. LLM 返回 `tool_calls: [{"name": "get_current_time", ...}]`
2. `tool_node` 执行工具，返回 `2026-03-22 14:30:00`
3. LLM 基于工具结果回复：`现在是下午两点半...`

### 代码示例

```python
from animetta.tools.base import create_tool_registry
from animetta.tools.config import load_tools_config

# 加载配置
tools_config = load_tools_config()

# 创建工具注册表
tools, tools_map = create_tool_registry(
    builtin_enabled=tools_config.get("builtin_tools", []),
)

# 直接调用工具
result = await tools_map["calculator"].ainvoke({"expression": "2 + 2"})
print(result)  # "4"
```

### 自定义工具

```python
from langchain_core.tools import tool
from animetta.tools.base import create_tool_registry

@tool
async def my_custom_tool(param: str) -> str:
    """自定义工具描述。

    Args:
        param: 参数说明
    """
    return f"结果: {param}"

# 注册工具
tools, tools_map = create_tool_registry(
    builtin_enabled=["calculator"],
    extra_tools=[my_custom_tool],
)
```

## 技术实现

### GLM-4 工具调用格式

```python
# 工具定义（发送给 LLM）
{
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "获取当前时间",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "时区"}
            },
            "required": []
        }
    }
}

# 工具调用（LLM 返回）
{
    "id": "call_123",
    "type": "function",
    "function": {
        "name": "get_current_time",
        "arguments": "{\"timezone\": \"Asia/Shanghai\"}"
    }
}

# 工具结果（发送回 LLM）
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "2026-03-22 14:30:00"
}
```

### 关键文件

| 文件 | 功能 |
|------|------|
| `src/animetta/graph/nodes/llm_node.py` | LLM 推理节点，处理工具调用 |
| `src/animetta/graph/nodes/tool_node.py` | 工具执行节点 |
| `src/animetta/services/llm/implementations/glm_llm.py` | GLM-4 工具调用实现 |
| `src/animetta/tools/base.py` | 内置工具定义 |
| `src/animetta/tools/config.py` | 配置加载 |

## 故障排除

### 问题：工具没有被调用

**症状**：输入 "现在几点了？"，LLM 回复 "我无法获取当前时间"

**检查步骤**：

1. 检查配置是否启用：
```bash
# 查看日志
grep "enable_tools" logs/animetta.log
# 应该看到: enable_tools=True
```

2. 检查工具是否加载：
```bash
# 查看日志
grep "工具调用已启用" logs/animetta.log
# 应该看到: 工具调用已启用，加载 X 个工具
```

3. 检查 LLM 模型：
```bash
# 确认使用的是 GLM-4 系列（支持工具调用）
grep "model=" config/services.yaml
```

### 问题：工具调用报错

**错误**：`Error code: 400, {"error":{"code":"1214","message":"工具类型不能为空"}}`

**原因**：tool_calls 格式不正确

**解决**：确保使用最新版本，已修复 GLM API 格式问题

### 问题：无限循环调用工具

**症状**：LLM 不断请求调用同一个工具

**原因**：工具结果没有正确传递回 LLM

**解决**：检查 `_convert_langchain_message_to_glm()` 是否正确处理 ToolMessage

## 依赖

- `langchain-core >= 0.3.0`: LangChain 核心库
- `zhipuai >= 2.0.0`: 智谱 AI SDK（GLM-4）
- `mcp >= 0.1.0`: MCP 协议支持（可选）

## 注意事项

1. **工具安全性**: 工具可以访问文件系统和网络，请谨慎配置
2. **LLM 限制**: 只有 GLM-4 系列模型支持工具调用
3. **超时控制**: 建议为工具调用设置合理的超时时间
4. **MCP 可选**: 如果未安装 `mcp` 包，MCP 功能会被跳过

## 下一步

- [ ] 添加更多内置工具
- [ ] 完善 MCP 协议支持
- [ ] 添加工具权限管理
- [ ] 支持工具组合调用
- [ ] 添加工具调用日志和监控
