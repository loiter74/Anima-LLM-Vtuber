"""Shared-token authentication, browser sessions, and fixed production limits."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from animetta.config.manifest import EffectiveConfig
from animetta.config.security import SecurityConfig
from animetta.observability.domain import (
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from animetta.observability.ports import NoOpObservationRecorder, ObservationRecorder

SESSION_COOKIE = "animetta_session"


class SecurityConfigurationError(RuntimeError):
    """Raised before serving when production security is unsafe."""


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Authenticated shared-session identity used for rate-limit ownership."""

    session_id: str
    source: str


class RateLimitError(RuntimeError):
    """Stable error containing the time until another attempt is allowed."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("RATE_LIMITED")
        self.retry_after = max(1, retry_after)


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """Small in-process token bucket for per-instance abuse protection."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def consume(
        self,
        category: str,
        owner: str,
        *,
        rate: int,
        period_seconds: int,
        burst: int,
    ) -> None:
        now = time.monotonic()
        key = (category, owner)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(burst), updated_at=now)
            self._buckets[key] = bucket
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(float(burst), bucket.tokens + elapsed * rate / period_seconds)
        bucket.updated_at = now
        if bucket.tokens < 1.0:
            wait = (1.0 - bucket.tokens) * period_seconds / rate
            raise RateLimitError(int(wait) + 1)
        bucket.tokens -= 1.0


