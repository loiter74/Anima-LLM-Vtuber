# Architecture

> For design decisions, see [Architecture Decision Records (ADRs)](../adrs/).

---

## System Context (C4 Level 1)

```mermaid
graph TB
    User([User])
    subgraph "Animetta System"
        FE[Vue3 Frontend<br/>Electron + Web]
        BE[Starlette ASGI Backend<br/>Socket.IO + REST]
        LG[LangGraph Engine<br/>State Graph]
    end
    subgraph "External Services"
        LLM[LLM Providers<br/>DeepSeek / GLM / OpenAI / Ollama]
        TTS[TTS Providers<br/>Edge / GLM / VibeVoice]
        ASR[ASR Providers<br/>Whisper / GLM / FunASR]
    end
    subgraph "Data Stores"
        SQL[(SQLite FTS5<br/>Keyword Index)]
        VDB[(Chroma<br/>Vector DB)]
        MD[(Markdown Files<br/>Conversation Logs)]
    end

    User -->|text/audio| FE
    FE -->|Socket.IO| BE
    BE --> LG
    LG -->|API calls| LLM
    LG -->|API calls| TTS
    LG -->|API calls| ASR
    LG -.->|RAG| VDB
    LG -.->|search| SQL
    LG -.->|store| MD
```

---

## Container Diagram (C4 Level 2)

```mermaid
graph TB
    subgraph "Frontend (Electron + Vue3)"
        UI[Chat UI<br/>Vue 3 + UnoCSS]
        L2D[Live2D Renderer<br/>pixi-live2d-display]
        DASH[Dashboard<br/>Chart.js + vue-chartjs]
    end
    subgraph "Backend (Starlette + Socket.IO ASGI)"
        SIO[Socket.IO Server<br/>Event Router]
        SM[Session Manager<br/>Per-user Orchestrator]
        LG[LangGraph Engine<br/>6 Graph Nodes]
        SC[Service Context<br/>Provider Container]
        STATS[Stats API<br/>REST Endpoints]
    end
    subgraph "Storage"
        SS[(StatsStore<br/>SQLite)]
        MS[(Memory Store<br/>SQLite FTS5)]
        VS[(Vector Store<br/>Chroma)]
        FS[(File System<br/>Markdown)]
    end

    UI -->|WebSocket| SIO
    DASH -->|HTTP GET| STATS
    SIO --> SM
    SM --> LG
    LG --> SC
    LG -.->|records traces| SS
    STATS -.->|queries| SS
    LG -.->|store/retrieve| MS
    LG -.->|vector search| VS
    LG -.->|persist| FS
```

---

## Sequence Diagram: Full Request Lifecycle

```mermaid
sequenceDiagram
    actor User
    participant FE as Vue3 Frontend
    participant BE as Starlette ASGI Backend
    participant LG as LangGraph Engine
    participant Mem as Memory System
    participant LLM as LLM Provider
    participant TTS as TTS Provider

    User->>FE: Type message / Speak
    FE->>BE: text_input / raw_audio_data

    alt Audio Input
        BE->>LG: asr_node
        LG->>ASR: transcribe(audio)
        ASR-->>LG: text
        LG-->>BE: user_text
    end

    BE->>LG: llm_node
    LG->>Mem: retrieve_context(query)
    Mem-->>LG: relevant history + facts
    LG->>LLM: generate(prompt + context)
    LLM-->>LG: stream tokens
    LG-->>BE: token chunks
    BE-->>FE: text event (streaming)

    alt Tool Calls
        LG->>LG: tool_node
        LG-->>LG: tool results
        LG->>LLM: generate(prompt + results)
        LLM-->>LG: final response
    end

    LG->>TTS: synthesize(response)
    TTS-->>LG: audio data
    LG->>LG: emotion_node
    LG->>LG: output_node
    LG-->>BE: text + audio + emotion
    BE-->>FE: text, audio_with_expression, expression events
    LG->>Mem: store_turn(conversation)
    FE->>User: Display response + animate Live2D
```

---

## LangGraph State Machine

```mermaid
graph TD
    START([START]) --> route_input{route_input}
    route_input -->|audio| asr_node[asr_node<br/>Speech Recognition]
    route_input -->|text| llm_node[llm_node<br/>LLM Reasoning + RAG]
    asr_node --> llm_node

    llm_node -->|tool_calls| tool_node[tool_node<br/>Tool Execution]
    tool_node -->|results| llm_node

    llm_node -->|response| tts_node[tts_node<br/>Text-to-Speech]

    tts_node --> emotion_node[emotion_node<br/>Emotion Analysis]
    emotion_node --> output_node[output_node<br/>Socket.IO + Memory Storage]
    output_node --> END([END])

    llm_node -.->|RAG query| Memory[Memory System<br/>Hybrid Search]
    Memory -.->|context| llm_node
```

### State: `AgentState` (TypedDict)

