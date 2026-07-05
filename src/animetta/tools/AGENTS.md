# TOOLS — TOOL CALLING + MCP + MINECRAFT

**Generated:** 2026-05-31
**Commit:** cdd4a87

> Parent: [../AGENTS.md](../AGENTS.md) — backend-wide conventions.

## OVERVIEW

LLM tool calling system with built-in tools (calculator, web search, file I/O), MCP protocol bridge for external tool servers, and Minecraft bot integration. The Minecraft action bot now runs as the external Node.js project `C:/Users/30262/Project/voyager-mc-bot`; Anima owns the Python bridge, Minecraft adapters, and generic game-bot contracts.

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
    ├── core/bridge.py       #   Python ↔ external Node.js runtime IPC bridge
    ├── core/tools.py        #   Minecraft tool definitions (mine, build, navigate, etc.)
    ├── autonomous/          #   Autonomous agent controller
    ├── skill/               #   Voyager-style skill models and execution
    ├── survival/            #   Iron-survival runner
    └── tech_tree/           #   Tech-tree progression runner
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add built-in tool | `base.py` | Use `@tool` decorator, add to config/tools.yaml |
| Add custom tool | `custom_tools.py` | User-defined, registered at runtime |
| Connect MCP server | `mcp_bridge.py` | Configure in config/tools.yaml under mcp_servers |
| Minecraft bot logic | `C:/Users/30262/Project/voyager-mc-bot/src/index.js` | JavaScript runtime — cross-language IPC via `minecraft/core/bridge.py` |
| Minecraft tool defs | `minecraft/tools.py` | Python-side tool definitions for LLM |
| Tool configuration | `config.py` + `config/tools.yaml` | Enable/disable tools, MCP servers, settings |

## KEY PATTERNS

- **@tool decorator**: LangChain `@tool` for built-in tools — auto-discovered by tool_manager
- **MCP bridge**: stdio transport to external MCP servers, tools exposed via mcp_bridge
- **Cross-language Minecraft**: Python `minecraft/core/bridge.py` spawns the configured external Node.js process and communicates via JSON over stdin/stdout
- **Tool config**: config/tools.yaml → tool_config.py → ToolManager in orchestration/graph/

## ANTI-PATTERNS

- ❌ Never reintroduce a Node.js runtime under `src/animetta/tools/minecraft/bot/` without a new migration plan
- ❌ Never add tools without corresponding config in config/tools.yaml
- ❌ Do not remove minecraft/ thinking it's "just a bot" — it's cross-language, removal breaks imports

## NOTES

- Minecraft bot is a Mineflayer (Node.js) runtime in `C:/Users/30262/Project/voyager-mc-bot`; Anima launches it through `config/tools.yaml` runtime settings
- MCP bridge supports stdio transport only; HTTP/SSE not yet implemented
- Tool execution timeout: 30s (configurable in tools.yaml)
- Max 5 tool calls per LLM turn
