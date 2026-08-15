"""Deterministic CLI for Animetta's backend-owned Bilibili session."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tooling.bilibili_mcp.controller import BilibiliController  # noqa: E402

DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config" / "bilibili.yaml"
DEFAULT_BASE_URL = "http://127.0.0.1"
ROOM_ID_LINE = re.compile(r"^\s*room_id:\s*(\d+)\s*(?:#.*)?$")


class Controller(Protocol):
    async def get_status(self) -> dict[str, Any]: ...

    async def connect_room(self, room_id: int, timeout_seconds: float) -> dict[str, Any]: ...

    async def switch_room(self, room_id: int, timeout_seconds: float) -> dict[str, Any]: ...

    async def disconnect_room(self, timeout_seconds: float) -> dict[str, Any]: ...

    async def close(self) -> None: ...


ControllerFactory = Callable[[str], Controller]
ReadinessProbe = Callable[[str, float], bool]


def local_override_path(config_path: Path) -> Path:
    """Gitignored per-host override stored next to the tracked template."""
    return config_path.with_name(f"{config_path.stem}.local{config_path.suffix}")


def _first_room_id(config_path: Path) -> int:
    with config_path.open(encoding="utf-8") as config:
        for line in config:
            match = ROOM_ID_LINE.fullmatch(line.rstrip("\r\n"))
            if match:
                return int(match.group(1))
    return 0


def load_default_room(config_path: Path = DEFAULT_CONFIG_PATH) -> int:
    """Prefer the gitignored local override, then the tracked template.

    Stop reading either file as soon as the public room identifier is found.
    """
    room_id = 0
    with suppress(OSError):
        room_id = _first_room_id(local_override_path(config_path))
    if room_id <= 0:
        try:
            room_id = _first_room_id(config_path)
        except OSError as exc:
            raise ValueError("无法读取 Bilibili 默认房间配置") from exc
    if room_id <= 0:
        raise ValueError(
            "config/bilibili.local.yaml 或 config/bilibili.yaml 的 room_id 必须是正整数"
        )
    return room_id


def probe_readiness(base_url: str, timeout_seconds: float = 3.0) -> bool:
    """Return whether the current formal runtime reports HTTP readiness."""
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/ready",
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return bool(
        isinstance(payload, Mapping)
        and (payload.get("ready") is True or payload.get("status") in {"ready", "ok"})
    )


def _normalized_result(raw: Mapping[str, Any], elapsed_ms: int) -> dict[str, Any]:
    status = raw.get("status")
    snapshot = status if isinstance(status, Mapping) else {}
    return {
        "ok": raw.get("ok") is True,
        "state": snapshot.get("state"),
        "room_id": snapshot.get("room_id"),
        "generation_id": snapshot.get("generation_id"),
        "elapsed_ms": elapsed_ms,
        "error_code": raw.get("error_code"),
        "message": str(raw.get("message") or ""),
    }


def _failure(error_code: str, message: str, started_at: float) -> dict[str, Any]:
    return {
        "ok": False,
        "state": None,
        "room_id": None,
        "generation_id": None,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        "error_code": error_code,
        "message": message,
    }


async def execute(
    args: argparse.Namespace,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    controller_factory: ControllerFactory = BilibiliController,
    readiness_probe: ReadinessProbe = probe_readiness,
) -> dict[str, Any]:
    """Execute one bounded action and return one credential-free result."""
    started_at = time.perf_counter()
    room_id = args.room_id
    if args.action in {"connect", "switch"} and room_id is None:
        try:
            room_id = load_default_room(config_path)
        except ValueError as exc:
            return _failure("invalid_default_room", str(exc), started_at)
    if args.action in {"connect", "switch"} and room_id is not None and room_id <= 0:
        return _failure("invalid_room_id", "room_id 必须是正整数", started_at)
    if not 0 < args.timeout_seconds <= 60:
        return _failure(
            "invalid_timeout",
            "timeout_seconds 必须大于 0 且不超过 60",
            started_at,
        )

    if args.action in {"connect", "switch"}:
        try:
            ready = await asyncio.to_thread(
                readiness_probe,
                args.base_url,
                args.readiness_timeout_seconds,
            )
        except Exception:
            ready = False
        if not ready:
            return _failure(
                "runtime_not_ready",
                "Animetta 正式运行时未就绪；请先使用 operate-anima-runtime",
                started_at,
            )

    controller: Controller | None = None
    try:
        controller = controller_factory(args.base_url)
        if args.action == "status":
            raw = await controller.get_status()
        elif args.action == "connect":
            assert room_id is not None
            raw = await controller.connect_room(room_id, args.timeout_seconds)
        elif args.action == "switch":
            assert room_id is not None
            raw = await controller.switch_room(room_id, args.timeout_seconds)
        else:
            raw = await controller.disconnect_room(args.timeout_seconds)
        return _normalized_result(
            raw,
            round((time.perf_counter() - started_at) * 1000),
        )
    except Exception:
        return _failure("control_failed", "Bilibili 直播控制失败", started_at)
    finally:
        if controller is not None:
            with suppress(Exception):
                await controller.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="控制 Animetta 的唯一 Bilibili 直播会话")
    parser.add_argument("action", choices=("status", "connect", "switch", "disconnect"))
    parser.add_argument("--room-id", type=int)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--readiness-timeout-seconds", type=float, default=3.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(execute(args))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
