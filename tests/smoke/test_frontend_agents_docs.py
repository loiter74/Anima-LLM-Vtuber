from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_agents_doc_matches_existing_vitest_suite() -> None:
    tests = sorted((ROOT / "frontend" / "src").rglob("*.test.ts"))
    agents = (ROOT / "frontend" / "AGENTS.md").read_text(encoding="utf-8")

    assert tests
    assert f"{len(tests)} Vitest" in agents
    assert "happy-dom" in agents
    assert "No frontend tests exist" not in agents
