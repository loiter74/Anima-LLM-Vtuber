.PHONY: lint format format-check frontend-lint frontend-format-check typecheck deadcode test quality-validate test-quick test-affected test-full test-affected-shadow benchmark-quick benchmark-affected docker-build-affected health docker-health docker-test docker-lint host-tts-up host-tts-status host-tts-stop anima-up anima-down install-hooks hooks

PYTHON ?= python
QUALITY_DOCKER_PLAN ?= artifacts/test-impact/docker-affected-plan.json
QUALITY_DOCKER_FULL_PLAN ?= artifacts/test-impact/docker-full-plan.json
QUALITY_RELEASE_EVIDENCE ?= artifacts/test-impact/release-runtime/evidence.json

# ── Local targets ────────────────────────────────────────────────────────

lint:
	PYTHONPATH=src ruff check src/ tooling/ scripts/ evaluations/ tests/

format:
	PYTHONPATH=src ruff format src/ tooling/ scripts/ evaluations/ tests/

format-check:
	PYTHONPATH=src ruff format --check src/ tooling/ scripts/ evaluations/ tests/

frontend-lint:
	pnpm --dir frontend lint

frontend-format-check:
	pnpm --dir frontend format:check

typecheck:
	PYTHONPATH=src mypy src/animetta --ignore-missing-imports

deadcode:
	PYTHONPATH=src $(PYTHON) -m vulture

test:
	PYTHONPATH=src python -m pytest tests/ -x -q

quality-validate:
	$(PYTHON) -m tooling.quality validate

test-quick:
	$(PYTHON) -m tooling.quality verify --tier quick --worktree --cache read-write

test-affected:
	$(PYTHON) -m tooling.quality verify --tier affected --worktree --cache read-write

test-full:
	$(PYTHON) -m tooling.quality verify --tier full --worktree --cache off
	$(PYTHON) -m tooling.quality plan --tier full --worktree --output $(QUALITY_DOCKER_FULL_PLAN)
	$(PYTHON) scripts/release_runtime_gate.py --plan $(QUALITY_DOCKER_FULL_PLAN) --output $(QUALITY_RELEASE_EVIDENCE)

test-affected-shadow:
	$(PYTHON) -m tooling.quality verify --tier affected --worktree --shadow-sequential --cache off

benchmark-quick:
	$(PYTHON) -m tooling.quality benchmark --tier quick --worktree --iterations 5 --output artifacts/test-impact/benchmark-quick.json

benchmark-affected:
	$(PYTHON) -m tooling.quality benchmark --tier affected --worktree --iterations 5 --output artifacts/test-impact/benchmark-affected.json

docker-build-affected:
	$(PYTHON) -m tooling.quality plan --tier affected --worktree --output $(QUALITY_DOCKER_PLAN)
	$(PYTHON) -m tooling.quality docker-build --plan $(QUALITY_DOCKER_PLAN)

health:
	@echo "=== Lint ==="
	$(MAKE) lint
	@echo ""
	@echo "=== Typecheck ==="
	$(MAKE) typecheck
	@echo ""
	@echo "=== Dead code ==="
	$(MAKE) deadcode
	@echo ""
	@echo "=== Tests ==="
	$(MAKE) test
	@echo ""
	@echo "All checks passed."

# ── Git hooks (pre-commit) ──────────────────────────────────────────────
# Install once after cloning: `make install-hooks`. The hook runs ruff
# lint+format-check and secret/large-file guards on every commit (sub-second).
# Slow checks (mypy, frontend eslint, tests) stay on CI; mypy is available
# as a manual stage: `pre-commit run --hook-stage manual mypy`.

install-hooks:
	py -3.13 -m pre_commit install

hooks:
	py -3.13 -m pre_commit run --all-files

# ── Docker targets ───────────────────────────────────────────────────────

host-tts-up:
	$(PYTHON) scripts/runtime_lifecycle.py host-tts-up

host-tts-status:
	$(PYTHON) scripts/runtime_lifecycle.py host-tts-status

host-tts-stop:
	$(PYTHON) scripts/runtime_lifecycle.py host-tts-stop

anima-up:
	$(PYTHON) scripts/runtime_lifecycle.py anima-up

anima-down:
	$(PYTHON) scripts/runtime_lifecycle.py anima-down

docker-health: docker-lint docker-test
	@echo "Docker health check complete."

docker-lint:
	docker compose exec animetta bash -c "pip install ruff --break-system-packages -q && PYTHONPATH=src ruff check src/ tests/"

docker-test:
	docker compose exec animetta bash -c "pip install pytest pytest-asyncio pytest-xdist pytest-timeout --break-system-packages -q && PYTHONPATH=src python -m pytest tests/ -x -q --ignore=tests/integration --ignore=tests/smoke"

docker-typecheck:
	docker compose exec animetta bash -c "pip install mypy --break-system-packages -q && PYTHONPATH=src mypy src/animetta --ignore-missing-imports"
