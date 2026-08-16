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
from animetta.orchestration.server.auth_display import RedisAuthDisplayStore
from animetta.orchestration.server.auth_session import RedisAuthSessionStore
from animetta.orchestration.server.auth_user import (
    AuthUserStore,
    AuthUserStoreUnavailableError,
)
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
        self.sets: dict[str, set[str]] = {}
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

    async def delete(self, *keys: str) -> int:
        self._check()
        deleted = 0
        for key in keys:
            deleted += int(self.values.pop(key, None) is not None)
            deleted += int(self.sets.pop(key, None) is not None)
        return deleted

    async def sadd(self, key: str, value: str) -> int:
        self._check()
        before = len(self.sets.setdefault(key, set()))
        self.sets[key].add(value)
        return int(len(self.sets[key]) > before)

    async def expire(self, key: str, _seconds: int) -> bool:
        self._check()
        return key in self.sets

    async def srem(self, key: str, value: str) -> int:
        self._check()
        before = len(self.sets.setdefault(key, set()))
        self.sets[key].discard(value)
        return int(len(self.sets[key]) < before)

    async def smembers(self, key: str) -> set[str]:
        self._check()
        return set(self.sets.get(key, set()))

    async def scard(self, key: str) -> int:
        self._check()
        return len(self.sets.get(key, set()))

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
    display_client: FakeRedis | None = None,
    display_store: RedisAuthDisplayStore | None = None,
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
        user_store=AuthUserStore(
            ":memory:",
            bootstrap_username=username,
            bootstrap_password_hash=password_hash,
        ),
        display_store=display_store
        or RedisAuthDisplayStore(
            None,
            pairing_ttl_seconds=300,
            credential_ttl_seconds=30 * 86400,
            poll_interval_seconds=3,
            max_active_credentials=5,
            client=display_client or FakeRedis(),
            code_hmac_key=b"display-route-test-key" * 2,
        ),
    )


def test_display_pairing_uses_separate_read_only_browser_credential() -> None:
    display_redis = FakeRedis()
    security = _runtime(display_client=display_redis)
    disconnect_display = AsyncMock()
    app = Starlette(routes=get_auth_routes(security, disconnect_display=disconnect_display))
    app.add_middleware(AuthenticationMiddleware, security=security)
    admin = TestClient(app, base_url="http://127.0.0.1")
    display = TestClient(app, base_url="http://127.0.0.1")
    machine = TestClient(app, base_url="http://127.0.0.1")

    assert (
        machine.get(
            "/api/auth/live-session",
            headers={"Authorization": f"Bearer {'s' * 32}"},
        ).status_code
        == 401
    )
    machine_approval = machine.post(
        "/api/auth/display/pairings/approve",
        headers={"Authorization": f"Bearer {'s' * 32}"},
        json={"code": "ABCD-EFGH", "name": "machine"},
    )
    assert machine_approval.status_code == 403
    assert machine_approval.json()["error"]["code"] == "ACCOUNT_ADMIN_REQUIRED"

    login = admin.post(
        "/api/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    changed = admin.post(
        "/api/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": "permanent-password"},
    )
    assert changed.status_code == 200

    pairing = display.post(
        "/api/auth/display/pairings",
        headers={"Origin": "http://127.0.0.1"},
    )
    assert pairing.status_code == 201
    assert "animetta_display_pairing=" in pairing.headers["set-cookie"]
    code = pairing.json()["pairing"]["code"]
    approved = admin.post(
        "/api/auth/display/pairings/approve",
        json={"code": code, "name": "B站直播场景"},
    )
    assert approved.status_code == 200

    exchanged = display.post(
        "/api/auth/display/pairings/exchange",
        headers={"Origin": "http://127.0.0.1"},
    )
    assert exchanged.status_code == 200
    assert "animetta_display=" in exchanged.headers["set-cookie"]
    device_id = exchanged.json()["display"]["id"]
    live_session = display.get("/api/auth/live-session")
    assert live_session.status_code == 200
    assert live_session.json()["auth_kind"] == "display"
    assert display.get("/api/auth/session").status_code == 401
    assert display.get("/api/auth/users").status_code == 401

    credentials = admin.get("/api/auth/display/credentials")
    assert credentials.status_code == 200
    assert [item["id"] for item in credentials.json()["credentials"]] == [device_id]
    security.bind_socket(
        "display-sid",
        AuthPrincipal(
            session_id="display-session",
            source="display",
            device_id=device_id,
            expires_at=9_999_999_999,
        ),
    )
    revoked = admin.delete(
        f"/api/auth/display/credentials/{device_id}",
    )
    assert revoked.status_code == 200
    disconnect_display.assert_awaited_once_with("display-sid")
    assert display.get("/api/auth/live-session").status_code == 401


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


