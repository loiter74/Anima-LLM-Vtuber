# TESTS — PYTEST + VITEST SUITE

**Generated:** 2026-06-15 · **Commit:** 10735c3 · **Branch:** main

> Parent: [../AGENTS.md](../AGENTS.md). Backend pytest mirrors `src/animetta/`; frontend vitest lives under `frontend/src/`.

## OVERVIEW

126 backend pytest files across 15 subdirs + 20 frontend vitest files. asyncio_mode=auto, xdist-parallel by default, 30s timeout, integration/slow auto-skipped. Backend coverage ~70% (advisory — `fail_under = 0`).

## STRUCTURE

```
tests/
├── conftest.py                    # GLOBAL: sys.path injection + 11 mock fixtures
├── test_{main_path,notifier,redis_checkpoint,stats_store,tracing_*}.py
├── avatar/  (+ mappers/)          # emotion analysis + Live2D param mapping
├── config/                        # Pydantic configs + ProviderRegistry
├── core/                          # service container + socketio_server
├── eval/  (+ conftest.py)         # RAG quality metrics + sample fixtures
├── fixtures/audio/                # static audio assets (singing_test.m4a)
├── inspection/                    # health/consistency checks
├── integration/  (+ conftest.py)  # ⚠️ AUTO-MARKED `integration`
├── memory_v2/                     # atom-based memory (Chroma+SQLite+Wiki)
├── orchestration/{graph,server}/  # LangGraph nodes + WebSocket/REST
├── services/{audio,llm,meme}/     # provider + factory + pipeline tests
├── smoke/                         # e2e-ish (conversation, meme, singing)
├── tools/minecraft/               # bridge, autonomous loop, planner
├── tracing/  (+ conftest.py)      # ⚠️ autouse fixture resets Prometheus/OTel
├── unit/                          # isolated unit tests
└── utils/                         # auto_config, env_helper, logger_manager
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add backend test | `tests/<module>/test_<name>.py` | Mirror `src/animetta/<module>/` |
| Integration test | `tests/integration/test_*.py` | Auto-marked via `pytest_collection_modifyitems` |
| Tracing test | `tests/tracing/` ONLY | autouse fixture resets global REGISTRY — do NOT place elsewhere |
| Mock fixtures | `tests/conftest.py` | 11 available (see CONVENTIONS) |
| RAG eval samples | `tests/eval/conftest.py` | sample_retrieved/expected/timings/chunks |
| Frontend test | `frontend/src/<area>/__tests__/<Name>.test.ts` | `.test.ts` NOT `.spec.ts` |

## CONVENTIONS

- **asyncio_mode = "auto"** — `async def test_foo()` works without `@pytest.mark.asyncio`
- **Parallel by default** — `-n auto` (pytest-xdist), 30s thread timeout
- **Default filter** — `-m "not slow and not integration"`; opt in by overriding `-m`
- **Markers** (pyproject.toml `[tool.pytest.ini_options]`): `asyncio`, `integration`, `slow`
- **Naming** — `test_<module>.py` / `Test<Component>` class / `test_<behavior>` method
- **AAA pattern** (Arrange/Act/Assert) per docs/development/testing.md
- **Frontend (vitest)** — `happy-dom` env, glob `src/**/*.test.ts` only, `@vue/test-utils` + `@testing-library/vue`; `pnpm test:run` / `pnpm test:coverage`

### Mock Fixtures (tests/conftest.py)

`mock_llm` · `mock_tts` · `mock_asr` · `mock_vad` · `mock_socketio` · `mock_service_context` (aggregates the four service mocks + memory/emotion) · `mock_embedding` (384-dim fixed vector) · `mock_chroma` (in-memory collection) · `mock_mcp_client` · `mock_minecraft_bridge` · `mock_bilibili_client`

All use `MagicMock` + `AsyncMock`; each exposes `.close = AsyncMock()`. Prefer these over constructing real services in unit tests.

## COMMANDS

```bash
# Stable impact-aware entrypoints (preferred for agent and CI parity)
make quality-validate
make test-quick
make test-affected
make test-full

# Default run (parallel, skip slow/integration)
PYTHONPATH=src python -m pytest tests/

# With coverage (advisory — no gate)
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta --cov-report=term-missing

# Single test
PYTHONPATH=src python -m pytest tests/test_main_path.py::TestVADServicesRegistered::test_vad_services_registered -v

# By directory
PYTHONPATH=src python -m pytest tests/orchestration/graph/ -v

# Integration (requires live server on :12394)
PYTHONPATH=src python -m pytest tests/integration/ -m integration

# Frontend
cd frontend && pnpm test:run && pnpm test:coverage
```

> `conftest.py` auto-injects `src/` to `sys.path`, but keep `PYTHONPATH=src` prefix in docs/CI for safety.

`quick` selects direct checks for rapid feedback. `affected` adds tests of impacted components. `full` runs the repository contract and executes `backend-full` once with coverage. The planner in `tooling/quality.yml` is authoritative; do not hand-maintain a second path map. `docker-compose-contract` is a hermetic static config check; service-isolated Playwright or live Docker groups run only when selected and when their declared capabilities are present.

## ANTI-PATTERNS

- ❌ Never put tracing tests outside `tests/tracing/` — Prometheus REGISTRY is global; only that conftest resets it
- ❌ Never write `.spec.ts` for frontend — vitest collects `*.test.ts` only
- ❌ Never manually decorate async tests with `@pytest.mark.asyncio` — asyncio_mode=auto handles it
- ❌ Never bypass `tests/conftest.py` fixtures by constructing real LLM/TTS/ASR services in unit tests
- ❌ Never assume `fail_under` enforces coverage — it's set to 0; coverage is advisory only

## NOTES

- `tests/integration/conftest.py` auto-tags every collected item as `integration`
- `tests/tracing/conftest.py` `autouse=True` fixture resets: Prometheus REGISTRY, OTel `_TRACER_INITIALIZED`, `metrics._initialized`
- Required plugins (implicit via addopts): pytest-asyncio, pytest-xdist, pytest-timeout, pytest-cov
- CI (`.github/workflows/quality.yml`): Python 3.13 from `.python-version`, frozen group-ID matrices, and `backend-full` with `--cov-fail-under=67`
- docs/development/testing.md is stale (claims 21% coverage); frontend/AGENTS.md is stale (claims 0% coverage / no vitest)
