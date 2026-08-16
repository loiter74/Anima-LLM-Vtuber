"""Machine-token authentication, account sessions, and fixed production limits."""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
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
from animetta.utils.env_helper import get_data_dir

from .auth_display import (
    AuthDisplayHealth,
    AuthDisplayStore,
    DisplayCredential,
    PendingPairing,
    RedisAuthDisplayStore,
)
from .auth_password import (
    PASSWORD_HASH_SCHEME,
    hash_password,
    parse_password_hash,
    validate_password,
    verify_password,
)
from .auth_session import (
    AuthSessionHealth,
    AuthSessionStore,
    AuthSessionStoreUnavailableError,
    RedisAuthSessionStore,
)
from .auth_user import (
    AuthUserHealth,
    AuthUserStore,
    AuthUserStoreUnavailableError,
    UserAccount,
    UserNotFoundError,
    UserRole,
)

SESSION_COOKIE = "animetta_session"
DISPLAY_PAIRING_COOKIE = "animetta_display_pairing"
DISPLAY_COOKIE = "animetta_display"


class SecurityConfigurationError(RuntimeError):
    """Raised before serving when production security is unsafe."""


class AccountDisabledError(RuntimeError):
    """Raised when a disabled account attempts to authenticate."""


class PasswordChangeRequiredError(RuntimeError):
    """Raised when a restricted first-login session reaches product APIs."""


class CurrentPasswordInvalidError(RuntimeError):
    """Raised when a self-service password check fails."""


class SamePasswordError(RuntimeError):
    """Raised when a password change would keep the current credential."""


class AccountAdminRequiredError(RuntimeError):
    """Raised when a browser principal lacks account-administration rights."""


