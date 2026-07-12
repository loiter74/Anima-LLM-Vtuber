# Interview Demo Walkthrough

**Total time:** 15 minutes + Q&A
**Story:** AI Orchestration Engine — same LangGraph + plugin system drives VTuber, livestream, and Minecraft bot
**Target:** Backend/Architecture roles

---

## Step 1: Hook — VTuber Chat (2 min)

**Action:** Open Anima, type a message, show the full interaction.

**What to show:**
- Text input → streaming response (token by token)
- Live2D avatar reacts with appropriate emotion
- TTS audio plays

**Story:**
> "This isn't a ChatGPT wrapper. Every conversation is orchestrated by a LangGraph state machine. Let me show you how the engine works under the hood."

---

## Step 2: Core — LangGraph State Machine (3 min)

**Action:** Open `orchestration/graph/builder.py`

**What to show:**
- 7 nodes + conditional edges + `astream()` streaming
- Each node is a pure function: `state → state_update`
- `should_use_tools()` conditional edge — tool calling is first-class, not a hack

**Story:**
> "Every node is independently testable — mock the external services, test the logic. That's the power of a state machine over event-driven: you always know what state the system is in. If the interviewer asks why not EventBus, we did use it originally — ADR-001 documents the migration."

---

## Step 3: Power — Plugin Architecture (2 min)

**Action:** Open `services/intelligence/llm/interface.py` → `glm_llm.py` → `config/core/registry.py`

**What to show:**
- ABC interface → implementation → `@ProviderRegistry.register_service` → factory
- Same pattern for LLM, ASR, TTS, VAD

**Story:**
> "Adding a new LLM takes two files and two decorators. Zero framework code changes. This is ADR-003 — open-closed principle applied to AI providers. Every provider has a mock and tests, so we can validate new integrations without real API keys."

---

## Step 4a: Flexibility — Bilibili Livestream (1.5 min)

**Action:** Open the danmaku panel, show live comments flowing in.

**What to show:**
- Viewer sends danmaku → AI reads and responds in real-time
- Same LangGraph state machine driving the interaction

**Story:**
> "Same engine, different input channel. The VTuber chat and the livestream danmaku interaction run on the identical state machine. Change the character, not the engine."

---

## Step 4b: Flexibility — Minecraft Bot (1.5 min)

**Action:** Open `tools/minecraft/bridge.py` (code explanation only, no live demo)

**What to show:**
- Python ↔ Node.js Mineflayer bot via JSON over stdin/stdout
- Bot runs as independent subprocess (parallel by design)
- State buffer accumulates bot events between conversation turns

**Story:**
> "The Minecraft bot is a separate Node.js process — it's always running, always perceiving the world. Information exchange with the conversation LLM happens through a state buffer: at the LLM node, we read the latest bot state and inject it into context. 30 lines of code to make an LLM aware of a Minecraft world. Same engine."

---

## Step 5: Depth — Memory System (2 min)

**Action:** Open README memory architecture section

**What to show:**
- Layer 1: Hybrid Search — 70% vector + 30% BM25 (ADR-002)
- Layer 2: FuzzyLayer — tiered context injection (context → support → precision)
- Layer 3: MemePool — time-decay scoring + Periodic Learner auto-evolution

**Story:**
> "Most projects stop at 'connect a vector DB.' This has three layers. The key insight is ADR-005: Markdown is the source of truth. Vector indexes are acceleration layers. That means memory is auditable and versionable — you can `git diff` your AI's knowledge base."

---

## Step 6: Quality — Engineering Practices (3 min)

### 6a. Dashboard + Observability (1 min)

**Action:** Open Dashboard page

**What to show:**
- KPI cards, latency breakdown per node, token usage, error rate, session timeline

**Story:**
> "Every conversation trace is auto-collected by StatsCallbackHandler — zero instrumentation code. LangGraph's callback mechanism handles it. SQLite-backed, REST API exposed."

### 6b. Testing + CI (1 min)

**Action:** Open `tests/conftest.py`, show CI badge

**What to show:**
- 81 tests, all external services mocked in conftest.py
- `mock_llm`, `mock_tts`, `mock_asr`, `mock_vad` fixtures
- GitHub Actions: canonical Python 3.13 from `.python-version`, mypy strict, ruff

### 6c. ADRs (1 min)

**Action:** Open `docs/adrs/` directory

**What to show:**
- 5 Architecture Decision Records
- Each has: Context, Decision, Alternatives Considered, Consequences

**Story:**
> "This is the part I'm most proud of. Every architecture decision is documented — why LangGraph over EventBus, why Chroma over Pinecone. Architecture isn't gut feeling. It's traceable."

---

## Pro Tips

1. **Pre-warm**: Run Anima before the interview starts
2. **Save conversations**: Have 2-3 conversations saved for memory recall
3. **Keep Dashboard open**: Let traces accumulate for live data
4. **Pre-test danmaku**: Bilibili room configured, test message received
5. **Know your numbers**: P50 latency, token usage, test count
6. **ADR ready**: `ARCHITECTURE.md` and `docs/adrs/` open in tabs
7. **Pacing**: Steps 1-3 are the core — if time is tight, compress 4-5, never skip 6
