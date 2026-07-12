# Enterprise-Grade Upgrade: Anima Project

**Date:** 2026-05-01
**Author:** Sisyphus (AI Orchestrator)
**Status:** Design Approved — Ready for Implementation Planning
**Target Role:** AI Application / LLM Engineer
**Timeline:** 8 Weeks

## Strategic Approach

**Chosen: Layered progression (B).** Three layers build on each other, each leaving
the project in a deliverable state:

```
Layer 1: Infrastructure  (Weeks 1-2) — quality foundation
    ↓
Layer 2: AI Capability  (Weeks 3-6) — core differentiator
    ↓
Layer 3: Delivery       (Weeks 7-8) — interview packaging
```

## Layer 1: Infrastructure (Weeks 1-2)

Goal: Every line of new code has quality guarantees. First impression when an
interviewer opens the repo: "This engineer has good habits."

### 1.1 Test Infrastructure (Week 1)

Current state: pytest available, 28 tests, no asyncio config, no coverage, no
conftest.py with shared fixtures.

Deliverables:
- `pyproject.toml` configures pytest (asyncio_mode=auto, testpaths, markers)
- `pytest-cov` added, coverage floor set at 70% (ratcheting to 85%)
- `conftest.py` with global fixtures: mock LLM, mock TTS, mock ASR, mock VAD, mock Socket.IO
- GitHub Actions: `pytest --cov --cov-fail-under=70` on every PR
- `TESTING.md`: philosophy, how to run, directory structure

Files to create/modify:
- `pyproject.toml` (add [tool.pytest.ini_options])
- `tests/conftest.py` (new — shared fixtures)
- `.github/workflows/test.yml` (new)
- `TESTING.md` (new)

### 1.2 Type System + Lint (Weeks 1-2)

Current state: No mypy/ruff config. Heavy use of `Any`, untyped `Optional`.
Pydantic V2 deprecation warnings.

Deliverables:
- `[tool.mypy]` in pyproject.toml (strict mode, gradual ramp-up)
- `[tool.ruff]` in pyproject.toml
- Pydantic V2: migrate `class Config:` → `model_config = ConfigDict(...)`
- CI adds mypy and ruff checks
- Type ignores (`# type: ignore`) tracked per-module, cleaned incrementally

Files to modify:
- `pyproject.toml`
- `src/animetta/config/core/base.py` (Pydantic Config → model_config)
- `src/animetta/config/providers/llm/local_lora_llm.py` (same)
- Plus any files that fail strict mypy after initial pass

### 1.3 CI/CD Pipeline (Week 2)

Deliverables:
- `.github/workflows/test.yml` — runs on PR: pytest + coverage + mypy + ruff
- `.github/workflows/build.yml` — runs on main merge: full suite + frontend build
- README CI badges

### Layer 1 Exit Criteria

- [ ] `pytest --cov` passes with ≥70% coverage
- [ ] `mypy src/` passes (may start with per-module exceptions)
- [ ] `ruff check src/` passes
- [ ] GitHub Actions shows green on PR
- [ ] README has CI badge

---

## Layer 2: AI Capability (Weeks 3-6)

Goal: Every AI module has test coverage, documentation, and graceful error
handling. This is the core differentiator that an AI/LLM engineering interviewer
will dig into.

### 2.1 LangGraph Node Tests (Weeks 3-4)

Current state: All nodes exist and function, but zero unit tests. Critical path:
`llm_node → tts_node → emotion_node → output_node`.

Deliverables per node (≥5 tests each):
- **llm_node**: mock LLM responses, RAG context injection, tool_calling branch,
  empty input, error recovery. Key file: `src/animetta/orchestration/graph/llm_node.py`.
- **tts_node**: mock TTS service (success + failure paths), empty text skip.
  Key file: `src/animetta/orchestration/graph/tts_node.py`.
- **emotion_node**: mock analyzer, emotion extraction from text, default on empty.
  Key file: `src/animetta/orchestration/graph/emotion_node.py`.
- **output_node**: mock Socket.IO callback, event format validation, memory storage.
  Key file: `src/animetta/orchestration/graph/output_node.py`.
- **orchestrator integration**: `process_text` and `process_audio` full flow.
  Key file: `src/animetta/orchestration/graph/orchestrator.py`.

Design decision: All external services (LLM API, TTS HTTP, databases) must be
mocked. No real network calls in unit tests. Global fixtures in `conftest.py`.

### 2.2 Tool System Hardening (Week 4)

Current state: 3 built-in tools registered. MCP Docker bridge fails silently when
Docker is unavailable (logged as ERROR, should be WARNING + continue).

Deliverables:
- `tool_manager.py` tests: mock MCP bridge, tool registration/deregistration
- `mcp_bridge.py` tests: graceful degradation when Docker unavailable
- `langchain_tools.py` tests: unit tests for each built-in tool (web_search,
  get_current_time, calculator)
- Tool call retry/timeout tests
- Change MCP Docker failure from ERROR to WARNING in `mcp_bridge.py`

### 2.3 Memory System Hardening (Week 5)

Current state: Wiki-architecture memory system fully implemented but zero tests.
Key components: chunker, hybrid_search, chroma_store, sqlite_store.

Deliverables:
- **chunker tests**: Markdown chunk boundaries, overlap windows, empty documents,
  edge cases. File: `src/animetta/memory/chunker.py`.
