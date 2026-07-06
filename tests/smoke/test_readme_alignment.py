from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_describes_current_backend_stack() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "WebSocket Server (Starlette + Socket.IO ASGI)" in readme
    assert "| **后端** | Starlette · Socket.IO ASGI |" in readme
    assert "FastAPI + Socket.IO" not in readme
    assert "FastAPI · Socket.IO" not in readme


def test_readme_frontend_commands_use_pnpm() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "cd frontend && pnpm install" in readme
    assert "cd frontend && pnpm dev" in readme
    assert "cd frontend && npm install" not in readme
    assert "cd frontend && npm run dev" not in readme
