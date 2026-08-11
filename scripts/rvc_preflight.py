#!/usr/bin/env python3
"""Read-only readiness preflight for the persistent local RVC service."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from animetta.host_rvc_contract import HOST_RVC_CONTRACT  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8769"
HOST_RVC_EXPECTED_IDENTITY = {
    "service": "rvc",
    "api_version": "v1",
    "separation_ready": True,
    "separation_model": HOST_RVC_CONTRACT.separation_model,
    **HOST_RVC_CONTRACT.identity(),
}


class RVCPreflightError(RuntimeError):
    def __init__(self, category: str, message: str, remediation: str) -> None:
        self.category = category
        self.remediation = remediation
        super().__init__(f"{message}. Remediation: {remediation}")


def validate_ready_identity(
    payload: Mapping[str, object],
    expected_identity: Mapping[str, object],
) -> Mapping[str, object]:
    if payload.get("ready") is not True:
        raise RVCPreflightError(
            "not_ready",
            "Host-local RVC is not ready",
            "run `py -3.13 scripts/runtime_lifecycle.py host-rvc-up` and inspect host-rvc.log",
        )
    mismatches = {
        field: {"expected": expected, "actual": payload.get(field)}
        for field, expected in expected_identity.items()
        if payload.get(field) != expected
    }
    if mismatches:
        raise RVCPreflightError(
            "identity_mismatch",
            "Host-local RVC identity mismatch in: " + ", ".join(sorted(mismatches)),
            "inspect config/host-rvc.yaml and restart with `host-rvc-stop` then `host-rvc-up`",
        )
    return payload


def _request_json(url: str, authorization: str | None) -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    request = Request(url, headers=headers)  # noqa: S310 - local fixed service URL
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        raise OSError(f"HTTP {exc.code}: {detail}") from exc
    except (OSError, URLError) as exc:
        raise OSError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise OSError("RVC returned non-object readiness data")
    return payload


def run_preflight(
    *,
    base_url: str,
    api_key: str,
    expected_identity: Mapping[str, object],
    request_json: Callable[[str, str | None], dict[str, object]] = _request_json,
    attempts: int = 1,
    interval_seconds: float = 0.0,
) -> dict[str, object]:
    if not api_key.strip():
        raise RVCPreflightError(
            "configuration",
            "Host-local RVC API key is missing",
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
                and health.get("service") == "rvc"
                and health.get("api_version") == "v1"
            ):
                raise RVCPreflightError(
                    "unhealthy",
                    "Host-local RVC health response is invalid",
                    "run `py -3.13 scripts/runtime_lifecycle.py host-rvc-up`",
                )
            identity = request_json(f"{endpoint}/ready", f"Bearer {api_key}")
            validate_ready_identity(identity, expected_identity)
            return {
                "status": "passed",
                "base_url": endpoint,
                "health": health,
                "identity": identity,
            }
        except RVCPreflightError as exc:
            if exc.category == "identity_mismatch":
                raise
            last_error = exc
        except (OSError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < attempts and interval_seconds > 0:
            time.sleep(interval_seconds)
    raise RVCPreflightError(
        "unavailable",
        f"Host-local RVC is unavailable: {last_error}",
        "run `py -3.13 scripts/runtime_lifecycle.py host-rvc-up` and inspect host-rvc.log",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("RVC_HOST_URL", DEFAULT_BASE_URL))
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    try:
        evidence = run_preflight(
            base_url=args.base_url,
            api_key=os.getenv("QWEN_TTS_API_KEY", ""),
            expected_identity=HOST_RVC_EXPECTED_IDENTITY,
            attempts=120 if args.wait else 1,
            interval_seconds=2.0 if args.wait else 0.0,
        )
    except (OSError, ValueError, RVCPreflightError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "category": getattr(exc, "category", "configuration"),
                    "error": str(exc),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(evidence, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
