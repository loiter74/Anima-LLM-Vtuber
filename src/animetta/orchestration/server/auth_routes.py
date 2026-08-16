"""Starlette routes for browser login and account administration."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth_session import AuthSessionStoreUnavailableError
from .auth_user import (
    AuthUserStoreUnavailableError,
    LastActiveAdminError,
    UsernameConflictError,
    UserNotFoundError,
)
from .security import (
    SESSION_COOKIE,
    AccountAdminRequiredError,
    AccountDisabledError,
    AuthPrincipal,
    CurrentPasswordInvalidError,
    PasswordChangeRequiredError,
    RateLimitError,
    SamePasswordError,
    SecurityRuntime,
    SelfAdminMutationError,
    _session_store_unavailable_response,
    _user_store_unavailable_response,
    error_response,
)


def get_auth_routes(security: SecurityRuntime) -> list[Route]:
    """Build browser auth and administrator routes without exposing secrets."""

    async def login(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
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
        data = await _json_object(request)
        username = str(data.get("username") or "")
        password = str(data.get("password") or "")
        try:
            token, expires_at, account = await security.login(username, password)
        except CurrentPasswordInvalidError:
            await security.record_error("UNAUTHORIZED", surface="login")
            return error_response("UNAUTHORIZED", "Invalid credentials", status_code=401)
        except AccountDisabledError:
            return error_response("ACCOUNT_DISABLED", "Account disabled", status_code=403)
        except AuthUserStoreUnavailableError:
            return await _user_store_unavailable_response(security, "login")
        except AuthSessionStoreUnavailableError:
            return await _session_store_unavailable_response(security, "login")
        response = JSONResponse(
            {
                "ok": True,
                "expires_at": expires_at,
                "user": _principal_user(account.id, account.username, account.role),
                "password_change_required": account.must_change_password,
            }
        )
        _set_session_cookie(response, request, security, token)
        return response

    async def session(request: Request) -> JSONResponse:
        principal = await _authenticate(request, security, surface="session")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            await security.record_error("UNAUTHORIZED", surface="session")
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        return JSONResponse(
            {
                "ok": True,
                "authenticated": True,
                "source": principal.source,
                "user": _principal_user(principal.user_id, principal.username, principal.role),
                "password_change_required": principal.password_change_required,
            }
        )

    async def logout(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        cookie = request.cookies.get(SESSION_COOKIE)
        try:
            if cookie:
                await security.revoke_session(cookie)
            response = JSONResponse({"ok": True})
        except AuthSessionStoreUnavailableError:
            response = await _session_store_unavailable_response(security, "logout")
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
        return response

    async def change_password(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        principal = await _authenticate(request, security, surface="password")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        data = await _json_object(request)
        current_password = str(data.get("current_password") or "")
        new_password = str(data.get("new_password") or "")
        try:
            token, expires_at, account = await security.change_password(
                principal,
                current_password=current_password,
                new_password=new_password,
            )
        except RateLimitError as exc:
            return error_response(
                "RATE_LIMITED",
                "Too many password attempts",
                status_code=429,
                retry_after=exc.retry_after,
            )
        except CurrentPasswordInvalidError:
            return error_response(
                "CURRENT_PASSWORD_INVALID",
                "Current password is invalid",
                status_code=401,
            )
        except (ValueError, SamePasswordError):
            return error_response(
                "PASSWORD_POLICY_VIOLATION",
                "New password does not satisfy policy",
                status_code=422,
            )
        except AuthUserStoreUnavailableError:
            return await _user_store_unavailable_response(security, "password")
        except AuthSessionStoreUnavailableError:
            response = await _session_store_unavailable_response(security, "password")
            response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
            return response
        except (AccountAdminRequiredError, UserNotFoundError):
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        response = JSONResponse(
            {
                "ok": True,
                "expires_at": expires_at,
                "user": _principal_user(account.id, account.username, account.role),
                "password_change_required": False,
            }
        )
        _set_session_cookie(response, request, security, token)
        return response

    async def list_users(request: Request) -> JSONResponse:
        principal = await _authenticate(request, security, surface="users_list")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        try:
            users = await security.list_users(principal)
        except Exception as exc:
            return await _admin_error(security, exc, "users_list")
        return JSONResponse({"ok": True, "users": users})

    async def create_user(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        principal = await _authenticate(request, security, surface="users_create")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        data = await _json_object(request)
        role = data.get("role")
        if role not in {"admin", "user"}:
            return error_response("INVALID_REQUEST", "Invalid role", status_code=422)
        try:
            account = await security.create_user(
                principal,
                username=str(data.get("username") or ""),
                role=role,
                temporary_password=str(data.get("temporary_password") or ""),
            )
        except Exception as exc:
            return await _admin_error(security, exc, "users_create")
        return JSONResponse(
            {"ok": True, "user": account.public_dict(active_sessions=0)}, status_code=201
        )

    async def update_user(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        principal = await _authenticate(request, security, surface="users_update")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        data = await _json_object(request)
        if not data or set(data) - {"role", "enabled"}:
            return error_response("INVALID_REQUEST", "Invalid account update", status_code=422)
        role = data.get("role")
        enabled = data.get("enabled")
        if role is not None and role not in {"admin", "user"}:
            return error_response("INVALID_REQUEST", "Invalid role", status_code=422)
        if enabled is not None and not isinstance(enabled, bool):
            return error_response("INVALID_REQUEST", "Invalid enabled state", status_code=422)
        try:
            account = await security.update_user_access(
                principal,
                str(request.path_params["user_id"]),
                role=role,
                enabled=enabled,
            )
        except Exception as exc:
            return await _admin_error(security, exc, "users_update")
        return JSONResponse({"ok": True, "user": account.public_dict(active_sessions=0)})

    async def reset_password(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        principal = await _authenticate(request, security, surface="users_reset_password")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        data = await _json_object(request)
        try:
            account = await security.reset_user_password(
                principal,
                str(request.path_params["user_id"]),
                temporary_password=str(data.get("temporary_password") or ""),
            )
        except Exception as exc:
            return await _admin_error(security, exc, "users_reset_password")
        return JSONResponse({"ok": True, "user": account.public_dict(active_sessions=0)})

    async def revoke_sessions(request: Request) -> JSONResponse:
        if response := _origin_error(request, security):
            return response
        principal = await _authenticate(request, security, surface="users_revoke_sessions")
        if isinstance(principal, JSONResponse):
            return principal
        if principal is None:
            return error_response("UNAUTHORIZED", "Authentication required", status_code=401)
        try:
            await security.revoke_user_sessions(principal, str(request.path_params["user_id"]))
        except Exception as exc:
            return await _admin_error(security, exc, "users_revoke_sessions")
        response = JSONResponse({"ok": True})
        if principal.user_id == str(request.path_params["user_id"]):
            response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
        return response

    return [
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/session", session, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/auth/password", change_password, methods=["POST"]),
        Route("/api/auth/users", list_users, methods=["GET"]),
        Route("/api/auth/users", create_user, methods=["POST"]),
        Route("/api/auth/users/{user_id:str}", update_user, methods=["PATCH"]),
        Route(
            "/api/auth/users/{user_id:str}/reset-password",
            reset_password,
            methods=["POST"],
        ),
        Route(
            "/api/auth/users/{user_id:str}/revoke-sessions",
            revoke_sessions,
            methods=["POST"],
        ),
    ]


async def _authenticate(
    request: Request,
    security: SecurityRuntime,
    *,
    surface: str,
) -> AuthPrincipal | JSONResponse | None:
    try:
        return await security.authenticate_http(request)
    except AuthSessionStoreUnavailableError:
        return await _session_store_unavailable_response(security, surface)
    except AuthUserStoreUnavailableError:
        return await _user_store_unavailable_response(security, surface)
    except AccountDisabledError:
        return error_response("ACCOUNT_DISABLED", "Account disabled", status_code=403)


async def _admin_error(
    security: SecurityRuntime,
    exc: Exception,
    surface: str,
) -> JSONResponse:
    if isinstance(exc, AuthSessionStoreUnavailableError):
        return await _session_store_unavailable_response(security, surface)
    if isinstance(exc, AuthUserStoreUnavailableError):
        return await _user_store_unavailable_response(security, surface)
    if isinstance(exc, AccountAdminRequiredError):
        return error_response("ACCOUNT_ADMIN_REQUIRED", "Administrator required", status_code=403)
    if isinstance(exc, PasswordChangeRequiredError):
        return error_response(
            "PASSWORD_CHANGE_REQUIRED", "Password change required", status_code=403
        )
    if isinstance(exc, SelfAdminMutationError):
        return error_response(
            "SELF_ADMIN_MUTATION_FORBIDDEN",
            "Administrators cannot mutate their own access",
            status_code=409,
        )
    if isinstance(exc, LastActiveAdminError):
        return error_response(
            "LAST_ACTIVE_ADMIN",
            "The last active administrator must be preserved",
            status_code=409,
        )
    if isinstance(exc, UsernameConflictError):
        return error_response("USERNAME_CONFLICT", "Username already exists", status_code=409)
    if isinstance(exc, UserNotFoundError):
        return error_response("USER_NOT_FOUND", "User not found", status_code=404)
    if isinstance(exc, (ValueError, SamePasswordError)):
        return error_response(
            "PASSWORD_POLICY_VIOLATION",
            "Password or username does not satisfy policy",
            status_code=422,
        )
    raise exc


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _principal_user(
    user_id: str | None,
    username: str | None,
    role: str | None,
) -> dict[str, str] | None:
    if user_id is None or username is None or role not in {"admin", "user"}:
        return None
    return {"id": user_id, "username": username, "role": role}


def _set_session_cookie(
    response: JSONResponse,
    request: Request,
    security: SecurityRuntime,
    token: str,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=security.config.session_hours * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def _origin_error(request: Request, security: SecurityRuntime) -> JSONResponse | None:
    origin = request.headers.get("origin")
    if origin is None or not security.enabled:
        return None
    if origin.rstrip("/") in security.config.allowed_origins:
        return None
    return error_response("ORIGIN_NOT_ALLOWED", "Origin is not allowed", status_code=403)
