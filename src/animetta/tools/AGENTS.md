# TOOLS — TOOL CALLING + MCP + MINECRAFT

**Generated:** 2026-05-31
**Commit:** cdd4a87

> Parent: [../AGENTS.md](../AGENTS.md) — backend-wide conventions.

## OVERVIEW

LLM tool calling system with built-in tools (calculator, web search, file I/O), MCP protocol bridge for external tool servers, and Minecraft bot integration. ⚠️ The Minecraft bot is a Node.js package embedded inside the Python tree.

## STRUCTURE

```
tools/
├── base.py                  # Built-in tools: calculator, web_search, get_weather, read_file, get_current_time, list_directory
├── custom_tools.py          # User-defined custom tools — add new tools here
├── langchain_tools.py       # LangChain tool adapter
├── mcp_bridge.py            # MCP protocol bridge — connects to external MCP servers
├── audio_tools.py           # Audio-related tools
├── config.py                # Tool configuration loader (from config/tools.yaml)
└── minecraft/               # ⚠️ Node.js bot inside Python tree!
    ├── bridge.py            #   Python ↔ Node.js IPC bridge
    ├── tools.py             #   Minecraft tool definitions (mine, build, navigate, etc.)
    ├── autonomous.py        #   Autonomous agent controller
    ├── planner.py           #   Action planner
    ├── config.py            #   Minecraft config
    ├── rules_engine.py      #   Behavior rules engine
    ├── world_state.py       #   World state tracker
    └── bot/                 #   ⚠️ Node.js package: package.json, index.js, behaviors/, scripts/
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add built-in tool | `base.py` | Use `@tool` decorator, add to config/tools.yaml |
| Add custom tool | `custom_tools.py` | User-defined, registered at runtime |
| Connect MCP server | `mcp_bridge.py` | Configure in config/tools.yaml under mcp_servers |
| Minecraft bot logic | `minecraft/bot/index.js` | ⚠️ JavaScript — cross-language IPC via bridge.py |
| Minecraft tool defs | `minecraft/tools.py` | Python-side tool definitions for LLM |
| Tool configuration | `config.py` + `config/tools.yaml` | Enable/disable tools, MCP servers, settings |

## KEY PATTERNS

- **@tool decorator**: LangChain `@tool` for built-in tools — auto-discovered by tool_manager
- **MCP bridge**: stdio transport to external MCP servers, tools exposed via mcp_bridge
- **Cross-language Minecraft**: Python bridge.py spawns Node.js process, communicates via JSON over stdin/stdout
- **Tool config**: config/tools.yaml → tool_config.py → ToolManager in orchestration/graph/

## ANTI-PATTERNS

- ❌ Never modify minecraft/bot/ Node.js code from the Python side — use bridge.py IPC
- ❌ Never add tools without corresponding config in config/tools.yaml
- ❌ Do not remove minecraft/ thinking it's "just a bot" — it's cross-language, removal breaks imports

## NOTES

- Minecraft bot is a Mineflayer (Node.js) bot — the ONLY JavaScript code in the Python backend
- MCP bridge supports stdio transport only; HTTP/SSE not yet implemented
- Tool execution timeout: 30s (configurable in tools.yaml)
- Max 5 tool calls per LLM turn