class SecurityRuntime:
    """Runtime-only secret boundary. Tokens never enter Pydantic snapshots."""

    def __init__(
        self,
        *,
        profile: str,
        config: SecurityConfig,
        environ: dict[str, str] | None = None,
        observation_recorder: ObservationRecorder | None = None,
    ) -> None:
        self.profile = profile
        self.config = config
        self.enabled = profile == "production"
        self._environ = environ if environ is not None else os.environ
        self._limiter = TokenBucketLimiter()
        self._socket_principals: dict[str, AuthPrincipal] = {}
        self._observation_recorder = observation_recorder or NoOpObservationRecorder()
        token = self._environ.get(config.access_token_env, "")
        if self.enabled and len(token.encode("utf-8")) < 32:
            raise SecurityConfigurationError(
                f"{config.access_token_env} must contain at least 32 bytes in production"
            )
        self._token = token.encode("utf-8")
        self._signing_key = hashlib.sha256(b"animetta-session\0" + self._token).digest()

    @classmethod
    def from_effective_config(
        cls,
        config: EffectiveConfig | None,
        *,
        observation_recorder: ObservationRecorder | None = None,
    ) -> SecurityRuntime:
        if config is None:
            return cls(
                profile="test",
                config=SecurityConfig(allowed_origins=("http://127.0.0.1:8000",)),
                observation_recorder=observation_recorder,
            )
        return cls(
            profile=config.profile,
            config=config.security,
            observation_recorder=observation_recorder,
        )

    async def record_error(self, code: str, *, surface: str) -> None:
        """Persist a content-free security failure without weakening request handling."""
        recorder = self._observation_recorder
        trace_id = uuid.uuid4().hex
        operation_id = uuid.uuid4().hex
        now = time.time()
        try:
            await recorder.start_trace(
                TraceStarted(
                    identity=TraceIdentity(
                        message_id=trace_id,
                        conversation_id=trace_id,
                        task_id=trace_id,
                        session_id="security",
                    ),
                    runtime_profile=self.profile,
                    input_type="security",
                    privacy_mode=PrivacyMode.REDACTED,
                    started_at=now,
                    attributes={"source": surface},
                )
            )
            await recorder.start_operation(
                OperationStarted(
                    operation_id=operation_id,
                    trace_id=trace_id,
                    parent_operation_id=None,
                    layer=ObservationLayer.TRANSPORT,
                    name=f"security:{surface}",
                    critical_path=True,
                    started_at=now,
                    attributes={"source": surface},
                )
            )
            await recorder.finish_operation(
                OperationFinished(
                    operation_id=operation_id,
                    status=OperationStatus.ERROR,
                    finished_at=time.time(),
                    error_type=code,
                    error_summary=code,
                )
            )
            await recorder.finish_trace(
                trace_id,
                TraceOutcome.FAILED,
                finished_at=time.time(),
                error_type=code,
                error_summary=code,
                attributes={"source": surface},
            )
        except Exception:
            return

    def check_login_limit(self, ip: str) -> None:
        if self.enabled:
            self._limiter.consume("login", ip, rate=5, period_seconds=300, burst=5)

    def check_connection_limit(self, ip: str) -> None:
        if self.enabled:
            self._limiter.consume("connection", ip, rate=10, period_seconds=60, burst=10)

    def check_chat_limit(self, session_id: str) -> None:
        if self.enabled:
            self._limiter.consume("chat", session_id, rate=12, period_seconds=60, burst=3)

    def check_control_limit(self, session_id: str) -> None:
        if self.enabled:
            self._limiter.consume("control", session_id, rate=30, period_seconds=60, burst=10)

    def bind_socket(self, sid: str, principal: AuthPrincipal) -> None:
        self._socket_principals[sid] = principal

    def unbind_socket(self, sid: str) -> None:
        self._socket_principals.pop(sid, None)

    def socket_principal(self, sid: str) -> AuthPrincipal | None:
        return self._socket_principals.get(sid)

    def socket_rate_owner(self, sid: str) -> str | None:
        principal = self.socket_principal(sid)
        if principal is not None:
            return principal.session_id
        return "nonproduction" if not self.enabled else None

    def verify_shared_token(self, supplied: str) -> bool:
        if not self._token:
            return not self.enabled
        return hmac.compare_digest(supplied.encode("utf-8"), self._token)

    def issue_session(self, *, now: int | None = None) -> tuple[str, int]:
        issued_at = int(time.time()) if now is None else now
        expires_at = issued_at + self.config.session_hours * 3600
        payload = _b64url(
            json.dumps(
                {"iat": issued_at, "exp": expires_at},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = _b64url(hmac.digest(self._signing_key, payload.encode("ascii"), "sha256"))
        return f"{payload}.{signature}", expires_at

    def verify_session(self, value: str, *, now: int | None = None) -> AuthPrincipal | None:
        try:
            payload, supplied_signature = value.split(".", 1)
            expected_signature = _b64url(
                hmac.digest(self._signing_key, payload.encode("ascii"), "sha256")
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return None
            decoded = json.loads(_b64url_decode(payload))
            current = int(time.time()) if now is None else now
            if current >= int(decoded["exp"]):
                return None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        session_id = hashlib.sha256(value.encode("ascii")).hexdigest()[:24]
        return AuthPrincipal(session_id=session_id, source="cookie")

    def authenticate_http(self, request: Request) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(session_id="nonproduction", source="disabled")
        bearer = _bearer_token(request.headers)
        if bearer is not None and self.verify_shared_token(bearer):
            return AuthPrincipal(session_id="shared-token", source="bearer")
        cookie = request.cookies.get(SESSION_COOKIE)
        return self.verify_session(cookie) if cookie else None

    def authenticate_socket(
        self,
        environ: dict[str, Any],
        auth: dict[str, Any] | None,
    ) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(session_id="nonproduction", source="disabled")
        token = str((auth or {}).get("token") or "")
        if token and self.verify_shared_token(token):
            return AuthPrincipal(session_id="shared-token", source="socket-auth")
        scope = dict(environ.get("asgi.scope") or {})
        scope.setdefault("headers", [])
        headers = Headers(scope=scope)
        bearer = _bearer_token(headers)
        if bearer is not None and self.verify_shared_token(bearer):
            return AuthPrincipal(session_id="shared-token", source="bearer")
        cookies = SimpleCookie()
        cookies.load(headers.get("cookie", ""))
        morsel = cookies.get(SESSION_COOKIE)
        return self.verify_session(morsel.value) if morsel else None


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Protect sensitive HTTP routes while leaving liveness and login public."""

    def __init__(self, app: Any, *, security: SecurityRuntime) -> None:
        super().__init__(app)
        self._security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._security.enabled or not _requires_authentication(request.url.path):
            return await call_next(request)
        principal = self._security.authenticate_http(request)
        if principal is None:
            await self._security.record_error("UNAUTHORIZED", surface="http")
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        request.state.auth_principal = principal
        return await call_next(request)


def get_auth_routes(security: SecurityRuntime) -> list[Any]:
    """Build login/session/logout routes without exposing the configured secret."""

    from starlette.routing import Route

    async def login(request: Request) -> JSONResponse:
        ip = request.client.host if request.client else "unknown"
        try:
            security.check_login_limit(ip)
        except RateLimitError as exc:
            await security.record_error("RATE_LIMITED", surface="login")
            return error_response(
                "RATE_LIMITED",
                "Too many login attempts",
                status_code=429,
                retry_after=exc.retry_after,
            )
        try:
            data = await request.json()
        except (json.JSONDecodeError, TypeError):
            data = {}
        supplied = str(data.get("token") or "") if isinstance(data, dict) else ""
        if not security.verify_shared_token(supplied):
            await security.record_error("UNAUTHORIZED", surface="login")
            return error_response("UNAUTHORIZED", "Invalid credentials", status_code=401)
        session, expires_at = security.issue_session()
        response = JSONResponse({"ok": True, "expires_at": expires_at})
        response.set_cookie(
            SESSION_COOKIE,
            session,
            max_age=security.config.session_hours * 3600,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return response

    async def session(request: Request) -> JSONResponse:
        principal = security.authenticate_http(request)
        if principal is None:
            await security.record_error("UNAUTHORIZED", surface="session")
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        return JSONResponse({"ok": True, "authenticated": True, "source": principal.source})

    async def logout(request: Request) -> JSONResponse:
        del request
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
        return response

    return [
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/session", session, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
    ]


def error_response(
    code: str,
    message: str,
    *,
    status_code: int,
    retry_after: int | None = None,
) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=headers,
    )


def _requires_authentication(path: str) -> bool:
    if path in {"/health", "/api/auth/login"}:
        return False
    return path in {"/ready", "/metrics"} or path.startswith("/api/")


def _bearer_token(headers: Headers) -> str | None:
    authorization = headers.get("authorization", "")
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value:
        return value
    return None


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
