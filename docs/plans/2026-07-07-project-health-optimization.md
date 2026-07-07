# Project Health Optimization Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current mostly-healthy Animetta repo into a reproducible, low-noise project where local, CI, Docker, and design-system checks agree.

**Architecture:** Treat health as a layered contract: runtime baseline, dependency setup, static checks, tests, frontend build, route smoke, Docker health, and design-system compliance. Each task first adds or updates a check so future regressions are visible, then makes the smallest change needed to pass it.

**Tech Stack:** Python 3.13, Starlette + Socket.IO ASGI, LangGraph, Pydantic V2, pytest, ruff, mypy, Vue 3, Vite, Vitest, pnpm, Docker Compose.

---

## Baseline From 2026-07-07 Audit

Healthy:
- `ruff check src/ tests/` passed.
- `mypy src/animetta --ignore-missing-imports` produced no errors.
- Backend test collection works with default addopts disabled: 3350 tests collected.
- Backend sampled suites passed: core/orchestration-server 413 passed, config/inspection/tracing 408 passed, memory_v2 115 passed.
- Frontend `pnpm run typecheck`, `pnpm run test:run`, and `pnpm run build` passed; 26 test files, 249 tests.
- `scripts/validate-events.py`, `scripts/route_smoke.py`, `scripts/check_secrets.py`, and `import animetta` passed.
- Docker Compose config validates for GPU and CPU files.
- Existing container is healthy; `GET /health` and `GET /` return 200.
- Last 500 Docker log lines had no `Traceback`, `ERROR`, `CRITICAL`, or `FATAL` matches.

Risks:
- Local shell is Python 3.11.15, while project policy and type tooling target Python 3.13; Docker currently uses Python 3.12 in several places.
- The local environment misses `pytest-xdist` and `pytest-timeout`, so default pytest addopts fail unless requirements are installed.
- Pydantic provider configs emit repeated field-shadow warnings on import.
- `pyproject.toml` suppresses `F821` broadly for multiple production modules and has broad mypy `ignore_errors`.
- `frontend/index.html`, `frontend/public/live.html`, and `frontend/uno.config.ts` still reference Google fonts despite the typography spec requiring OS-native fonts only.
- Optional audio dependencies such as `pydub` are correctly in local-AI requirements, but current smoke output logs noisy warnings.
- Security audit path is not reliable in this environment: `pnpm audit --audit-level high` failed because registry fetch failed.
- `PersonaHandlers` and provider base config classes show lower direct test coverage in CodeGraph.
- Root had two scratch files reviewed during planning: `FIX_PLAN.md` and `fetch_rss.sh`. Their still-valid items are absorbed below; the root-level files should be deleted rather than kept as parallel plans/scripts.

## Task 1: Unify Python Runtime Baseline

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `Dockerfile.cuda`
- Modify: `docker-compose.cpu.yml`
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/deploy-zeabur.yml`
- Modify: `README.md`
- Create: `.python-version`

**Step 1: Add a baseline check**

Create or update a small version check in the health path. Preferred file:
`scripts/check_runtime.py`.

```python
import sys

MIN_VERSION = (3, 13)

