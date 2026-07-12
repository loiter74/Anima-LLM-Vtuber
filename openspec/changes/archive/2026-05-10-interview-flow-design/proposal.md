# Interview Flow Design — AI Orchestration Engine Narrative

**Date:** 2026-05-10
**Target:** Backend/Architecture roles
**Duration:** 15 minutes + Q&A

## Storyline

> "I built an AI orchestration engine. Same state machine + plugin system drives a VTuber, a livestream host, and a Minecraft bot. The engine itself is production-grade — full-chain observability, 81 tests, every architecture decision documented."

## Flow

| Step | Time | Focus | Mode |
|------|------|-------|------|
| 1 🎭 Hook | 2min | VTuber chat demo — streaming + Live2D expression | Live demo |
| 2 🧩 Core | 3min | LangGraph state machine: 7 nodes, conditional edges, streaming | Code + diagram |
| 3 🔌 Power | 2min | Plugin architecture: `@ProviderRegistry`, open-closed principle | Code walkthrough |
| 4a 📺 | 1.5min | Bilibili livestream danmaku — same engine, different input | Live demo |
| 4b 🎮 | 1.5min | Minecraft bot — parallel subprocess, state sync via buffer | Code explanation |
| 5 🧠 | 2min | Memory system: Hybrid Search → FuzzyLayer → MemePool | README diagram |
| 6 📊 | 3min | Dashboard + Stats API + 81 tests + CI/CD + 5 ADRs | Demo + code |

## Key Talking Points Per Step

### Step 1 — Hook
- "This isn't a ChatGPT wrapper — every conversation is orchestrated by a LangGraph state machine"
- Transition: "Let me show you how the engine works under the hood"

### Step 2 — LangGraph Core
- 7 nodes, each a pure function `state → state_update`, independently testable
- Conditional edges: tool calling is a first-class graph branch
- `astream()` for end-to-end streaming
- Backup: if asked "why not EventBus" → ADR-001

### Step 3 — Plugin Architecture
- `interface.py` ABC → implementation → `@ProviderRegistry.register_service` → factory
- New LLM = 2 files + 2 decorators, zero framework code changes
- Same pattern for ASR, TTS, VAD
- Backup: ADR-003

### Step 4a — Livestream
- Same LangGraph state machine driving danmaku interaction
- "Change the character, not the engine"

### Step 4b — Minecraft
- Bot runs as independent Node.js subprocess (parallel by design)
- State buffer accumulates bot events between conversation turns
- Information exchange at LLM node: read buffer, inject into context
- "30 lines of code to make the LLM aware of the Minecraft world"

### Step 5 — Memory Depth
- Layer 1: Hybrid Search (70% vector + 30% BM25) — ADR-002
- Layer 2: FuzzyLayer tiered injection (context → support → precision)
- Layer 3: MemePool time-decay + Periodic Learner auto-evolution
- "Markdown is the source of truth — auditable and versionable" — ADR-005

### Step 6 — Engineering Quality
- Dashboard: latency breakdown per node, token usage, error rate
- StatsCallbackHandler auto-collects traces — zero instrumentation code
- 81 tests, mock fixtures for ALL external services in conftest.py
- CI: Python 3.12/3.13 matrix, mypy strict, ruff
- 5 ADRs: every architecture decision traceable

## Backup Q&A Reserve

Existing `docs/demo/interview-qa.md` covers 71 anticipated questions across:
- Architecture & Design (LangGraph, plugins, scaling)
- AI Engineering (LLM quality, memory, failure handling)
- Testing & Quality (mocking strategy, test pyramid)
- Operations (debugging, deployment)

## Demo Preparation Checklist

- [ ] Pre-warm: run Anima before interview starts
- [ ] Have 2-3 previous conversations saved (memory recall demo)
- [ ] Keep Dashboard open (accumulate live traces)
- [ ] Bilibili room configured and test danmaku received
- [ ] Know your numbers: P50 latency, token usage, test count
- [ ] `ARCHITECTURE.md` and `docs/adrs/` ready to open