class SelfAdminMutationError(RuntimeError):
    """Raised when an administrator attempts a prohibited self-mutation."""


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Authenticated shared-session identity used for rate-limit ownership."""

    session_id: str
    source: str
    user_id: str | None = None
    username: str | None = None
    role: UserRole | None = None
    password_change_required: bool = False
    credential_version: int | None = None
    device_id: str | None = None
    expires_at: int | None = None


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
    """Runtime-only secret boundary. Credentials never enter Pydantic snapshots."""

    def __init__(
        self,
        *,
        profile: str,
        config: SecurityConfig,
        environ: dict[str, str] | None = None,
        observation_recorder: ObservationRecorder | None = None,
        redis_url: str | None = None,
        session_store: AuthSessionStore | None = None,
        user_store: AuthUserStore | None = None,
        display_store: AuthDisplayStore | None = None,
    ) -> None:
        self.profile = profile
        self.config = config
        self.enabled = profile == "production"
        runtime_environment = environ if environ is not None else os.environ
        self._limiter = TokenBucketLimiter()
        self._socket_principals: dict[str, AuthPrincipal] = {}
        self._observation_recorder = observation_recorder or NoOpObservationRecorder()
        token = runtime_environment.get(config.access_token_env, "")
        account_username = runtime_environment.get(config.account_username_env, "")
        account_password_hash = runtime_environment.get(config.account_password_hash_env, "")
        if self.enabled and len(token.encode("utf-8")) < 32:
            raise SecurityConfigurationError(
                f"{config.access_token_env} must contain at least 32 bytes in production"
            )
        if self.enabled and not 1 <= len(account_username.encode("utf-8")) <= 128:
            raise SecurityConfigurationError(
                f"{config.account_username_env} must contain between 1 and 128 bytes in production"
            )
        try:
            parse_password_hash(account_password_hash)
        except ValueError as exc:
            if self.enabled:
                raise SecurityConfigurationError(
                    f"{config.account_password_hash_env} must contain a valid {PASSWORD_HASH_SCHEME} hash in production"
                ) from exc
        self._token = token.encode("utf-8")
        self._session_store = session_store or RedisAuthSessionStore(
            redis_url or runtime_environment.get("ANIMETTA_REDIS_URL"),
            ttl_seconds=config.session_hours * 3600,
        )
        self._user_store = user_store or AuthUserStore(
            get_data_dir() / "auth.db",
            bootstrap_username=account_username,
            bootstrap_password_hash=account_password_hash,
        )
        display = config.display
        self._display_store = display_store or RedisAuthDisplayStore(
            redis_url or runtime_environment.get("ANIMETTA_REDIS_URL"),
            pairing_ttl_seconds=display.pairing_ttl_seconds,
            credential_ttl_seconds=display.credential_days * 86400,
            poll_interval_seconds=display.poll_interval_seconds,
            max_active_credentials=display.max_active_credentials,
        )

    @classmethod
    def from_effective_config(
        cls,
        config: EffectiveConfig | None,
        *,
        observation_recorder: ObservationRecorder | None = None,
        redis_url: str | None = None,
    ) -> SecurityRuntime:
        if config is None:
            return cls(
                profile="test",
                config=SecurityConfig(allowed_origins=("http://127.0.0.1:8000",)),
                observation_recorder=observation_recorder,
                redis_url=redis_url,
            )
        return cls(
            profile=config.profile,
            config=config.security,
            observation_recorder=observation_recorder,
            redis_url=redis_url,
        )

    @property
    def session_health(self) -> AuthSessionHealth:
        if not self.enabled:
            return AuthSessionHealth(True, None)
        return self._session_store.health

    @property
    def user_health(self) -> AuthUserHealth:
        if not self.enabled:
            return AuthUserHealth(True, None)
        return self._user_store.health

    @property
    def display_health(self) -> AuthDisplayHealth:
        if not self.enabled or not self.config.display.enabled:
            return AuthDisplayHealth(True, None)
        return self._display_store.health

    async def start(self) -> tuple[AuthSessionHealth, AuthUserHealth, AuthDisplayHealth]:
        if not self.enabled:
            return self.session_health, self.user_health, self.display_health
        if not self.config.display.enabled:
            session_health, user_health = await asyncio.gather(
                self._session_store.start(),
                self._user_store.start(),
            )
            return session_health, user_health, self.display_health
        session_health, user_health, display_health = await asyncio.gather(
            self._session_store.start(),
            self._user_store.start(),
            self._display_store.start(),
        )
        return session_health, user_health, display_health

    async def check_session_health(self) -> AuthSessionHealth:
        if not self.enabled:
            return self.session_health
        return await self._session_store.check_health()

    async def check_user_health(self) -> AuthUserHealth:
        if not self.enabled:
            return self.user_health
        return await self._user_store.check_health()

    async def check_display_health(self) -> AuthDisplayHealth:
        if not self.enabled or not self.config.display.enabled:
            return self.display_health
        return await self._display_store.check_health()

    async def close(self) -> None:
        if self.enabled:
            await asyncio.gather(
                self._session_store.close(),
                self._user_store.close(),
                self._display_store.close(),
            )

    async def record_error(self, code: str, *, surface: str) -> None:
        """Persist a content-free security failure without weakening request handling."""
        await self._record_security_observation(code, surface=surface, failed=True)

    async def record_event(self, action: str, *, surface: str) -> None:
        """Persist a content-free successful security event."""
        await self._record_security_observation(action, surface=surface, failed=False)

    async def _record_security_observation(
        self,
        action: str,
        *,
        surface: str,
        failed: bool,
    ) -> None:
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
                    status=OperationStatus.ERROR if failed else OperationStatus.SUCCESS,
                    finished_at=time.time(),
                    error_type=action if failed else None,
                    error_summary=action if failed else None,
                )
            )
            await recorder.finish_trace(
                trace_id,
                TraceOutcome.FAILED if failed else TraceOutcome.SUCCESS,
                finished_at=time.time(),
                error_type=action if failed else None,
                error_summary=action if failed else None,
                attributes={
                    "source": surface,
                    **({} if failed else {"action": action}),
                },
            )
        except Exception:
            return

    def check_login_limit(self, ip: str) -> None:
        if self.enabled:
            self._limiter.consume("login", ip, rate=5, period_seconds=300, burst=5)

    def check_password_limit(self, user_id: str) -> None:
        if self.enabled:
            self._limiter.consume("password", user_id, rate=5, period_seconds=900, burst=5)

    def check_pairing_create_limit(self, owner: str) -> None:
        if self.enabled:
            self._limiter.consume("display_pairing", owner, rate=3, period_seconds=300, burst=3)

    def check_pairing_approve_limit(self, session_id: str) -> None:
        if self.enabled:
            self._limiter.consume(
                "display_approve", session_id, rate=5, period_seconds=300, burst=5
            )

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

    def display_socket_ids(self, device_id: str) -> tuple[str, ...]:
        return tuple(
            sid
            for sid, principal in self._socket_principals.items()
            if principal.source == "display" and principal.device_id == device_id
        )

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

    async def verify_account_credentials(self, username: str, password: str) -> bool:
        if not self.enabled:
            return True
        return await self._user_store.authenticate(username, password) is not None

    async def login(
        self,
        username: str,
        password: str,
        *,
        now: int | None = None,
    ) -> tuple[str, int, UserAccount]:
        if not self.enabled:
            expires_at = (
                int(time.time()) if now is None else now
            ) + self.config.session_hours * 3600
            account = UserAccount(
                id="nonproduction",
                username=username or "nonproduction",
                password_hash="",
                role="admin",
                enabled=True,
                must_change_password=False,
                credential_version=1,
                created_at=0,
                updated_at=0,
                last_login_at=None,
                created_by=None,
            )
            return secrets.token_urlsafe(32), expires_at, account
        account = await self._user_store.authenticate(username, password)
        if account is None:
            raise CurrentPasswordInvalidError("UNAUTHORIZED")
        if not account.enabled:
            raise AccountDisabledError("ACCOUNT_DISABLED")
        account = await self._user_store.record_login(account.id)
        token, session = await self._session_store.issue(
            user_id=account.id,
            credential_version=account.credential_version,
            now=now,
        )
        return token, session.expires_at, account

    async def issue_session(
        self,
        account: UserAccount,
        *,
        now: int | None = None,
    ) -> tuple[str, int]:
        issued_at = int(time.time()) if now is None else now
        expires_at = issued_at + self.config.session_hours * 3600
        if not self.enabled:
            return secrets.token_urlsafe(32), expires_at
        value, session = await self._session_store.issue(
            user_id=account.id,
            credential_version=account.credential_version,
            now=issued_at,
        )
        return value, session.expires_at

    async def verify_session(
        self,
        value: str,
        *,
        now: int | None = None,
    ) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(
                session_id="nonproduction",
                source="disabled",
                user_id="nonproduction",
                username="nonproduction",
                role="admin",
            )
        session = await self._session_store.verify(value, now=now)
        if session is None:
            return None
        account = await self._user_store.get_by_id(session.user_id)
        if account is None or account.credential_version != session.credential_version:
            return None
        if not account.enabled:
            raise AccountDisabledError("ACCOUNT_DISABLED")
        return self._principal_for_account(session.session_id, account)

    async def revoke_session(self, value: str) -> None:
        if self.enabled:
            await self._session_store.revoke(value)

    async def change_password(
        self,
        principal: AuthPrincipal,
        *,
        current_password: str,
        new_password: str,
        now: int | None = None,
    ) -> tuple[str, int, UserAccount]:
        account = await self._browser_account(principal)
        self.check_password_limit(account.id)
        if not verify_password(current_password, account.password_hash):
            raise CurrentPasswordInvalidError("CURRENT_PASSWORD_INVALID")
        validate_password(new_password)
        if verify_password(new_password, account.password_hash):
            raise SamePasswordError("PASSWORD_UNCHANGED")
        account = await self._user_store.update_password(
            account.id,
            password_hash=hash_password(new_password),
            must_change_password=False,
            actor_user_id=account.id,
            action="password_changed",
        )
        await self._session_store.revoke_user(account.id)
        token, expires_at = await self.issue_session(account, now=now)
        return token, expires_at, account

    async def list_users(self, principal: AuthPrincipal) -> list[dict[str, object]]:
        await self._require_admin(principal)
        users = await self._user_store.list_users()
        counts = await self._session_store.count_user_sessions(
            {user.id: user.credential_version for user in users}
        )
        return [user.public_dict(active_sessions=counts[user.id]) for user in users]

    async def create_user(
        self,
        principal: AuthPrincipal,
        *,
        username: str,
        role: UserRole,
        temporary_password: str,
    ) -> UserAccount:
        actor = await self._require_admin(principal)
        validate_password(temporary_password)
        return await self._user_store.create_user(
            username=username,
            password_hash=hash_password(temporary_password),
            role=role,
            actor_user_id=actor.id,
        )

    async def update_user_access(
        self,
        principal: AuthPrincipal,
        user_id: str,
        *,
        role: UserRole | None,
        enabled: bool | None,
    ) -> UserAccount:
        actor = await self._require_admin(principal)
        if actor.id == user_id and (role is not None or enabled is not None):
            raise SelfAdminMutationError("SELF_ADMIN_MUTATION_FORBIDDEN")
        account, changed = await self._user_store.update_access(
            user_id,
            role=role,
            enabled=enabled,
            actor_user_id=actor.id,
        )
        if changed:
            await self._session_store.revoke_user(account.id)
        return account

    async def reset_user_password(
        self,
        principal: AuthPrincipal,
        user_id: str,
        *,
        temporary_password: str,
    ) -> UserAccount:
        actor = await self._require_admin(principal)
        if actor.id == user_id:
            raise SelfAdminMutationError("SELF_ADMIN_MUTATION_FORBIDDEN")
        validate_password(temporary_password)
        account = await self._user_store.update_password(
            user_id,
            password_hash=hash_password(temporary_password),
            must_change_password=True,
            actor_user_id=actor.id,
            action="password_reset",
        )
        await self._session_store.revoke_user(account.id)
        return account

    async def revoke_user_sessions(self, principal: AuthPrincipal, user_id: str) -> None:
        actor = await self._require_admin(principal)
        if await self._user_store.get_by_id(user_id) is None:
            raise UserNotFoundError("USER_NOT_FOUND")
        await self._session_store.revoke_user(user_id)
        await self._user_store.record_event(
            actor_user_id=actor.id,
            target_user_id=user_id,
            action="sessions_revoked",
        )

    async def create_display_pairing(
        self,
        *,
        origin: str,
        now: int | None = None,
    ) -> PendingPairing:
        self.require_display_origin(origin)
        return await self._display_store.create_pairing(origin=origin, now=now)

    async def approve_display_pairing(
        self,
        principal: AuthPrincipal,
        *,
        code: str,
        name: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        actor = await self._require_admin(principal)
        self.check_pairing_approve_limit(principal.session_id)
        return await self._display_store.approve_pairing(
            code,
            name=name,
            approved_by_user_id=actor.id,
            now=now,
        )

    async def exchange_display_pairing(
        self,
        token: str,
        *,
        origin: str,
        now: int | None = None,
    ) -> tuple[str, DisplayCredential] | None:
        self.require_display_origin(origin)
        return await self._display_store.exchange_pairing(token, origin=origin, now=now)

    async def list_display_credentials(
        self,
        principal: AuthPrincipal,
        *,
        now: int | None = None,
    ) -> list[DisplayCredential]:
        await self._require_admin(principal)
        return await self._display_store.list_credentials(now=now)

    async def revoke_display_credential(
        self,
        principal: AuthPrincipal,
        device_id: str,
    ) -> bool:
        await self._require_admin(principal)
        return await self._display_store.revoke_credential(device_id)

    async def verify_display_credential(
        self,
        token: str,
        *,
        origin: str,
        touch: bool = False,
        now: int | None = None,
    ) -> AuthPrincipal | None:
        self.require_display_origin(origin)
        credential = await self._display_store.verify_credential(
            token,
            origin=origin,
            now=now,
            touch=touch,
        )
        if credential is None:
            return None
        return AuthPrincipal(
            session_id=credential.session_id,
            source="display",
            device_id=credential.id,
            expires_at=credential.expires_at,
        )

    async def authenticate_live_http(self, request: Request) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(session_id="nonproduction", source="disabled", role="admin")
        user_cookie = request.cookies.get(SESSION_COOKIE)
        if user_cookie:
            principal = await self.verify_session(user_cookie)
            if principal is not None:
                return principal
        display_cookie = request.cookies.get(DISPLAY_COOKIE)
        if not display_cookie or not self.config.display.enabled:
            return None
        return await self.verify_display_credential(
            display_cookie,
            origin=request_origin(request),
        )

    def require_display_origin(self, origin: str) -> None:
        if (
            not self.config.display.enabled
            or origin.rstrip("/") not in self.config.display.allowed_origins
        ):
            raise ValueError("ORIGIN_NOT_ALLOWED")

    async def _browser_account(self, principal: AuthPrincipal) -> UserAccount:
        if principal.source != "cookie" or principal.user_id is None:
            raise AccountAdminRequiredError("ACCOUNT_ADMIN_REQUIRED")
        account = await self._user_store.get_by_id(principal.user_id)
        if account is None:
            raise UserNotFoundError("USER_NOT_FOUND")
        if not account.enabled:
            raise AccountDisabledError("ACCOUNT_DISABLED")
        return account

    async def _require_admin(self, principal: AuthPrincipal) -> UserAccount:
        account = await self._browser_account(principal)
        if account.must_change_password:
            raise PasswordChangeRequiredError("PASSWORD_CHANGE_REQUIRED")
        if account.role != "admin":
            raise AccountAdminRequiredError("ACCOUNT_ADMIN_REQUIRED")
        return account

    @staticmethod
    def _principal_for_account(session_id: str, account: UserAccount) -> AuthPrincipal:
        return AuthPrincipal(
            session_id=session_id,
            source="cookie",
            user_id=account.id,
            username=account.username,
            role=account.role,
            password_change_required=account.must_change_password,
            credential_version=account.credential_version,
        )

    async def authenticate_http(self, request: Request) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(session_id="nonproduction", source="disabled", role="admin")
        bearer = _bearer_token(request.headers)
        if bearer is not None and self.verify_shared_token(bearer):
            return AuthPrincipal(session_id="shared-token", source="bearer")
        cookie = request.cookies.get(SESSION_COOKIE)
        return await self.verify_session(cookie) if cookie else None

    async def authenticate_socket(
        self,
        environ: dict[str, Any],
        auth: dict[str, Any] | None,
    ) -> AuthPrincipal | None:
        if not self.enabled:
            return AuthPrincipal(session_id="nonproduction", source="disabled", role="admin")
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
        if morsel:
            principal = await self.verify_session(morsel.value)
            if principal is not None:
                return principal
        display = cookies.get(DISPLAY_COOKIE)
        if display is None or not self.config.display.enabled:
            return None
        return await self.verify_display_credential(
            display.value,
            origin=headers.get("origin", "").rstrip("/"),
            touch=True,
        )


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Protect sensitive HTTP routes while leaving liveness and login public."""

    def __init__(self, app: Any, *, security: SecurityRuntime) -> None:
        super().__init__(app)
        self._security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._security.enabled or not _requires_authentication(request.url.path):
            return await call_next(request)
        try:
            principal = await self._security.authenticate_http(request)
        except AuthSessionStoreUnavailableError:
            return await _session_store_unavailable_response(self._security, "http")
        except AuthUserStoreUnavailableError:
            return await _user_store_unavailable_response(self._security, "http")
        except AccountDisabledError:
            return error_response("ACCOUNT_DISABLED", "Account disabled", status_code=403)
        if principal is None:
            await self._security.record_error("UNAUTHORIZED", surface="http")
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        if principal.password_change_required:
            return error_response(
                "PASSWORD_CHANGE_REQUIRED",
                "Password change required",
                status_code=403,
            )
        request.state.auth_principal = principal
        return await call_next(request)


