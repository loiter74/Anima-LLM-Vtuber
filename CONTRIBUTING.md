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
docker compose up -d --build

# Or CPU-only
docker compose -f docker-compose.cpu.yml up -d --build

# Check health
curl -s http://localhost/health
```

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
# Run all tests
PYTHONPATH=src python -m pytest tests/

# With coverage
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta

# Single file
PYTHONPATH=src python -m pytest tests/orchestration/graph/test_llm_node.py -v
```

See [Testing Guide](docs/development/testing.md) for detailed test conventions.

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests first (TDD preferred)
3. Ensure CI passes (pytest + mypy + ruff)
4. Update docs if changing public interfaces
5. Open PR against `main`

## Docker Development

```bash
# Build and run with GPU
docker compose up -d --build

# View logs
docker compose logs -f animetta

# Run tests inside container
docker compose exec animetta PYTHONPATH=/app/src python -m pytest tests/ -v

# Shell access
docker compose exec animetta bash

# Rebuild after code changes
docker compose build && docker compose up -d

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
3. Add config to `config/services.yaml`
4. Write tests for registration + basic functionality