@pytest.mark.asyncio
async def test_compose_default_password_hash_accepts_animetta_and_is_salted() -> None:
    first = hash_password("animetta")
    second = hash_password("animetta")
    security = _runtime(password_hash=DEFAULT_PASSWORD_HASH)

    assert first.startswith("scrypt-v1:")
    assert first != second
    assert await security.verify_account_credentials("admin", "animetta") is True
    assert await security.verify_account_credentials("admin", "wrong") is False
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
        session = client.get("/api/auth/session").json()
        assert session["authenticated"] is True
        assert session["password_change_required"] is True
        assert session["user"] == {
            "id": session["user"]["id"],
            "username": TEST_USERNAME,
            "role": "admin",
        }

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/auth/session").status_code == 401
        client.cookies.set("animetta_session", original_cookie)
        assert client.get("/api/auth/session").status_code == 401


def test_first_login_requires_password_change_and_replaces_all_sessions() -> None:
    security = _runtime()

    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=get_auth_routes(security) + [Route("/api/private", ok)],
    )
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app, base_url="https://animetta.example") as first:
        first_login = first.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        assert first_login.json()["password_change_required"] is True
        original_cookie = first.cookies.get("animetta_session")
        assert original_cookie
        assert first.get("/api/private").json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

        with TestClient(app, base_url="https://animetta.example") as second:
            assert (
                second.post(
                    "/api/auth/login",
                    json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
                ).status_code
                == 200
            )
            second_cookie = second.cookies.get("animetta_session")
            assert second_cookie

            changed = first.post(
                "/api/auth/password",
                json={
                    "current_password": TEST_PASSWORD,
                    "new_password": "a-new-secure-password",
                },
            )
            assert changed.status_code == 200
            replacement_cookie = first.cookies.get("animetta_session")
            assert replacement_cookie not in {None, original_cookie, second_cookie}
            assert first.get("/api/private").status_code == 200
            assert first.get("/api/auth/session").json()["password_change_required"] is False
            assert second.get("/api/auth/session").status_code == 401

        replay = TestClient(app, base_url="https://animetta.example")
        replay.cookies.set("animetta_session", original_cookie)
        assert replay.get("/api/auth/session").status_code == 401


def test_admin_manages_users_while_regular_users_and_bearer_are_forbidden() -> None:
    security = _runtime()
    app = Starlette(routes=get_auth_routes(security))
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app, base_url="https://animetta.example") as admin:
        admin.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        admin.post(
            "/api/auth/password",
            json={
                "current_password": TEST_PASSWORD,
                "new_password": "admin-permanent-password",
            },
        )
        created = admin.post(
            "/api/auth/users",
            json={
                "username": "Viewer",
                "role": "user",
                "temporary_password": "viewer-temporary-password",
            },
        )
        assert created.status_code == 201
        user_id = created.json()["user"]["id"]
        listed = admin.get("/api/auth/users")
        assert listed.status_code == 200
        assert {user["username"] for user in listed.json()["users"]} == {"admin", "Viewer"}

        bearer = admin.get(
            "/api/auth/users",
            headers={"Authorization": f"Bearer {'s' * 32}"},
        )
        assert bearer.status_code == 403
        assert bearer.json()["error"]["code"] == "ACCOUNT_ADMIN_REQUIRED"

        with TestClient(app, base_url="https://animetta.example") as viewer:
            login = viewer.post(
                "/api/auth/login",
                json={"username": "viewer", "password": "viewer-temporary-password"},
            )
            assert login.json()["password_change_required"] is True
            assert (
                viewer.get("/api/auth/users").json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
            )
            viewer.post(
                "/api/auth/password",
                json={
                    "current_password": "viewer-temporary-password",
                    "new_password": "viewer-permanent-password",
                },
            )
            assert viewer.get("/api/auth/users").json()["error"]["code"] == "ACCOUNT_ADMIN_REQUIRED"

            disabled = admin.patch(f"/api/auth/users/{user_id}", json={"enabled": False})
            assert disabled.status_code == 200
            assert viewer.get("/api/auth/session").json()["error"]["code"] == "UNAUTHORIZED"

        assert (
            admin.post(
                "/api/auth/login",
                json={"username": "viewer", "password": "viewer-permanent-password"},
            ).json()["error"]["code"]
            == "ACCOUNT_DISABLED"
        )
        assert admin.patch(f"/api/auth/users/{user_id}", json={"enabled": True}).status_code == 200
        reset = admin.post(
            f"/api/auth/users/{user_id}/reset-password",
            json={"temporary_password": "viewer-reset-password"},
        )
        assert reset.status_code == 200
        assert reset.json()["user"]["must_change_password"] is True