- **hybrid_search tests**: Vector (70%) + BM25 (30%) weighting, empty results,
  boundary scores. File: `src/animetta/memory/hybrid_search.py`.
- **chroma_store tests**: CRUD, collection management, persistence.
  File: `src/animetta/memory/chroma_store.py`.
- **sqlite_store tests**: FTS5 search, metadata filtering, concurrent access.
  File: `src/animetta/memory/sqlite_store.py`.
- **memory_system integration test**: store_turn → retrieve_context end-to-end.
  File: `src/animetta/memory/memory_system.py`.

### 2.4 Observability (Weeks 5-6)

Current state: StatsCallbackHandler collects data into SQLite, but `stats_api.py`
FastAPI routes are not registered on the main ASGI app.

Deliverables:
- Register `stats_api.py` router on the main ASGI application
- `/health` endpoint: returns service status + component health checks
- `/metrics` endpoint: Prometheus-format or simple JSON metrics for request counts,
  node latencies, error rates
- Structured JSON logging (replace ad-hoc loguru format with consistent schema)
- StatsStore data retention policy (auto-cleanup old traces)

### 2.5 Configuration Management (Week 6)

Current state: `config.yaml` + `services.yaml` have overlapping responsibilities.

Deliverables:
- Clear layering: `config.yaml` = user-facing settings, `services.yaml` = provider params
- Top-level `AppConfig.validate()` for config schema validation
- Config hot-reload: file watcher that signals running orchestrator on change
- `.env.example` with all env vars documented (types, defaults, descriptions)

### Layer 2 Exit Criteria

- [ ] Each LangGraph node has ≥5 unit tests
- [ ] Tool system tests cover happy + error paths
- [ ] Memory system tests cover CRUD + search + hybrid weights
- [ ] `/health`, `/metrics`, `/stats` endpoints available
- [ ] StatsCallbackHandler data visible via stats_api
- [ ] Config schema validated + `.env.example` exists

---

## Layer 3: Delivery (Weeks 7-8)

Goal: Open the repo and the first impression is "this is production quality" —
Demo GIF, CI badges, architecture docs, one-click deploy.

### 3.1 Containerization (Week 7)

Current state: No Dockerfile. Startup via `scripts/start.py`. External services
(VibeVoice TTS, Docker MCP) fail noisily when unavailable.

Deliverables:
- `Dockerfile`: multi-stage build, `python:3.13-slim` base
- `docker-compose.yml`: backend service + optional frontend
- `.dockerignore`
- `docker-compose.override.yml`: development mode with hot-reload
- Graceful degradation: MCP tools show user-friendly errors when Docker absent

### 3.2 Documentation Overhaul (Weeks 7-8)

Current state: README references deleted directories (`adapters/`, `pipeline/`,
`events/`, `handlers/`). Mixed Chinese/English. No ARCHITECTURE.md.

Deliverables:
- `README.md` rewrite: Demo GIF at top, CI badge, architecture diagram (Mermaid),
  3-command quickstart, accurate project structure tree, tech stack
- `ARCHITECTURE.md`: data flow diagram, module responsibilities, LangGraph state
  machine visualization, deployment topology
- `CONTRIBUTING.md`: dev environment setup, PR workflow, coding standards
- `TESTING.md`: test philosophy, run commands, coverage targets
- Remove stale docs from `docs/development/` and `docs/architecture/`

### 3.3 Demo Deployment (Week 8)

Deliverables:
- Fly.io / Render free-tier deployment config
- `Dockerfile.prod`: production-optimized (slimmer image, gunicorn, static CDN)
- Demo preset: mock mode, works out of the box
- `docs/deployment.md`: deployment guide
- Health check URL + auto-recovery

### 3.4 Final Polish (Week 8)

- Translate Chinese comments to English
- Remove `__pycache__` directories and backup files from git
- Clean up `TODOS.md`
- Complete `.gitignore`
- Aggregate all CI badges at top of README

### Layer 3 Exit Criteria

- [ ] `docker-compose up` starts the full stack
- [ ] README has Demo GIF + architecture diagram + CI badges
- [ ] ARCHITECTURE.md covers data flow / modules / state graph
- [ ] Live demo on Fly.io or Render
- [ ] All docs consistent with actual code
- [ ] Zero Chinese comments, zero stale files

---

## Timeline Summary

| Week | Layer | Key Deliverables |
|------|-------|-----------------|
| 1 | Infrastructure | pytest config, conftest.py, CI test.yml, TESTING.md |
| 2 | Infrastructure | mypy/ruff config, Pydantic V2 fix, CI green, README badge |
| 3 | AI Capability | 4 LangGraph node test suites (llm, tts, emotion, output) |
| 4 | AI Capability | Tool system tests, MCP graceful degradation, orchestrator integration tests |
| 5 | AI Capability | Memory system full coverage (chunker, search, stores, integration) |
| 6 | AI Capability | Observability (/health, /metrics, stats_api), config management |
| 7 | Delivery | Dockerfile, docker-compose, containerization |
| 8 | Delivery | Docs overhaul, demo deploy, final polish |

## Pre-existing Technical Debt (Not in Scope)

These issues exist but are deferred from this plan:
- LangChain `metadata.enable_tools` propagation warning (cosmetic, LangChain internal)
- Socket.IO protocol version mismatch (minor, client-side)
- `threading.Lock` + `asyncio` mixed in stats_handler.py (low risk, works in practice)
- LangGraph ConfigStore pattern (`_config` hack) — documented but not refactored
