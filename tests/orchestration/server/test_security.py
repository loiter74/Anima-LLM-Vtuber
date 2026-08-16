from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from socketio.exceptions import ConnectionRefusedError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from animetta.config.security import SecurityConfig
from animetta.orchestration.server.auth_session import RedisAuthSessionStore
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
DEFAULT_PASSWORD_HASH = (
    "scrypt-v1:hCKIbfm-qsCRNXImQMlMtQ:Y8LBHJTp-XPsjB0z3Jqs_V3hV8MuGPCVMpN0BsSlcs4"
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.unavailable = False

    async def ping(self) -> bool:
        self._check()
        return True

    async def set(self, key: str, value: str, **_kwargs) -> bool:
        self._check()
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        self._check()
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        self._check()
        return int(self.values.pop(key, None) is not None)

    def _check(self) -> None:
        if self.unavailable:
            raise ConnectionError("redis unavailable")


def _runtime(
    token: str = "s" * 32,
    *,
    username: str = TEST_USERNAME,
    password_hash: str = TEST_PASSWORD_HASH,
    recorder=None,
    session_client: FakeRedis | None = None,
) -> SecurityRuntime:
    client = session_client or FakeRedis()
    return SecurityRuntime(
        profile="production",
        config=SecurityConfig(allowed_origins=("https://animetta.example",)),
        environ={
            "ANIMETTA_ACCESS_TOKEN": token,
            "ANIMETTA_AUTH_USERNAME": username,
            "ANIMETTA_AUTH_PASSWORD_HASH": password_hash,
        },
        observation_recorder=recorder,
        session_store=RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=client),
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


def test_compose_default_password_hash_accepts_animetta_and_is_salted() -> None:
    first = hash_password("animetta")
    second = hash_password("animetta")
    security = _runtime(password_hash=DEFAULT_PASSWORD_HASH)

    assert first.startswith("scrypt-v1:")
    assert first != second
    assert security.verify_account_credentials("admin", "animetta") is True
    assert security.verify_account_credentials("admin", "wrong") is False
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "ANIMETTA_AUTH_USERNAME=${ANIMETTA_AUTH_USERNAME:-admin}" in compose
    assert (
        f"ANIMETTA_AUTH_PASSWORD_HASH=${{ANIMETTA_AUTH_PASSWORD_HASH:-{DEFAULT_PASSWORD_HASH}}}"
        in compose
    )


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
        original_cookie = client.cookies.get("animetta_session")
        assert original_cookie
        assert "." not in original_cookie
        assert client.get("/api/auth/session").json()["authenticated"] is True

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/auth/session").status_code == 401
        client.cookies.set("animetta_session", original_cookie)
        assert client.get("/api/auth/session").status_code == 401


def test_browser_auth_fails_closed_when_session_store_is_unavailable() -> None:
    session_client = FakeRedis()
    security = _runtime(session_client=session_client)

    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=get_auth_routes(security) + [Route("/api/private", ok)],
    )
    app.add_middleware(AuthenticationMiddleware, security=security)
    session_client.unavailable = True

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        client.cookies.set("animetta_session", "a" * 43)
        session = client.get("/api/auth/session")
        protected = client.get("/api/private")
        bearer = client.get(
            "/api/private",
            headers={"Authorization": f"Bearer {'s' * 32}"},
        )
        logout = client.post("/api/auth/logout")

    for response in (login, session, protected, logout):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTH_SESSION_STORE_UNAVAILABLE"
    assert bearer.status_code == 200
    assert "max-age=0" in logout.headers["set-cookie"].lower()


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
    assert started.name == "security:session"
    assert dict(started.attributes) == {"source": "session"}
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


@pytest.mark.asyncio
async def test_cookie_socket_fails_closed_but_machine_token_ignores_redis_failure(
    mock_socketio,
) -> None:
    session_client = FakeRedis()
    security = _runtime(session_client=session_client)
    session_manager = MagicMock()
    handlers = register_routes(mock_socketio, session_manager, security=security)
    handlers.on_connect = AsyncMock()
    registered = {call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list}
    session_client.unavailable = True

    with pytest.raises(ConnectionRefusedError) as refused:
        await registered["connect"](
            "cookie",
            {
                "REMOTE_ADDR": "127.0.0.1",
                "asgi.scope": {"headers": [(b"cookie", b"animetta_session=" + b"a" * 43)]},
            },
            None,
        )

    assert "AUTH_SESSION_STORE_UNAVAILABLE" in str(refused.value)
    await registered["connect"](
        "machine",
        {"REMOTE_ADDR": "127.0.0.2"},
        {"token": "s" * 32},
    )
    assert security.socket_principal("machine") == AuthPrincipal(
        session_id="shared-token",
        source="socket-auth",
    )
