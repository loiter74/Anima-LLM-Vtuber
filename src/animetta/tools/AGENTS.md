# TOOLS — TOOL CALLING + MCP + MINECRAFT

**Generated:** 2026-05-31
**Commit:** cdd4a87

> Parent: [../AGENTS.md](../AGENTS.md) — backend-wide conventions.

## OVERVIEW

LLM tool calling system with built-in tools, MCP protocol bridges, and Minecraft control-plane integration. The independent `mc-mcp` service owns Minecraft runtime resources; Anima owns mission planning, durable projections and the typed MCP adapter.

## STRUCTURE

```
tools/
├── base.py                  # Built-in tools: calculator, web_search, get_weather, read_file, get_current_time, list_directory
├── custom_tools.py          # User-defined custom tools — add new tools here
├── langchain_tools.py       # LangChain tool adapter
├── mcp_bridge.py            # MCP protocol bridge — connects to external MCP servers
├── audio_tools.py           # Audio-related tools
├── config.py                # Tool configuration loader (from config/tools.yaml)
├── gamebot/                 # Generic game-bot contracts, client, and stdio transport
└── minecraft/               # Minecraft-specific Python adapters and orchestration
    ├── core/bridge.py       #   Streamable HTTP mc-mcp client
    ├── core/tools.py        #   mc_connection + mc_operate_bot
    ├── skill/               #   Voyager-style Skill IR and trust
    ├── survival/            #   Typed deterministic workflows
    └── tech_tree/           #   Evidence-backed technology graph
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add built-in tool | `base.py` | Use `@tool` decorator, add to config/tools.yaml |
| Add custom tool | `custom_tools.py` | User-defined, registered at runtime |
| Connect MCP server | `mcp_bridge.py` | Configure in config/tools.yaml under mcp_servers |
| Minecraft MCP adapter | `minecraft/core/bridge.py` | Loopback Streamable HTTP only |
| Minecraft tool defs | `minecraft/core/tools.py` | Exact two-capability public surface |
| Tool configuration | `config.py` + `config/tools.yaml` | Enable/disable tools, MCP servers, settings |

## KEY PATTERNS

- **@tool decorator**: LangChain `@tool` for built-in tools — auto-discovered by tool_manager
- **MCP bridge**: stdio transport to external MCP servers, tools exposed via mcp_bridge
- **Cross-language Minecraft**: Python connects to the independently managed `mc-mcp` Streamable HTTP service
- **Tool config**: config/tools.yaml → tool_config.py → ToolManager in orchestration/graph/

## ANTI-PATTERNS

- ❌ Never reintroduce a Node.js runtime under `src/animetta/tools/minecraft/bot/` without a new migration plan
- ❌ Never add tools without corresponding config in config/tools.yaml
- ❌ Do not remove minecraft/ thinking it's "just a bot" — it's cross-language, removal breaks imports

## NOTES

- Anima never launches Minecraft Node or Compose directly; mc-mcp profiles own those policies
- MCP bridge supports stdio, SSE and Streamable HTTP transports
- Tool execution timeout: 30s (configurable in tools.yaml)
- Max 5 tool calls per LLM turn
