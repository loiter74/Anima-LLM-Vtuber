# TESTS — PYTEST + VITEST SUITE

> Parent: [../AGENTS.md](../AGENTS.md). Backend pytest mirrors `src/animetta/`; frontend vitest lives under `frontend/src/`.

## OVERVIEW

Backend pytest mirrors the application tree; frontend Vitest inventory is tracked and checked in `frontend/AGENTS.md`. asyncio_mode=auto, xdist-parallel by default, 30s timeout, integration/slow auto-skipped. Backend coverage is advisory locally (`fail_under = 0`).

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
├── mcp/                           # 开发智能体 MCP 服务的隔离协议与客户端测试
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
| Add development MCP test | `tests/mcp/<server>/test_<name>.py` | Mock transport; no live service or network |
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

```powershell
# Windows canonical entrypoints; validate Python once before the first command
py -3.13 -c "import sys; assert sys.version_info >= (3, 13)"

# Default daily gate: pass the exact current-task paths and run once
py -3.13 -m tooling.quality verify --tier affected --paths <task-paths...> --cache read-write

# Only after changing the quality catalog, models, or test directory structure
py -3.13 -m tooling.quality validate

# Diagnosis only; do not chain quick into affected after the same frozen diff
py -3.13 -m tooling.quality verify --tier quick --worktree --cache read-write
py -3.13 -m tooling.quality verify --tier affected --worktree --shadow-sequential --cache off

# Benchmarks only
py -3.13 -m tooling.quality benchmark --tier quick --worktree --iterations 5 --output artifacts/test-impact/benchmark-quick.json
py -3.13 -m tooling.quality benchmark --tier affected --worktree --iterations 5 --output artifacts/test-impact/benchmark-affected.json

# Full release gate: run these three commands in order, without shell chaining
py -3.13 -m tooling.quality verify --tier full --worktree --cache off
py -3.13 -m tooling.quality plan --tier full --worktree --output artifacts/test-impact/docker-full-plan.json
py -3.13 scripts/release_runtime_gate.py --plan artifacts/test-impact/docker-full-plan.json --output artifacts/test-impact/release-runtime/evidence.json

# Targeted backend examples
py -3.13 -m pytest tests/
py -3.13 -m pytest tests/ --cov=src/animetta --cov-report=term-missing
py -3.13 -m pytest tests/test_main_path.py::TestVADServicesRegistered::test_vad_services_registered -v
py -3.13 -m pytest tests/orchestration/graph/ -v
py -3.13 -m pytest tests/integration/ -m integration

# Frontend commands are separate invocations from the repository root
pnpm --dir frontend test:run
pnpm --dir frontend test:coverage
```

以上命令按触发条件互斥，不是需要顺序执行的清单。POSIX 环境可使用对应的 `make` 入口；Windows 不得先尝试 `make`，也不得用裸 `python`。`conftest.py` 会注入 `src/`，因此上面的 Windows pytest 命令无需拼接临时环境变量。

`quick` selects direct checks for rapid feedback. `affected` adds tests of impacted components. Both use exact content fingerprints, a bounded weighted scheduler, and trust-scoped reuse of successful cacheable hermetic results. `full` is a cold release gate (`cache off`) and executes `backend-full` once with coverage. `test-affected-shadow` disables dominance and cache for sequential comparison. The planner in `tooling/quality.yml` is authoritative; do not hand-maintain a second path or Docker-scope map. `docker-compose-contract` is a hermetic static config check; service-isolated Playwright or live Docker groups always collect fresh evidence when selected and when their declared capabilities are present.

## ANTI-PATTERNS

- ❌ Never put tracing tests outside `tests/tracing/` — Prometheus REGISTRY is global; only that conftest resets it
- ❌ Never write `.spec.ts` for frontend — vitest collects `*.test.ts` only
- ❌ Never manually decorate async tests with `@pytest.mark.asyncio` — asyncio_mode=auto handles it
- ❌ Never bypass `tests/conftest.py` fixtures by constructing real LLM/TTS/ASR services in unit tests
- ❌ Never assume `fail_under` enforces coverage — it's set to 0; coverage is advisory only
- ❌ Never keep `pass`-only tests or tests that only assert behavior configured on their own mock
- ❌ Never use live network timeouts or production rate-limit sleeps in unit tests; isolate the boundary and set injected delays to zero
- ❌ Never permanently skip or xfail a deterministic path because an optional dependency or host OS is absent; simulate that boundary or move the scenario to a marked integration test
- ❌ Never carry pytest-xdist worker flags into quality feedback shards; the quality scheduler already owns sharding and concurrency

## NOTES

- `tests/integration/conftest.py` auto-tags every collected item as `integration`
- `tests/tracing/conftest.py` `autouse=True` fixture resets: Prometheus REGISTRY, OTel `_TRACER_INITIALIZED`, `metrics._initialized`
- Required plugins (implicit via addopts): pytest-asyncio, pytest-xdist, pytest-timeout, pytest-cov
- CI (`.github/workflows/quality.yml`): Python 3.13 from `.python-version`, frozen group-ID matrices, and `backend-full` with `--cov-fail-under=67`
- docs/development/testing.md is stale (claims 21% coverage); frontend/AGENTS.md is stale (claims 0% coverage / no vitest)
