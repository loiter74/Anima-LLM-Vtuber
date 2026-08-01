#!/usr/bin/env python3
"""Read-only readiness preflight for the persistent local Qwen TTS service."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8766"
HOST_TTS_DEFAULT_BASE_URL = "http://127.0.0.1:8767"

# Identity of the host-local gguf Qwen TTS runtime (port 8767). This is the
# single source of truth for the local runtime; keep it in sync with
# HOST_TTS_IDENTITY in scripts/runtime_lifecycle.py. The /ready endpoint returns
# both ``revision`` and ``runtime_commit`` (same value); preflight validates the
# subset that is stable across restarts and shared with the remote-worker mode.
HOST_TTS_EXPECTED_IDENTITY: dict[str, str] = {
    "service": "qwen-tts",
    "api_version": "v1",
    "provider": "qwen3-tts-gguf-host",
    "model": "Qwen3-TTS-1.7B-Base",
    "revision": "0eb32e283ee46b86820c67843abb04cf12bc58d7",
    "voice": "tosaka-rin-cn",
}


class QwenPreflightError(RuntimeError):
    """Categorized, actionable persistent-worker readiness failure."""

    def __init__(self, category: str, message: str, remediation: str) -> None:
        self.category = category
        self.remediation = remediation
        super().__init__(f"{message}. Remediation: {remediation}")


def validate_ready_identity(
    payload: Mapping[str, Any],
    expected_identity: Mapping[str, str],
) -> Mapping[str, Any]:
    """Require exact ready identity while allowing informational response fields."""
    if payload.get("ready") is not True:
        raise QwenPreflightError(
            "not_ready",
            "Persistent Qwen TTS worker is not ready",
            "run `python scripts/runtime_lifecycle.py qwen-up` and wait for model preload",
        )
    mismatches = {
        field: {"expected": expected, "actual": payload.get(field)}
        for field, expected in expected_identity.items()
        if payload.get(field) != expected
    }
    if mismatches:
        fields = ", ".join(sorted(mismatches))
        raise QwenPreflightError(
            "identity_mismatch",
            f"Persistent Qwen TTS identity mismatch in: {fields}",
            "run `python scripts/runtime_lifecycle.py qwen-deploy` to apply the pinned worker identity",
        )
    return payload


def _request_json(url: str, authorization: str | None) -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if authorization:
        headers["authorization"] = authorization
    request = Request(url, headers=headers)  # noqa: S310 - local fixed service URL
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OSError(f"HTTP {exc.code}: {body[:240]}") from exc
    except (OSError, URLError) as exc:
        raise OSError(str(exc)) from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OSError("Qwen TTS returned non-JSON readiness data") from exc
    if not isinstance(payload, dict):
        raise OSError("Qwen TTS returned non-object readiness data")
    return payload


def run_preflight(
    *,
    base_url: str,
    api_key: str,
    expected_identity: Mapping[str, str],
    request_json: Callable[[str, str | None], dict[str, Any]] = _request_json,
    attempts: int = 1,
    interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """Collect fresh health and identity evidence without mutating Docker state."""
    if not api_key.strip():
        raise QwenPreflightError(
            "configuration",
            "QWEN_TTS_API_KEY is missing",
            "set QWEN_TTS_API_KEY in the deployment environment",
        )
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    endpoint = base_url.rstrip("/")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            health = request_json(f"{endpoint}/health", None)
            if not (
                health.get("status") == "ok"
                and health.get("service") == "qwen-tts"
                and health.get("api_version") == "v1"
            ):
                raise QwenPreflightError(
                    "unhealthy",
                    "Persistent Qwen TTS health response is invalid",
                    "run `python scripts/runtime_lifecycle.py qwen-up` and inspect the Qwen project logs",
                )
            identity = request_json(
                f"{endpoint}/ready",
                f"Bearer {api_key}",
            )
            validate_ready_identity(identity, expected_identity)
            return {
                "status": "passed",
                "base_url": endpoint,
                "health": health,
                "identity": identity,
            }
        except QwenPreflightError as exc:
            if exc.category == "identity_mismatch":
                raise
            last_error = exc
        except (OSError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < attempts and interval_seconds > 0:
            time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error is not None else ""
    raise QwenPreflightError(
        "unavailable",
        f"Persistent Qwen TTS is unavailable{detail}",
        "run `python scripts/runtime_lifecycle.py qwen-up`; if the image is missing, "
        "run the `qwen-build` operation first",
    )


def load_expected_settings(
    *,
    fallback_base_url: str = DEFAULT_BASE_URL,
    mode: str = "remote",
) -> tuple[str, dict[str, str]]:
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    # Host-tts mode: the local gguf runtime is the real TTS backend. Its identity
    # is fixed by the runtime build and authenticated by QWEN_TTS_API_KEY; it does
    # not declare a production remote worker in the manifest, so resolve the
    # identity directly without touching load_remote_tts_worker_config.
    if mode == "host-tts":
        api_key = os.environ.get("QWEN_TTS_API_KEY", "").strip()
        if not api_key:
            raise QwenPreflightError(
                "configuration",
                "QWEN_TTS_API_KEY is missing",
                "set QWEN_TTS_API_KEY in the deployment environment",
            )
        return api_key, dict(HOST_TTS_EXPECTED_IDENTITY)

    from animetta.config.manifest import load_remote_tts_worker_config
    from animetta.config.providers.tts.remote import RemoteTTSConfig

    configured_worker_url = os.environ.get("QWEN_TTS_URL")
    use_fallback = not configured_worker_url or not configured_worker_url.strip()
    if use_fallback:
        os.environ["QWEN_TTS_URL"] = fallback_base_url
    try:
        remote = load_remote_tts_worker_config()
    finally:
        if use_fallback:
            if configured_worker_url is None:
                os.environ.pop("QWEN_TTS_URL", None)
            else:
                os.environ["QWEN_TTS_URL"] = configured_worker_url
    if not isinstance(remote, RemoteTTSConfig) or remote.worker is None:
        raise QwenPreflightError(
            "configuration",
            "Production TTS does not declare a remote Qwen worker",
            "restore the production qwen-alice worker declaration",
        )
    return (
        remote.api_key or "",
        {
            "service": "qwen-tts",
            "api_version": "v1",
            "provider": remote.provider,
            "model": remote.model,
            "revision": remote.worker.revision,
            "voice": remote.voice,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("remote", "host-tts"),
        default=os.environ.get("QWEN_TTS_MODE", "remote"),
        help="remote: persistent Docker Qwen worker (manifest identity); "
        "host-tts: local gguf-host runtime (port 8767, QWEN_TTS_API_KEY auth)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "QWEN_TTS_HOST_URL",
            HOST_TTS_DEFAULT_BASE_URL,  # set below based on mode if unset
        ),
    )
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--attempts", type=int)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    # When --base-url is left at the env-derived default and the operator did not
    # pin QWEN_TTS_HOST_URL, select the mode-appropriate default so host-tts mode
    # probes 8767 without requiring an explicit flag.
    if not os.environ.get("QWEN_TTS_HOST_URL") and "--base-url" not in (argv or ()):
        args.base_url = HOST_TTS_DEFAULT_BASE_URL if args.mode == "host-tts" else DEFAULT_BASE_URL
    try:
        api_key, expected_identity = load_expected_settings(
            fallback_base_url=args.base_url,
            mode=args.mode,
        )
        evidence = run_preflight(
            base_url=args.base_url,
            api_key=api_key,
            expected_identity=expected_identity,
            attempts=args.attempts or (120 if args.wait else 1),
            interval_seconds=args.interval_seconds if args.wait else 0.0,
        )
    except (OSError, ValueError, QwenPreflightError) as exc:
        payload = {
            "status": "failed",
            "category": getattr(exc, "category", "configuration"),
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