def get_auth_routes(
    security: SecurityRuntime,
    *,
    disconnect_display: Any | None = None,
) -> list[Any]:
    """Build browser auth routes while preserving the historical import path."""
    from .auth_routes import get_auth_routes as build_auth_routes

    return build_auth_routes(security, disconnect_display=disconnect_display)


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


async def _session_store_unavailable_response(
    security: SecurityRuntime,
    surface: str,
) -> JSONResponse:
    await security.record_error("AUTH_SESSION_STORE_UNAVAILABLE", surface=surface)
    return error_response(
        "AUTH_SESSION_STORE_UNAVAILABLE",
        "Authentication session store unavailable",
        status_code=503,
    )


async def _user_store_unavailable_response(
    security: SecurityRuntime,
    surface: str,
) -> JSONResponse:
    await security.record_error("AUTH_USER_STORE_UNAVAILABLE", surface=surface)
    return error_response(
        "AUTH_USER_STORE_UNAVAILABLE",
        "Authentication user store unavailable",
        status_code=503,
    )


def _requires_authentication(path: str) -> bool:
    if path == "/health" or path.startswith("/api/auth/"):
        return False
    return path in {"/ready", "/metrics"} or path.startswith("/api/")


def _bearer_token(headers: Headers) -> str | None:
    authorization = headers.get("authorization", "")
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value:
        return value
    return None


def request_origin(request: Request) -> str:
    """Return the browser origin even when a credentialed GET omits Origin."""
    supplied = request.headers.get("origin")
    if supplied:
        return supplied.rstrip("/")
    host = request.headers.get("host") or request.url.netloc
    return f"{request.url.scheme}://{host}".rstrip("/")