def test_admin_cannot_mutate_own_access_or_reuse_username() -> None:
    security = _runtime()
    app = Starlette(routes=get_auth_routes(security))
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app, base_url="https://animetta.example") as client:
        client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        client.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": "new-admin-password"},
        )
        user_id = client.get("/api/auth/session").json()["user"]["id"]
        self_mutation = client.patch(f"/api/auth/users/{user_id}", json={"role": "user"})
        assert self_mutation.status_code == 409
        assert self_mutation.json()["error"]["code"] == "SELF_ADMIN_MUTATION_FORBIDDEN"
        conflict = client.post(
            "/api/auth/users",
            json={
                "username": " ADMIN ",
                "role": "user",
                "temporary_password": "temporary-password",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "USERNAME_CONFLICT"


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


def test_browser_auth_fails_closed_when_user_store_is_unavailable(monkeypatch) -> None:
    security = _runtime()
    monkeypatch.setattr(
        security._user_store,
        "authenticate",
        AsyncMock(side_effect=AuthUserStoreUnavailableError("database unavailable")),
    )

    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=get_auth_routes(security) + [Route("/api/private", ok)],
    )
    app.add_middleware(AuthenticationMiddleware, security=security)

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        bearer = client.get(
            "/api/private",
            headers={"Authorization": f"Bearer {'s' * 32}"},
        )

    assert login.status_code == 503
    assert login.json()["error"]["code"] == "AUTH_USER_STORE_UNAVAILABLE"
    assert bearer.status_code == 200


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


@pytest.mark.asyncio
async def test_token_is_not_present_in_runtime_representation() -> None:
    security = _runtime("private-token-that-is-long-enough-123")

    assert "private-token" not in repr(security)
    assert TEST_PASSWORD not in repr(security)
    assert security.verify_shared_token("private-token-that-is-long-enough-123") is True
    assert security.verify_shared_token("private-token-that-is-long-enough-124") is False
    assert await security.verify_account_credentials(TEST_USERNAME, TEST_PASSWORD) is True
    assert await security.verify_account_credentials(TEST_USERNAME, "wrong") is False


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
async def test_display_socket_is_read_only_for_every_registered_business_event(
    mock_socketio,
) -> None:
    security = _runtime()
    handlers = register_routes(mock_socketio, MagicMock(), security=security)
    handlers.chat.on_text_event = AsyncMock()
    security.bind_socket(
        "display-sid",
        AuthPrincipal(
            session_id="display-session",
            source="display",
            device_id="device-id",
            expires_at=9_999_999_999,
        ),
    )
    registered = {call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list}

    for event, payload in (
        ("chat:text", {"text": "forbidden"}),
        ("config:get", {}),
        ("bilibili:connect", {}),
        ("minecraft:status", {}),
        ("sing:process", {}),
    ):
        result = await registered[event]("display-sid", payload)
        assert result == {
            "ok": False,
            "error": {
                "code": "DISPLAY_READ_ONLY",
                "message": "Display credentials are read-only",
            },
        }
    handlers.chat.on_text_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_display_cookie_authenticates_only_from_its_bound_socket_origin() -> None:
    display_store = RedisAuthDisplayStore(
        None,
        pairing_ttl_seconds=300,
        credential_ttl_seconds=30 * 86400,
        poll_interval_seconds=3,
        max_active_credentials=5,
        client=FakeRedis(),
        code_hmac_key=b"display-socket-test-key" * 2,
    )
    security = _runtime(display_store=display_store)
    pairing = await display_store.create_pairing(origin="http://127.0.0.1", now=2_000_000_000)
    await display_store.approve_pairing(
        pairing.code,
        name="B站直播场景",
        approved_by_user_id="admin-id",
        now=2_000_000_001,
    )
    exchanged = await display_store.exchange_pairing(
        pairing.token,
        origin="http://127.0.0.1",
        now=2_000_000_002,
    )
    assert exchanged is not None
    token, credential = exchanged
    environ = {
        "asgi.scope": {
            "headers": [
                (b"origin", b"http://127.0.0.1"),
                (b"cookie", f"animetta_display={token}".encode()),
            ]
        }
    }

    principal = await security.authenticate_socket(environ, None)

    assert principal == AuthPrincipal(
        session_id=credential.session_id,
        source="display",
        device_id=credential.id,
        expires_at=credential.expires_at,
    )
    environ["asgi.scope"]["headers"][0] = (b"origin", b"http://localhost")
    assert await security.authenticate_socket(environ, None) is None


@pytest.mark.asyncio
async def test_socket_rejects_session_until_required_password_change(
    mock_socketio,
) -> None:
    security = _runtime()
    token, _, _ = await security.login(TEST_USERNAME, TEST_PASSWORD)
    handlers = register_routes(mock_socketio, MagicMock(), security=security)
    handlers.on_connect = AsyncMock()
    registered = {call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list}

    with pytest.raises(ConnectionRefusedError) as refused:
        await registered["connect"](
            "restricted",
            {
                "REMOTE_ADDR": "127.0.0.3",
                "asgi.scope": {
                    "headers": [
                        (b"cookie", f"animetta_session={token}".encode()),
                    ]
                },
            },
            None,
        )

    assert "PASSWORD_CHANGE_REQUIRED" in str(refused.value)
    assert security.socket_principal("restricted") is None


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