if sys.version_info < MIN_VERSION:
    raise SystemExit(
        f"Animetta requires Python {MIN_VERSION[0]}.{MIN_VERSION[1]}+, "
        f"got {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

print("Python runtime OK")
```

**Step 2: Run it to verify the current local mismatch**

Run:

```bash
PYTHONPATH=src python scripts/check_runtime.py
```

Expected locally until Python is switched: FAIL with Python 3.11.x.

**Step 3: Align project metadata**

Update:

```toml
requires-python = ">=3.13"

[tool.mypy]
python_version = "3.13"
```

Keep `ruff.target-version = "py313"`.

**Step 4: Align Docker and CI**

Use Python 3.13 consistently where images permit it. For CUDA runtime, verify the current Ubuntu base can install Python 3.13 cleanly before switching the runtime layer; otherwise document the exception and keep app code tested under 3.13.

**Step 5: Verify**

Run:

```bash
PYTHONPATH=src python scripts/check_runtime.py
ruff check src/ tests/
mypy src/ --ignore-missing-imports
docker compose config --quiet
docker compose -f docker-compose.cpu.yml config --quiet
```

Expected: all pass in a Python 3.13 environment.

## Task 2: Make Local Health Reproducible

**Files:**
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `requirements-dev.txt`
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/deploy-zeabur.yml`
- Create or modify: `scripts/check_dev_env.py`

**Step 1: Add dependency preflight**

Create `scripts/check_dev_env.py` to verify the tools required by default pytest addopts are importable:

```python
import importlib.util

required = {
    "pytest": "pytest",
    "xdist": "pytest-xdist",
    "pytest_timeout": "pytest-timeout",
    "pytest_asyncio": "pytest-asyncio",
}

missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]

if missing:
    raise SystemExit(
        "Missing dev dependencies: "
        + ", ".join(missing)
        + ". Run: python -m pip install -r requirements.txt"
    )

print("Dev environment OK")
```

**Step 2: Wire preflight into `make health`**

Run `scripts/check_runtime.py` and `scripts/check_dev_env.py` before pytest so the failure is actionable.

**Step 3: Add full health target**

Add a target that runs:

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports
python scripts/validate-events.py
python scripts/check_secrets.py
python scripts/route_smoke.py
python -m pytest tests/ --cov=src/animetta --cov-report=term-missing --cov-fail-under=67
```

**Step 4: Add frontend health target**

From `frontend/`, run:

```bash
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run test:run
pnpm run build
```

**Step 5: Verify**

Run:

```bash
make health
make frontend-health
```

Expected: either pass or fail with a specific missing dependency/runtime message.

## Task 3: Remove Pydantic Provider Warning Noise

**Files:**
- Modify: `src/animetta/config/core/mixins.py`
- Modify: `src/animetta/config/providers/llm/base.py`
- Modify: `src/animetta/config/providers/asr/base.py`
- Modify: `src/animetta/config/providers/tts/base.py`
- Modify provider config files under `src/animetta/config/providers/{llm,asr,tts}/`
- Add tests under: `tests/config/`

**Step 1: Write a warning regression test**

Add a test that imports all provider config modules and fails on Pydantic field-shadow warnings.

```python
import importlib
import warnings

PROVIDER_MODULES = [
    "animetta.config.providers.llm.deepseek",
    "animetta.config.providers.llm.openai",
    "animetta.config.providers.asr.openai",
    "animetta.config.providers.tts.qwen3",
]


def test_provider_config_imports_without_field_shadow_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for module in PROVIDER_MODULES:
            importlib.import_module(module)

    messages = [str(w.message) for w in caught]
    assert not [m for m in messages if "shadows an attribute in parent" in m]
```

**Step 2: Run it and confirm failure**

Run:

```bash
PYTHONPATH=src python -m pytest -o addopts='' tests/config/test_provider_warning_contract.py -q
```

Expected before refactor: FAIL with field-shadow warnings.

**Step 3: Refactor common provider fields**

Prefer one of these low-risk designs after checking all provider tests:
- Remove Pydantic field mixins for fields that subclasses commonly override; keep provider classes explicit.
- Or keep mixins only for fields that are not provider-specific and do not get overridden.

Do not suppress warnings globally unless a field name must intentionally override a parent field and has a documented reason.

**Step 4: Verify**

Run:

```bash
PYTHONPATH=src python -m pytest -o addopts='' tests/config -q
PYTHONPATH=src python scripts/route_smoke.py
```

Expected: tests pass and route smoke no longer floods provider field-shadow warnings.

## Task 4: Shrink Static-Analysis Suppression Surface

**Files:**
- Modify: `pyproject.toml`
- Modify production files currently protected by broad `F821` ignores
- Modify: `tests/`

**Step 1: Add an audit command**

Run:

```bash
ruff check src/ tests/ --select F821
mypy src/animetta --ignore-missing-imports --warn-unused-configs
```

Expected today: Ruff may pass only because production globs suppress `F821`; mypy reports an unused override section.

**Step 2: Remove one suppression group at a time**

Start with the narrowest module group. For each group, remove the `F821` ignore, run Ruff, and fix real undefined names.

**Step 3: Tighten mypy only after Ruff is clean**

Remove broad `ignore_errors = true` overrides module by module. Keep targeted ignores only when an external dependency genuinely prevents type checking.

**Step 4: Verify**

Run:

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports
PYTHONPATH=src python -m pytest tests/config tests/core tests/orchestration/server -q
```

Expected: all pass with fewer or no broad suppressions.

## Task 5: Enforce Design-System Typography Rules

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/public/live.html`
- Modify: `frontend/uno.config.ts`
- Modify or add frontend tests under `frontend/src/**/*.test.ts`
- Reference: `design-system/typography.html`

**Step 1: Add a static font rule test or script**

Create a frontend-side check that fails if app HTML/CSS references external font providers.

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const files = ['index.html', 'public/live.html', 'uno.config.ts']

describe('font loading policy', () => {
  it('does not load external web fonts', () => {
    const text = files.map((file) => readFileSync(file, 'utf8')).join('\n')
    expect(text).not.toMatch(/fonts\.googleapis|fonts\.gstatic|Quicksand|Noto\+Sans/)
  })
})
```

**Step 2: Run it and confirm failure**

Run from `frontend/`:

```bash
pnpm run test:run
```

Expected before cleanup: FAIL because Google Fonts are referenced.

**Step 3: Remove external font links and CSP allowances**

Remove:
- Google Fonts `preconnect` and stylesheet links from `frontend/index.html`.
- Google Fonts links from `frontend/public/live.html`.
- `font-quicksand` token from `frontend/uno.config.ts` unless no code references it.
- `https://fonts.googleapis.com` and `https://fonts.gstatic.com` from CSP unless still required by a non-font feature.

**Step 4: Verify**

Run from `frontend/`:

```bash
pnpm run typecheck
pnpm run test:run
pnpm run build
```

Expected: all pass and built HTML contains no external font references.

## Task 6: Improve Coverage Around Route and Persona Handlers

**Files:**
- Modify: `src/animetta/orchestration/server/handlers/persona_handlers.py`
- Modify: `src/animetta/orchestration/server/routes.py`
- Add or modify: `tests/orchestration/server/test_persona_handlers.py`
- Add or modify: `tests/orchestration/server/test_routes.py`

**Step 1: Add direct PersonaHandlers tests**

Cover:
- initial persona list includes MBTI fields when config is set;
- `set_global_config` propagates into persona event responses;
- missing config returns a structured empty/error response without throwing;
- event names use canonical `module:action` names.

**Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=src python -m pytest -o addopts='' tests/orchestration/server/test_persona_handlers.py -q
```

Expected before fixes: either fail or expose missing direct coverage.

**Step 3: Make smallest implementation fixes**

Keep `routes.py` as a facade. If behavior is wrong, fix it in `PersonaHandlers` or its collaborators, not by adding business logic to `routes.py`.

**Step 4: Verify**

Run:

```bash
PYTHONPATH=src python -m pytest -o addopts='' tests/orchestration/server -q
PYTHONPATH=src python scripts/validate-events.py
```

Expected: all pass.

## Task 7: Normalize Optional Audio Dependency Reporting

**Files:**
- Modify: `src/animetta/avatar/analyzers/audio.py`
- Modify ASR/audio provider files that warn on optional `pydub`
- Add or modify: `tests/avatar/test_audio_analyzer.py`
- Add or modify: `tests/inspection/test_health.py`

**Step 1: Add warning behavior tests**

Assert that missing optional dependencies are reported as capability status or fallback behavior, not noisy import-time warnings during unrelated route smoke.

**Step 2: Convert import-time warning to lazy capability reporting**

Move optional dependency checks into the function that needs them, or into inspection health checks.

**Step 3: Verify**

Run:

```bash
PYTHONPATH=src python scripts/route_smoke.py
PYTHONPATH=src python -m pytest -o addopts='' tests/avatar tests/inspection -q
```

Expected: route smoke remains clean except intentional route results.

## Task 8: Add Reliable Security Audit Path

**Files:**
- Modify: `frontend/.npmrc`
- Modify: `.github/workflows/frontend.yml`
- Modify: `Makefile`
- Optional create: `scripts/audit_frontend.ps1`

**Step 1: Make registry explicit for audit**

Either use the public npm registry for audit commands or document the mirror outage fallback.

**Step 2: Add CI audit gate with retry**

Run:

```bash
pnpm audit --audit-level high --registry=https://registry.npmjs.org
```

For local China mirror workflows, keep install mirrors separate from audit registry if needed.

**Step 3: Verify**

Run from `frontend/`:

```bash
pnpm audit --audit-level high --registry=https://registry.npmjs.org
```

Expected: returns a real vulnerability result or clean pass, not `fetch failed`.

## Task 9: Preserve Docker Startup Protocol As A First-Class Gate

**Files:**
- Modify: `Makefile`
- Optional create: `scripts/docker_health_check.ps1`
- Optional create: `scripts/docker_health_check.sh`
- Modify: `README.md`

**Step 1: Script the protocol**

Implement the documented sequence:

```bash
docker compose down
docker compose build
docker compose up -d
curl -s http://localhost/health
curl -s http://localhost
docker compose logs animetta
```

Poll `/health` until HTTP 200 and response contains `"status":"ok"`.

**Step 2: Add log gate**

Fail if logs contain:

```text
Traceback
ERROR
CRITICAL
FATAL
```

**Step 3: Verify GPU and CPU modes**

Run:

```bash
make docker-health
make docker-health-cpu
```

Expected: both modes either pass or fail with a clear environment reason.

## Task 10: Absorb Legacy Scratch Notes

**Files:**
- Delete after absorption: `FIX_PLAN.md`
- Delete after absorption: `fetch_rss.sh`
- Modify as needed: `docs/plans/2026-07-07-project-health-optimization.md`
- Optional modify: `scripts/check_secrets.py`
- Optional modify: `docs/architecture/overview.md`
- Optional modify: `docs/README.md`
- Optional modify: `src/animetta/AGENTS.md`
- Optional modify: `frontend/start-electron-dev.ps1`
- Optional modify: `frontend/start-electron-dev.bat`
- Optional modify: `frontend/start-live-stream.bat`
- Optional create: `scripts/fetch_youtube_rss.py`

**Context absorbed from `FIX_PLAN.md`:**

Several old findings are already fixed in the current tree and should not be reintroduced as active tasks:
- `requirements.txt` exists and already includes `requirements-core.txt` plus `requirements-dev.txt`.
- `scripts/health_check.py` exists and already has Windows-aware `pnpm.cmd` / `pnpm` / `corepack pnpm` detection.
- `Dockerfile` and `Dockerfile.cuda` already use `pnpm install --frozen-lockfile`.
- Unsafe `tempfile.mktemp()` currently has a source hygiene test and no active source match in `src/` or `frontend/src/`.
- External calls to `LivingMemorySystem._run_metabolism_tick()` were not found outside the class; the public `run_metabolism_tick()` wrapper exists.

Still-valid items from the old plan should be retained as follow-up work:
- Extend `scripts/check_secrets.py` beyond root `config/*.yaml` so explicit `.env*` scans are possible without printing secret values. Do not assume `.env` is safe just because the default scan passes.
- Keep shrinking broad static-analysis suppressions, especially `F821` per-file ignores and broad mypy `ignore_errors`.
- Audit broad `except Exception` by boundary category. Keep intentional safety nets at I/O, plugin, and background-loop boundaries, but make critical paths use narrower exceptions or structured error wrappers.
- Update stale FastAPI references in active docs and agent maps. Current backend identity is Starlette + Socket.IO ASGI + LangGraph.
- Align root/frontend helper scripts with pnpm/corepack. `frontend/start-electron-dev.ps1`, `frontend/start-electron-dev.bat`, and `frontend/start-live-stream.bat` still contain `npm install`.
- Keep memory performance items on the backlog: confirm SQLite/Chroma calls in async memory paths do not block hot loops, and profile `MemoryGraph.vue` for large graph updates before changing d3 simulation behavior.

**Context absorbed from `fetch_rss.sh`:**

The file is a one-off root-level script:

```bash
curl -s "https://www.youtube.com/feeds/videos.xml?channel_id=UCuoozZpRvmMUNiUq4ekBApg"
```

Do not keep it in the project root. If YouTube RSS fetching is a real feature or operational utility, replace it with a tracked, parameterized script under `scripts/`, for example:

```bash
PYTHONPATH=src python scripts/fetch_youtube_rss.py --channel-id UCuoozZpRvmMUNiUq4ekBApg
```

Expected behavior for a real script:
- accepts `--channel-id` and optional `--output`;
- has a timeout and nonzero exit on HTTP failure;
- writes XML to stdout by default;
- has no hardcoded personal channel ID unless documented as a fixture;
- has a small smoke test or documented manual verification.

**Step 1: Delete absorbed scratch files**

Run:

```bash
Remove-Item -LiteralPath FIX_PLAN.md
Remove-Item -LiteralPath fetch_rss.sh
```

Expected: both files are gone from `git status --short`.

**Step 2: Verify active plan carries the useful content**

Run:

```bash
Select-String -Path docs/plans/2026-07-07-project-health-optimization.md -Pattern "Absorb Legacy Scratch Notes", "fetch_youtube_rss", "FastAPI references", "check_secrets"
git status --short
```

Expected: only intentional tracked/untracked work remains; the old root-level scratch files are absent.

## Task 11: Final Verification Bundle

**Files:**
- No implementation files unless previous tasks require updates.

**Step 1: Run backend checks**

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports
PYTHONPATH=src python scripts/validate-events.py
PYTHONPATH=src python scripts/check_secrets.py
PYTHONPATH=src python scripts/route_smoke.py
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta --cov-report=term-missing --cov-fail-under=67
```

**Step 2: Run frontend checks**

```bash
cd frontend
pnpm run typecheck
pnpm run test:run
pnpm run build
```

**Step 3: Run Docker gate**

Follow the Docker startup protocol from `AGENTS.md`. Use CPU mode when GPU is unavailable.

**Step 4: Report**

Update this plan with:
- exact commands run;
- pass/fail status;
- coverage percentage;
- remaining warnings;
- Docker health result;
- any deliberately deferred items.
