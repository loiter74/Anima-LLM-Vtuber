.PHONY: lint typecheck deadcode test health docker-health docker-test docker-lint

# ── Local targets ────────────────────────────────────────────────────────

lint:
	PYTHONPATH=src ruff check src/ tests/

format:
	PYTHONPATH=src ruff format src/ tests/

typecheck:
	PYTHONPATH=src mypy src/animetta --ignore-missing-imports

deadcode:
	PYTHONPATH=src vulture src/animetta/core src/animetta/config src/animetta/memory src/animetta/avatar src/animetta/utils src/animetta/notifier src/animetta/inspection --min-confidence 80

test:
	PYTHONPATH=src python -m pytest tests/ -x -q

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

# ── Docker targets ───────────────────────────────────────────────────────

docker-health: docker-lint docker-test
	@echo "Docker health check complete."

docker-lint:
	docker compose exec animetta bash -c "pip install ruff --break-system-packages -q && PYTHONPATH=src ruff check src/ tests/"

docker-test:
	docker compose exec animetta bash -c "pip install pytest pytest-asyncio pytest-xdist pytest-timeout --break-system-packages -q && PYTHONPATH=src python -m pytest tests/ -x -q --ignore=tests/integration --ignore=tests/smoke"

docker-typecheck:
	docker compose exec animetta bash -c "pip install mypy --break-system-packages -q && PYTHONPATH=src mypy src/animetta --ignore-missing-imports"
