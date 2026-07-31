# Contributing Guide

## Development Setup

```bash
# Clone and enter
git clone https://github.com/loiter74/animetta.git
cd animetta

# Copy env template
cp .env.example .env
# Edit .env with your API keys

# Docker (Recommended)
python scripts/runtime_lifecycle.py qwen-deploy  # one-time / intentional Qwen change
python scripts/runtime_lifecycle.py anima-up     # routine; preserves Qwen

# Or CPU-only
docker compose -f docker-compose.cpu.yml up -d --build

# Check health
curl -s http://localhost/health
```

## Git Hooks (one-time setup)

Install the pre-commit hook so trivial lint/format/secret mistakes are caught
locally on every commit (sub-second), instead of waiting for CI:

```bash
pip install -r requirements-dev.txt   # installs pre-commit + ruff + mypy
make install-hooks                    # installs .git/hooks/pre-commit
```

The hook runs `ruff check`, `ruff format --check`, secret/large-file guards,
and (on frontend changes) `prettier --check`. Slow checks (mypy, frontend
eslint, pytest) stay on CI; run `make health` before pushing for a full local
gate. See [docs/ci-gate-plan.md](docs/ci-gate-plan.md) for the gate design.

## Project Structure

```
src/animetta/          # Python backend
  ├── core/         # Server entry + service container
  ├── orchestration/# LangGraph state graph
  ├── services/     # LLM / ASR / TTS / VAD implementations
  ├── tools/        # Tool system (built-in + MCP)
  ├── memory/       # Wiki-architecture memory system
  ├── avatar/       # Live2D expression analysis
  └── config/       # Configuration (YAML + Pydantic)
frontend/           # Vue 3 + TypeScript Electron app
tests/              # Test suite
```

## Code Standards

- **Python 3.13+** — use modern typing (Optional[X] → X | None where possible)
- **Type hints required** for all public functions
- **Async-first** — all I/O operations must be async
- **Pydantic V2** — use `model_config = ConfigDict(...)` not `class Config:`
- **Logging** — use `loguru` logger, English messages only
- **Frontend styling** — follow [STYLE_GUIDE.md](STYLE_GUIDE.md) and use design tokens/UnoCSS utilities instead of hardcoded colors.

## Testing

```bash
# Validate the quality catalog
make quality-validate

# Fast local feedback; exact hermetic cache + weighted scheduler
make test-quick

# Current-worktree impact closure
make test-affected

# Cold repository-wide release gate
make test-full

# Compare against the cache-off, dominance-disabled sequential plan
make test-affected-shadow

# With coverage
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta

# Single file
PYTHONPATH=src python -m pytest tests/orchestration/graph/test_llm_node.py -v
```

See [Testing Guide](docs/development/testing.md) for detailed test conventions.

`tooling/quality.yml` is the sole component-to-test and Docker-scope mapping. Cache reuse is limited to successful hermetic results in the same repository and trust scope. Browser, live-service, and Docker-runtime acceptance always records fresh evidence.

## Pull Request Process

1. Create a feature branch from `main`
2. Install the local gate once: `make install-hooks` (see [Git Hooks](#git-hooks-one-time-setup) above)
3. Write tests first (TDD preferred)
4. Ensure CI passes:
   - **preflight** (sub-minute, PR-only): ruff + format + scoped mypy on changed files
   - **Quality** matrix: `tooling/quality` impact-selected tests, then `quality-gate` aggregates
5. Update docs if changing public interfaces (and tick the impact checklist in the PR template)
6. Open PR against `main`

> **Branch protection (manual, one-time):** in GitHub Settings → Branches → `main`, enable "Require status checks to pass before merging" and add `preflight` + `quality-gate` as required checks. Enable "Require review from code owners" (see `.github/CODEOWNERS`). This step can't be set from the repo files — see [docs/ci-gate-plan.md §Enabling branch protection](docs/ci-gate-plan.md#enabling-branch-protection-manual-one-time).

## Change Tracking (openspec)

New features and changes are tracked via the [openspec](openspec/) spec-driven system — **not** free-form plan docs. To propose a change:

```
/opsx-propose <change-name>
```

This generates `proposal.md` + `design.md` + `tasks.md` under `openspec/changes/<name>/`. Implement with `/opsx-apply`, then archive with `/opsx-archive`. Historical plans migrated from the former `docs/plans/` live in `openspec/changes/archive/`.

## Agent Collaboration

When working with AI agents (ZCode, Claude Code, Cursor, Copilot), read [AGENTS.md](AGENTS.md) first — it is the single source of truth for project conventions, architecture boundaries, and coding rules. Scoped sub-`AGENTS.md` files exist in module directories (`src/animetta/**/AGENTS.md`, `frontend/AGENTS.md`, etc.).

## Docker Development

```bash
# One-time Qwen deployment
python scripts/runtime_lifecycle.py qwen-deploy

# Routine build and startup (Qwen remains resident)
python scripts/runtime_lifecycle.py anima-up

# View logs
docker compose logs -f animetta

# Run tests inside container
docker compose exec animetta PYTHONPATH=/app/src python -m pytest tests/ -v

# Shell access
docker compose exec animetta bash

# Rebuild Animetta after application code changes
python scripts/runtime_lifecycle.py anima-up

# Stop Animetta without unloading Qwen
python scripts/runtime_lifecycle.py anima-down

# Release Qwen GPU memory without deleting its container
python scripts/runtime_lifecycle.py qwen-stop

# CPU-only mode
docker compose -f docker-compose.cpu.yml up -d --build
```

### Container Structure

The container runs nginx (port 80) + Python backend (port 12394) via `docker/entrypoint.sh`. Frontend is pre-built and served as static files by nginx. See `docs/deployment/docker.md` for full details.

### Debugging

```bash
# Check backend health
curl http://localhost/health

# Inspect container
docker compose exec animetta env          # Environment variables
docker compose exec animetta ls /app/data # Check volumes
docker compose exec animetta nvidia-smi   # GPU status

# Restart backend only (without rebuild)
docker compose restart animetta
```

## Adding a New Service Provider

1. Create config class with `@ProviderRegistry.register_config`
2. Create service implementation with `@ProviderRegistry.register_service`
3. Add the typed provider declaration to `config/animetta.yaml` and reference it from each intended profile
4. Write tests for registration + basic functionality