```
{
  input_type: "text" | "audio",
  raw_audio: Optional[bytes],
  user_text: str,
  messages: Sequence[BaseMessage],       # annotated with add_messages
  system_prompt: Optional[str],
  response_text: str,
  response_chunks: List[str],            # streaming tokens
  tts_audio: Optional[bytes | str],
  emotion: Optional[str],
  tool_calls: Optional[List[Dict]],
  tool_results: Optional[List[Dict]],
  session_id: str,
  metadata: Dict[str, Any],
}
```

---

## Core Components

### 1. LangGraph State Graph (`src/animetta/orchestration/graph/`)

| Node | Input | Output | Responsibility |
|------|-------|--------|----------------|
| `asr_node` | `raw_audio` | `user_text` | Speech recognition via configured ASR provider |
| `llm_node` | `user_text`, `messages` | `response_text`, `tool_calls` | LLM reasoning + RAG memory injection |
| `tts_node` | `response_text` | `tts_audio` | Text-to-speech via configured TTS provider |
| `emotion_node` | `response_text` | `emotion` | Sentiment analysis (keyword + LLM-based) |
| `output_node` | all state | Socket.IO events | Distribution + memory storage |
| `tool_node` | `tool_calls` | `tool_results` | Tool execution (built-in + MCP) |

Two execution paths:
- **Direct**: `llm_node → tts_node → emotion_node → output_node`
- **Tool-calling**: `llm_node → tool_node → llm_node → ... → output_node`

### 2. Service Registry (`src/animetta/config/core/registry.py`)

Decorator-based plugin system ([ADR-003](../adrs/ADR-003-plugin-architecture.md)):

```python
@ProviderRegistry.register_service("llm", "openai")
class OpenAILLM(LLMInterface): ...
```

Config-driven selection:
```yaml
services:
  agent: deepseek    # picks LLM provider
  tts: edge          # picks TTS provider
  asr: mock          # picks ASR provider
```

### 3. Memory System (`src/animetta/memory/`)

Wiki-architecture ([ADR-005](../adrs/ADR-005-wiki-memory.md)) with three storage layers:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Short-term | In-memory (20 turns) | Recent conversation context |
| Long-term | Markdown files | Human-readable source of truth |
| Vector index | Chroma | Semantic search (70% weight) |
| Keyword index | SQLite FTS5 | BM25 keyword search (30% weight) |
| Fact store | SQLite | Structured memory with versioning |

Retrieval: **Hybrid search** ([ADR-002](../adrs/ADR-002-hybrid-search.md)) with weighted fusion:
```
score = 0.7 × vector_similarity + 0.3 × bm25_score
```

### 4. Tool System (`src/animetta/tools/`)

Three tool sources:
- **Built-in**: `web_search`, `get_current_time`, `calculator`, `get_weather`
- **LangChain tools**: Python REPL, extensible via config
- **MCP tools**: Docker-sandboxed external servers via Model Context Protocol

### 5. WebSocket Server (`src/animetta/orchestration/server/`)

Starlette + Socket.IO ASGI app:
- Event-based communication (`text_input`, `raw_audio_data`, `interrupt_signal`)
- Session management (per-user orchestrator instances via `SessionManager`)
- Desktop client tracking (`DesktopClientManager`)
- Live2D action/motion control (`Live2DManager`)
- Stats REST API (`GET /api/stats/*`, `GET /health`)

---

## Data Flow (Text Input)

```
1. Client sends text_input via WebSocket
2. Route handler creates/gets session → LangGraphOrchestrator
3. Orchestrator runs state graph:
   a. llm_node: calls LLM, injects RAG memory context
   b. (optional) tool_node: executes tool calls, feeds back to LLM
   c. tts_node: synthesizes speech (if TTS enabled)
   d. emotion_node: extracts emotion from response
   e. output_node: emits events to frontend, stores to memory
4. Response streamed to client via Socket.IO events (text + audio + expression)
```

---

## Configuration Layering

```yaml
config/animetta.yaml     # Canonical profiles, provider declarations, and runtime policy
config/personas/         # Character personality definitions
config/tools.yaml        # Tool and MCP server configuration
.env                     # Selected profile, endpoints, and secrets only
```

---

## Architecture Decision Records

| ID | Decision | Key Alternative |
|----|----------|-----------------|
| [ADR-001](../adrs/ADR-001-langgraph-over-eventbus.md) | LangGraph over EventBus | Direct orchestration, Message queue |
| [ADR-002](../adrs/ADR-002-hybrid-search.md) | Chroma + SQLite FTS5 | Pinecone, Weaviate, Pure vector |
| [ADR-003](../adrs/ADR-003-plugin-architecture.md) | Decorator-based plugin registry | Factory pattern, DI container |
| [ADR-004](../adrs/ADR-004-streaming-response.md) | Streaming-first design | Buffered response, Polling |
| [ADR-005](../adrs/ADR-005-wiki-memory.md) | Wiki-architecture memory | Buffer-only, Chroma-only |

---

## Ports

| Service | Port | Protocol |
|---------|------|----------|
| Backend | 12394 | Socket.IO + HTTP |
| Dashboard | 12394 | `GET /api/stats/*` |
| Web Config | 8080 | HTTP |
| Frontend | Electron | IPC |
