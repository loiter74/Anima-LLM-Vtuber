from __future__ import annotations

"""
Tests for socketio_server module — server entry point.

The socketio_server module executes code at import time (dotenv loading,
argparse, UserSettings instantiation, log level configuration).  This test
file carefully mocks those side effects before the import, then tests each
public/private function in isolation.
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────────


def _noop_coro():
    """Return a noop coroutine object (each call creates a fresh one)."""

    async def _inner():
        pass

    return _inner()


# ── Module-level fixture ────────────────────────────────────────────


@pytest.fixture(scope="module")
def mod():
    """Import socketio_server module once with side-effect mocks.

    The module runs code at import time:
    - ``parse_server_args()`` on line 64 (reads ``sys.argv``)
    - ``load_dotenv()`` in the ``try`` block on line 22
    - ``UserSettings(...)`` on line 71 (reads ``.user_settings.yaml``)
    - ``logger_manager.set_level(...)`` on line 75

    This fixture:
    - Sets ``sys.argv`` so argparse doesn't error
    - Patches ``dotenv.load_dotenv`` so no real ``.env`` is loaded
    - Patches ``UserSettings._load`` so no YAML file is read
    """
    original_argv = sys.argv.copy()
    sys.argv = ["test_prog"]

    # Ensure a fresh import
    if "animetta.core.socketio_server" in sys.modules:
        del sys.modules["animetta.core.socketio_server"]

    with (
        patch("dotenv.load_dotenv"),
        patch(
            "animetta.config.user.UserSettings._load",
            return_value={"log_level": "INFO"},
        ),
    ):
        import animetta.core.socketio_server as m

    sys.argv = original_argv
    return m


# ── TestParseServerArgs ─────────────────────────────────────────────


class TestUserSettingsRuntimePath:
    """Runtime user settings location."""

    def test_user_settings_uses_project_root(self, mod):
        """User settings should live at project root, not under src/."""

        project_root = Path(__file__).resolve().parents[2]

        assert mod.user_settings.config_file == project_root / ".user_settings.yaml"


class TestParseServerArgs:
    """parse_server_args() — CLI argument parsing."""

    def test_parses_redis_url_flag(self, mod):
        """--redis-url flag is parsed correctly."""
        with patch.object(sys, "argv", ["prog", "--redis-url", "redis://localhost:6379"]):
            args = mod.parse_server_args()
        assert args.redis_url == "redis://localhost:6379"

    def test_defaults_to_none_when_flag_missing(self, mod):
        """When --redis-url is absent, redis_url is None."""
        with patch.object(sys, "argv", ["prog"]):
            args = mod.parse_server_args()
        assert args.redis_url is None


def test_run_server_uses_the_bounded_singing_websocket_frame_limit(mod, monkeypatch) -> None:
    config = MagicMock()
    config.system.host = "127.0.0.1"
    config.system.port = 12394
    server = MagicMock()
    monkeypatch.setattr(mod, "global_config", config)

    with (
        patch("atexit.register"),
        patch.object(mod, "init_config"),
        patch.object(mod, "create_server", return_value=server),
        patch.object(mod.uvicorn, "run") as run,
    ):
        mod.run_server()

    run.assert_called_once_with(
        "animetta.core.socketio_server:get_asgi_app",
        host="127.0.0.1",
        port=12394,
        log_level="info",
        factory=True,
        ws_max_size=96 * 1024 * 1024,
    )


# ── TestInitConfig ──────────────────────────────────────────────────


class TestInitConfig:
    """init_config() — global configuration loading."""

    def test_loads_from_default_path(self, mod):
        """Without config_path, resolves the canonical manifest once."""
        mock_config = MagicMock()
        mock_config.system.host = "localhost"
        mock_config.system.port = 12394

        mod.global_config = None
        with patch(
            "animetta.core.socketio_server.load_effective_config",
            return_value=mock_config,
        ) as load:
            result = mod.init_config()

        assert mod.global_config is mock_config
        assert result is mock_config
        load.assert_called_once_with(mod._PROJECT_ROOT / "config" / "animetta.yaml")

    def test_loads_from_specified_path(self, mod):
        """An explicit manifest path is forwarded to the canonical loader."""
        mock_config = MagicMock()
        mock_config.system.host = "localhost"
        mock_config.system.port = 12394

        mod.global_config = None
        with patch(
            "animetta.core.socketio_server.load_effective_config",
            return_value=mock_config,
        ) as load:
            result = mod.init_config(config_path="/custom/path/animetta.yaml")

        assert mod.global_config is mock_config
        assert result is mock_config
        load.assert_called_once_with(Path("/custom/path/animetta.yaml"))

    def test_repeated_init_reuses_the_same_effective_config(self, mod):
        mock_config = MagicMock()
        mock_config.system.host = "localhost"
        mock_config.system.port = 12394
        mod.global_config = None

        with patch(
            "animetta.core.socketio_server.load_effective_config",
            return_value=mock_config,
        ) as load:
            first = mod.init_config()
            second = mod.init_config()

        assert first is second is mock_config
        load.assert_called_once()


# ── TestSetupCheckpointer ───────────────────────────────────────────


class TestSetupCheckpointer:
    """_setup_checkpointer() — LangGraph checkpointer configuration."""

    # -- Helpers ------------------------------------------------------

    @staticmethod
    def _patch_redis_url(mod, url):
        """Replace ``_server_args`` with a namespace for the test duration."""
        original = mod._server_args
        mod._server_args = argparse.Namespace(redis_url=url)
        return original

    # -- Tests --------------------------------------------------------

    def test_sets_redis_checkpointer_when_redis_url_given(self, mod):
        """With a --redis-url, AsyncRedisSaver is created and registered."""
        original = self._patch_redis_url(mod, "redis://localhost:6379")

        mock_checkpointer = MagicMock()
        with (
            patch("animetta.core.socketio_server.set_external_checkpointer") as mock_set,
            patch(
                "animetta.core.socketio_server.AsyncRedisSaver",
                return_value=mock_checkpointer,
            ),
        ):
            mod._setup_checkpointer()

        mock_set.assert_called_once_with(mock_checkpointer)

        mod._server_args = original

    def test_skips_when_redis_url_not_set(self, mod):
        """When --redis-url is None, no external checkpointer is registered."""
        # _server_args.redis_url is None from import-time default
        with patch("animetta.core.socketio_server.set_external_checkpointer") as mock_set:
            mod._setup_checkpointer()

        mock_set.assert_not_called()

    def test_handles_exception_gracefully(self, mod):
        """If AsyncRedisSaver raises, the error is caught and swallowed."""
        original = self._patch_redis_url(mod, "redis://localhost:6379")

        with (
            patch("animetta.core.socketio_server.set_external_checkpointer") as mock_set,
            patch(
                "animetta.core.socketio_server.AsyncRedisSaver",
                side_effect=ConnectionError("redis not available"),
            ),
        ):
            # Should not raise
            mod._setup_checkpointer()

        mock_set.assert_not_called()

        mod._server_args = original


# ── TestGetAsgiApp ──────────────────────────────────────────────────


class TestGetAsgiApp:
    """get_asgi_app() — lazy-init ASGI application factory."""

    # -- Helpers ------------------------------------------------------

    @staticmethod
    def _reset_module_state(mod):
        """Reset lazy-init globals so get_asgi_app() re-runs."""
        mod.asgi_app = None
        mod._server = None
        mod._INIT_DONE.clear()
        mod._INIT_TASKS.clear()

    # -- Tests --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_returns_asgi_app(self, mod):
        """First call creates and returns an ASGI app."""
        self._reset_module_state(mod)
        mod.global_config = MagicMock()

        mock_asgi_app = MagicMock()
        mock_server = MagicMock()
        mock_server.get_app.return_value = mock_asgi_app
        mock_server.model_manager = MagicMock()
        mock_server.model_manager.warmup = MagicMock(side_effect=_noop_coro)
        mock_server.prewarm_services = MagicMock(side_effect=_noop_coro)

        with (
            patch("animetta.core.socketio_server._setup_checkpointer") as mock_check,
            patch("animetta.core.socketio_server.create_server", return_value=mock_server),
        ):
            result = mod.get_asgi_app()

        assert result is mock_asgi_app
        mock_check.assert_called_once()
        mock_server.set_user_settings.assert_called_once()
        mock_server.get_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_caches_result_across_calls(self, mod):
        """Subsequent calls return the cached ASGI app without re-creating."""
        self._reset_module_state(mod)
        mod.global_config = MagicMock()

        mock_asgi_app = MagicMock()
        mock_server = MagicMock()
        mock_server.get_app.return_value = mock_asgi_app
        mock_server.model_manager = MagicMock()
        mock_server.model_manager.warmup = MagicMock(side_effect=_noop_coro)
        mock_server.prewarm_services = MagicMock(side_effect=_noop_coro)

        with (
            patch("animetta.core.socketio_server._setup_checkpointer"),
            patch("animetta.core.socketio_server.create_server", return_value=mock_server),
        ):
            result1 = mod.get_asgi_app()
            result2 = mod.get_asgi_app()

        assert result1 is result2  # Same cached object
        mock_server.get_app.assert_called_once()  # Only built once

    @pytest.mark.asyncio
    async def test_calls_init_config_when_global_config_none(self, mod):
        """If global_config is None, get_asgi_app calls init_config()."""
        self._reset_module_state(mod)
        mod.global_config = None

        mock_server = MagicMock()
        mock_server.model_manager = MagicMock()
        mock_server.model_manager.warmup = MagicMock(side_effect=_noop_coro)
        mock_server.prewarm_services = MagicMock(side_effect=_noop_coro)

        with (
            patch("animetta.core.socketio_server.init_config") as mock_init,
            patch("animetta.core.socketio_server._setup_checkpointer"),
            patch("animetta.core.socketio_server.create_server", return_value=mock_server),
        ):
            mod.get_asgi_app()

        mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_init_config_when_config_already_loaded(self, mod):
        """If global_config is already set, init_config is NOT called."""
        self._reset_module_state(mod)
        mod.global_config = MagicMock()  # Already loaded

        mock_server = MagicMock()
        mock_server.model_manager = MagicMock()
        mock_server.model_manager.warmup = MagicMock(side_effect=_noop_coro)
        mock_server.prewarm_services = MagicMock(side_effect=_noop_coro)

        with (
            patch("animetta.core.socketio_server.init_config") as mock_init,
            patch("animetta.core.socketio_server._setup_checkpointer"),
            patch("animetta.core.socketio_server.create_server", return_value=mock_server),
        ):
            mod.get_asgi_app()

        mock_init.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_asgi_app_delegates_tracing_to_server_factory(self, mod):
        """Tracing bootstrap is owned by create_server(), not the core ASGI factory."""
        self._reset_module_state(mod)
        mod.global_config = MagicMock()

        mock_server = MagicMock()
        mock_server.model_manager = MagicMock()
        mock_server.model_manager.warmup = MagicMock(side_effect=_noop_coro)
        mock_server.prewarm_services = MagicMock(side_effect=_noop_coro)

        with (
            patch("animetta.core.socketio_server._setup_checkpointer"),
            patch("animetta.core.socketio_server.create_server", return_value=mock_server),
        ):
            mod.get_asgi_app()

        assert not hasattr(mod, "init_tracing")


# ── TestModuleLevelVars ─────────────────────────────────────────────


class TestModuleLevelVars:
    """Module-level variables are properly initialised at import time."""

    def test_global_config_exists(self, mod):
        assert hasattr(mod, "global_config")

    def test_user_settings_exists(self, mod):
        assert hasattr(mod, "user_settings")

    def test_server_args_exists(self, mod):
        assert hasattr(mod, "_server_args")
        # Parsed at import time — our fixture used sys.argv = ["test_prog"]
        assert mod._server_args.redis_url is None

    def test_asgi_app_exists(self, mod):
        """asgi_app module-level variable exists (lazy init)."""
        assert hasattr(mod, "asgi_app")

    def test_server_exists(self, mod):
        """_server module-level variable exists (lazy init)."""
        assert hasattr(mod, "_server")


class TestFrontendServingMiddleware:
    """The SPA fallback must not swallow operational endpoints."""

    def test_ready_path_passes_through_instead_of_returning_index(
        self,
        mod,
        tmp_path,
    ):
        frontend_dist = tmp_path / "frontend" / "dist"
        frontend_dist.mkdir(parents=True)
        (frontend_dist / "index.html").write_text(
            "<html>spa fallback</html>",
            encoding="utf-8",
        )

        async def ready_endpoint(_request):
            return JSONResponse({"ready": False}, status_code=503)

        app = Starlette(routes=[Route("/ready", ready_endpoint)])
        with patch.object(mod, "_PROJECT_ROOT", tmp_path):
            wrapped = mod._wrap_with_frontend_serving(app)
            with TestClient(wrapped) as client:
                response = client.get("/ready")

        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"ready": False}
