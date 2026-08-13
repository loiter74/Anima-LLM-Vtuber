#!/usr/bin/env python3
"""Render deterministic synthetic danmaku and control Animetta program replays."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_BASE_URL = "http://127.0.0.1"
DEFAULT_CREATOR_ID = "codex-danmaku-simulator"
TERMINAL_STATES = {"completed", "stopped", "failed"}

ACTORS = (
    ("柚子茶不加冰", 91001),
    ("路过的小云朵", 91002),
    ("晚风收集员", 91003),
    ("猫爪信号灯", 91004),
    ("月亮便利店", 91005),
    ("今天也有元气", 91006),
    ("汽水半糖", 91007),
    ("星星来敲门", 91008),
)

TEXTS = {
    "greeting": ("晚上好，今天准备聊什么？", "来啦，今晚有什么安排？", "刚进直播间，先打个招呼！"),
    "follow_up": (
        "刚才那个观点能再展开一点吗？",
        "这件事你最看重哪一部分？",
        "如果只能选一个，你会怎么选？",
    ),
    "topic": (
        "最近有没有让你反复听的一首歌？",
        "今天发生过什么小确幸吗？",
        "想听你分享一个最近学到的新东西。",
    ),
    "quiet": ("我还在，慢慢想也没关系。", "安静陪一会儿也挺好。", "喝口水，我们不着急。"),
    "crowd": (
        "这个我有共鸣！",
        "展开讲讲！",
        "记下来了。",
        "好有画面感。",
        "确实是这样。",
        "哈哈哈太真实了。",
    ),
    "thanks": ("小小礼物，祝今晚顺利！", "支持一下，继续加油！", "送朵小花，慢慢播。"),
    "super_chat": (
        "想认真问问，你会怎么度过状态不好的那天？",
        "如果给刚入坑的人一句建议，你会说什么？",
        "今天最想留给大家的一句话是什么？",
    ),
}

SCENARIO_DESCRIPTIONS = {
    "daily": "日常聊天：入场、问候、追问、点赞、话题互动与关注",
    "quiet": "冷场恢复：稀疏消息与长间隔后的继续互动",
    "crowd": "短时高峰：连续弹幕、点赞与关注",
    "support": "混合支持：普通弹幕、礼物、醒目留言与后续追问",
}


def _event(
    offset_ms: int,
    event_type: str,
    actor: tuple[str, int],
    text: str = "",
    **payload: Any,
) -> dict[str, Any]:
    user_name, user_id = actor
    return {
        "offset_ms": offset_ms,
        "event_type": event_type,
        "actor_id": user_name,
        "text": text,
        "payload": {"user_id": user_id, **payload},
    }


def build_scenario(name: str, seed: int) -> list[dict[str, Any]]:
    if name not in SCENARIO_DESCRIPTIONS:
        raise ValueError(f"未知场景：{name}")
    rng = random.Random(seed)
    actors = list(ACTORS)
    rng.shuffle(actors)

    def choose(key: str) -> str:
        return rng.choice(TEXTS[key])

    if name == "daily":
        events = [
            _event(0, "enter", actors[0]),
            _event(1_500, "danmaku", actors[0], choose("greeting")),
            _event(7_000, "danmaku", actors[1], choose("follow_up")),
            _event(12_000, "like_batch", actors[2], count=18),
            _event(18_000, "danmaku", actors[2], choose("topic")),
            _event(27_000, "follow", actors[3]),
            _event(32_000, "danmaku", actors[3], choose("crowd")),
        ]
    elif name == "quiet":
        events = [
            _event(0, "enter", actors[0]),
            _event(2_000, "danmaku", actors[0], choose("greeting")),
            _event(22_000, "danmaku", actors[1], choose("quiet")),
            _event(48_000, "like_batch", actors[1], count=6),
            _event(65_000, "danmaku", actors[2], choose("topic")),
        ]
    elif name == "crowd":
        events = [
            _event(0, "enter", actors[0]),
            *[
                _event(600 + index * 450, "danmaku", actors[index % 6], text)
                for index, text in enumerate(rng.sample(TEXTS["crowd"], k=6))
            ],
            _event(3_600, "like_batch", actors[6], count=88),
            _event(4_200, "follow", actors[7]),
            _event(5_000, "danmaku", actors[7], choose("follow_up")),
        ]
    else:
        events = [
            _event(0, "enter", actors[0]),
            _event(1_000, "danmaku", actors[0], choose("greeting")),
            _event(7_000, "gift", actors[1], choose("thanks"), gift_name="小花花", gift_count=1),
            _event(13_000, "like_batch", actors[2], count=36),
            _event(
                20_000,
                "super_chat",
                actors[3],
                choose("super_chat"),
                price=30,
                currency="CNY",
            ),
            _event(30_000, "danmaku", actors[4], choose("follow_up")),
            _event(38_000, "follow", actors[4]),
        ]
    return events


def render_jsonl(name: str, seed: int) -> str:
    return (
        "\n".join(
            json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            for event in build_scenario(name, seed)
        )
        + "\n"
    )


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _url(base_url, path),
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(body)
        except json.JSONDecodeError:
            details = {"message": body or exc.reason}
        raise RuntimeError(
            f"Animetta API {exc.code}: {details.get('error') or details.get('message') or details}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 Animetta：{exc.reason}") from exc
    if not body:
        return {}
    result = json.loads(body)
    if not isinstance(result, dict):
        raise RuntimeError("Animetta API 返回了非对象 JSON")
    return result


def assert_ready(base_url: str) -> None:
    _request(base_url, "/ready", timeout=10)


def wait_for_terminal(
    base_url: str,
    replay_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        snapshot = _request(
            base_url,
            f"/api/program-replays/{urllib.parse.quote(replay_id, safe='')}",
        )
        if snapshot.get("state") in TERMINAL_STATES:
            return snapshot
        if time.monotonic() >= deadline:
            raise TimeoutError(f"等待重放完成超时：replay_id={replay_id}")
        time.sleep(poll_seconds)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Animetta 正式实例 URL")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成并重放可复现的合成直播弹幕。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出内置场景")

    render = subparsers.add_parser("render", help="生成场景 JSONL，不访问运行时")
    render.add_argument("scenario", choices=SCENARIO_DESCRIPTIONS)
    render.add_argument("--seed", type=int, default=20260813)
    render.add_argument("--output", type=Path, help="写入明确指定的文件；默认输出到 stdout")

    start = subparsers.add_parser("start", help="在当前 Animetta 实例启动重放")
    start.add_argument("scenario", choices=SCENARIO_DESCRIPTIONS)
    _add_connection_args(start)
    start.add_argument("--room-id", type=int, default=1)
    start.add_argument("--seed", type=int, default=20260813)
    start.add_argument("--speed", type=float, default=1.0)
    start.add_argument("--creator-id", default=DEFAULT_CREATOR_ID)
    start.add_argument("--task-id", default=None)
    start.add_argument("--wait", action="store_true")
    start.add_argument("--timeout-seconds", type=float, default=900)
    start.add_argument("--poll-seconds", type=float, default=1)

    status = subparsers.add_parser("status", help="读取重放状态")
    status.add_argument("replay_id")
    _add_connection_args(status)

    control = subparsers.add_parser("control", help="控制当前 Skill 创建的重放")
    control.add_argument("replay_id")
    control.add_argument("action", choices=("pause", "resume", "step", "speed", "restart", "stop"))
    _add_connection_args(control)
    control.add_argument("--creator-id", default=DEFAULT_CREATOR_ID)
    control.add_argument("--speed", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            _print(
                {
                    name: {
                        "description": description,
                        "events": len(build_scenario(name, 20260813)),
                    }
                    for name, description in SCENARIO_DESCRIPTIONS.items()
                }
            )
            return 0

        if args.command == "render":
            content = render_jsonl(args.scenario, args.seed)
            if args.output is None:
                print(content, end="")
            else:
                args.output.write_text(content, encoding="utf-8")
                _print(
                    {
                        "output": str(args.output.resolve()),
                        "scenario": args.scenario,
                        "seed": args.seed,
                    }
                )
            return 0

        if args.command == "start":
            if args.room_id <= 0:
                raise ValueError("room-id 必须为正整数")
            if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
                raise ValueError("等待与轮询时间必须为正数")
            assert_ready(args.base_url)
            payload = {
                "source": "jsonl",
                "jsonl": render_jsonl(args.scenario, args.seed),
                "room_id": args.room_id,
                "creator_id": args.creator_id,
                "speed": args.speed,
                "task_id": args.task_id or str(uuid4()),
            }
            snapshot = _request(
                args.base_url,
                "/api/program-replays/start",
                method="POST",
                payload=payload,
                timeout=30,
            )
            if args.wait:
                snapshot = wait_for_terminal(
                    args.base_url,
                    str(snapshot["replay_id"]),
                    timeout_seconds=args.timeout_seconds,
                    poll_seconds=args.poll_seconds,
                )
            _print(
                {
                    "base_url": args.base_url.rstrip("/"),
                    "scenario": args.scenario,
                    "seed": args.seed,
                    **snapshot,
                }
            )
            return 1 if snapshot.get("state") == "failed" else 0

        if args.command == "status":
            _print(
                _request(
                    args.base_url,
                    f"/api/program-replays/{urllib.parse.quote(args.replay_id, safe='')}",
                )
            )
            return 0

        if args.action == "speed" and args.speed is None:
            raise ValueError("speed 动作必须提供 --speed")
        if args.action != "speed" and args.speed is not None and args.action != "restart":
            raise ValueError("只有 speed 或 restart 动作可以提供 --speed")
        _print(
            _request(
                args.base_url,
                f"/api/program-replays/{urllib.parse.quote(args.replay_id, safe='')}/control",
                method="POST",
                payload={
                    "action": args.action,
                    "creator_id": args.creator_id,
                    "speed": args.speed,
                    "command_id": str(uuid4()),
                },
            )
        )
        return 0
    except (KeyError, OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
