"""Capture fail-closed evidence for the July golden-path baseline."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

HttpGet = Callable[[str, float], tuple[int, str, bytes]]
PreflightRunner = Callable[[Path, Path], dict[str, Any]]

_SECRET = re.compile(
    r"(?:Bearer\s+|sk-)[A-Za-z0-9._-]+|"
    r"(?i:(?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"
)


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))
    except (TypeError, ValueError):
        return "<redacted-url>"


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if any(part in str(key).lower() for part in ("key", "token", "secret", "password"))
                else _sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _SECRET.sub("<redacted>", value)
    return value


def _default_preflight(config_path: Path, project_root: Path) -> dict[str, Any]:
    from animetta.config.manifest import load_effective_config

    del project_root
    config = load_effective_config(config_path)
    public = config.to_public_dict()
    return {
        "ok": all(item["ready"] for item in public["providers"].values()),
        "profile": config.profile,
        "version": config.version,
        "effective_hash": config.effective_hash,
        "semantic_hash": config.semantic_hash,
        "providers": public["providers"],
    }


def _default_http_get(url: str, timeout: float) -> tuple[int, str, bytes]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return (
                int(response.status),
                response.headers.get_content_type(),
                response.read(),
            )
    except HTTPError as exc:
        return int(exc.code), exc.headers.get_content_type(), exc.read()


def _http_check(
    url: str,
    timeout: float,
    http_get: HttpGet,
    *,
    readiness: bool,
) -> dict[str, Any]:
    try:
        status, content_type, body = http_get(url, timeout)
    except Exception as exc:
        return {
            "ok": False,
            "code": "request_exception",
            "error_type": type(exc).__name__,
            "detail": str(exc),
        }
    if "json" not in content_type.lower():
        return {"ok": False, "code": "non_json_response", "status_code": status}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "code": "malformed_json", "status_code": status}
    if not isinstance(payload, dict):
        return {"ok": False, "code": "invalid_json_shape", "status_code": status}
    expected = payload.get("ready") is True if readiness else payload.get("status") == "ok"
    ok = status == 200 and expected
    return {
        "ok": ok,
        "code": "ok" if ok else "invariant_failed",
        "status_code": status,
        "payload": payload,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_baseline(
    *,
    config_path: Path,
    project_root: Path,
    base_url: str,
    output_dir: Path,
    timeout: float = 5.0,
    static_only: bool = False,
    preflight_runner: PreflightRunner = _default_preflight,
    http_get: HttpGet = _default_http_get,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[int, Path, dict[str, Any]]:
    """Run all requested probes and atomically persist sanitized evidence."""
    recorded_at = now().astimezone(UTC)
    filename = f"golden-baseline-{recorded_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path = output_dir / filename
    try:
        preflight = preflight_runner(config_path, project_root)
        preflight_check = {
            "ok": preflight.get("ok") is True,
            "code": "ok" if preflight.get("ok") is True else "preflight_failed",
            "payload": preflight,
        }
    except Exception as exc:
        preflight_check = {
            "ok": False,
            "code": "preflight_exception",
            "error_type": type(exc).__name__,
            "detail": str(exc),
        }

    checks: dict[str, Any] = {"preflight": preflight_check}
    if not static_only:
        root = base_url.rstrip("/")
        checks["liveness"] = _http_check(
            f"{root}/health", timeout, http_get, readiness=False
        )
        checks["readiness"] = _http_check(
            f"{root}/ready", timeout, http_get, readiness=True
        )
    report = _sanitize(
        {
            "schema_version": 1,
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "profile": preflight_check.get("payload", {}).get("profile", "unknown"),
            "config": str(config_path),
            "base_url": _safe_url(base_url),
            "mode": "static" if static_only else "runtime",
            "checks": checks,
            "ok": all(check.get("ok") is True for check in checks.values()),
        }
    )
    _write_atomic(evidence_path, report)
    return (0 if report["ok"] else 1), evidence_path, report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/animetta.yaml"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--output-dir", type=Path, default=Path("data/baseline"))
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--static-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    exit_code, path, report = run_baseline(
        config_path=args.config,
        project_root=args.project_root,
        base_url=args.base_url,
        output_dir=args.output_dir,
        timeout=args.timeout,
        static_only=args.static_only,
    )
    print(json.dumps({"ok": report["ok"], "evidence": str(path)}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
