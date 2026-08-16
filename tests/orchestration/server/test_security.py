from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from socketio.exceptions import ConnectionRefusedError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from animetta.config.security import SecurityConfig
from animetta.orchestration.server.routes import register_routes
from animetta.orchestration.server.security import (
    AuthenticationMiddleware,
    AuthPrincipal,
    RateLimitError,
    SecurityConfigurationError,
    SecurityRuntime,
    get_auth_routes,
    hash_password,
)

TEST_USERNAME = "admin"
TEST_PASSWORD = "correct horse battery staple"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def _runtime(
    token: str = "s" * 32,
    *,
    username: str = TEST_USERNAME,
    password_hash: str = TEST_PASSWORD_HASH,
    recorder=None,
) -> SecurityRuntime:
    return SecurityRuntime(
        profile="production",
        config=SecurityConfig(allowed_origins=("https://animetta.example",)),
        environ={
            "ANIMETTA_ACCESS_TOKEN": token,
            "ANIMETTA_AUTH_USERNAME": username,
            "ANIMETTA_AUTH_PASSWORD_HASH": password_hash,
        },
        observation_recorder=recorder,
    )


def test_production_rejects_missing_or_weak_access_token() -> None:
    for token in ("", "too-short"):
        try:
            _runtime(token)
        except SecurityConfigurationError as exc:
            assert "at least 32 bytes" in str(exc)
        else:
            raise AssertionError("weak production token was accepted")


@pytest.mark.parametrize(
    ("username", "password_hash", "message"),
    [
        ("", TEST_PASSWORD_HASH, "ANIMETTA_AUTH_USERNAME"),
        (TEST_USERNAME, "", "ANIMETTA_AUTH_PASSWORD_HASH"),
        (TEST_USERNAME, "invalid", "ANIMETTA_AUTH_PASSWORD_HASH"),
    ],
    ids=("missing-username", "missing-password-hash", "malformed-password-hash"),
)
def test_production_rejects_missing_or_invalid_account_credentials(
    username: str,
    password_hash: str,
    message: str,
) -> None:
    with pytest.raises(SecurityConfigurationError, match=message):
        _runtime(username=username, password_hash=password_hash)


def test_login_issues_strict_httponly_session_and_protects_api() -> None:
    security = _runtime()
    app = Starlette(routes=get_auth_routes(security))
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app, base_url="https://animetta.example") as client:
        unauthorized = client.get("/api/auth/session")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"

        machine_token_login = client.post("/api/auth/login", json={"token": "s" * 32})
        assert machine_token_login.status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "max-age=28800" in cookie
        assert client.get("/api/auth/session").json()["authenticated"] is True

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/auth/session").status_code == 401


def test_login_rate_limit_returns_retry_after() -> None:
    security = _runtime()
    app = Starlette(routes=get_auth_routes(security))
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app) as client:
        for _ in range(5):
            assert (
                client.post(
                    "/api/auth/login",
                    json={"username": TEST_USERNAME, "password": "wrong"},
                ).status_code
                == 401
            )
        limited = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "wrong"},
        )

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1


def test_auth_failures_are_written_as_content_free_ledger_records() -> None:
    recorder = MagicMock()
    recorder.start_trace = AsyncMock()
    recorder.start_operation = AsyncMock()
    recorder.finish_operation = AsyncMock()
    recorder.finish_trace = AsyncMock()
    security = _runtime(recorder=recorder)
    app = Starlette(routes=get_auth_routes(security))
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app) as client:
        response = client.get("/api/auth/session")

    assert response.status_code == 401
    started = recorder.start_operation.await_args.args[0]
    finished = recorder.finish_operation.await_args.args[0]
    assert started.name == "security:http"
    assert dict(started.attributes) == {"source": "http"}
    assert finished.error_type == "UNAUTHORIZED"


def test_token_is_not_present_in_runtime_representation() -> None:
    security = _runtime("private-token-that-is-long-enough-123")

    assert "private-token" not in repr(security)
    assert TEST_PASSWORD not in repr(security)
    assert security.verify_shared_token("private-token-that-is-long-enough-123") is True
    assert security.verify_shared_token("private-token-that-is-long-enough-124") is False
    assert security.verify_account_credentials(TEST_USERNAME, TEST_PASSWORD) is True
    assert security.verify_account_credentials(TEST_USERNAME, "wrong") is False


def test_health_is_public_while_ready_metrics_and_api_require_authentication() -> None:
    security = _runtime()

    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/health", ok),
            Route("/ready", ok),
            Route("/metrics", ok),
            Route("/api/private", ok),
        ]
    )
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        for path in ("/ready", "/metrics", "/api/private"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"
            assert (
                client.get(
                    path,
                    headers={"Authorization": f"Bearer {'s' * 32}"},
                ).status_code
                == 200
            )


def test_fixed_connection_chat_and_control_bursts() -> None:
    security = _runtime()

    for _ in range(10):
        security.check_connection_limit("127.0.0.1")
    with pytest.raises(RateLimitError):
        security.check_connection_limit("127.0.0.1")

    for _ in range(3):
        security.check_chat_limit("session")
    with pytest.raises(RateLimitError):
        security.check_chat_limit("session")

    for _ in range(10):
        security.check_control_limit("session")
    with pytest.raises(RateLimitError):
        security.check_control_limit("session")


@pytest.mark.asyncio
async def test_socket_requires_auth_and_chat_aliases_cannot_bypass_rate_limit(
    mock_socketio,
) -> None:
    security = _runtime()
    session_manager = MagicMock()
    handlers = register_routes(mock_socketio, session_manager, security=security)
    handlers.on_connect = AsyncMock()
    handlers.chat.on_text_event = AsyncMock()
    registered = {call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list}

    with pytest.raises(ConnectionRefusedError):
        await registered["connect"]("unauthorized", {"REMOTE_ADDR": "127.0.0.1"}, None)

    await registered["connect"](
        "authorized",
        {"REMOTE_ADDR": "127.0.0.2"},
        {"token": "s" * 32},
    )
    assert security.socket_principal("authorized") == AuthPrincipal(
        session_id="shared-token",
        source="socket-auth",
    )

    for _ in range(3):
        assert await registered["chat:text"]("authorized", {"text": "hello"}) is None
    limited = await registered["chat:developer_text"]("authorized", {"text": "bypass"})

    assert limited["error"]["code"] == "RATE_LIMITED"
    assert limited["retry_after"] >= 1
    assert handlers.chat.on_text_event.await_count == 3
