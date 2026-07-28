"""Bounded live-room danmaku capture over the production gateway."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import TextIO

from loguru import logger

from animetta.services.bilibili.gateway import DanmakuGateway, create_danmaku_gateway
from animetta.services.bilibili.models import DanmakuMessage

_CSV_FIELDS = (
    "timestamp",
    "room_id",
    "user_id",
    "user_name",
    "text",
    "is_gift",
    "is_super_chat",
    "meta",
)


@dataclass(frozen=True, slots=True)
class LiveDanmakuOptions:
    """Validated command options for one live-room capture."""

    room_id: int
    output_dir: Path


class LiveDanmakuWriter:
    """Thread-safe CSV and JSONL sink for normalized danmaku messages."""

    def __init__(self, output_dir: Path, *, room_id: int, timestamp: str | None = None) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        captured_at = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        stem = f"live_danmaku_{room_id}_{captured_at}"
        self.paths = (output_dir / f"{stem}.csv", output_dir / f"{stem}.jsonl")
        self._room_id = room_id
        self._lock = threading.Lock()
        self._closed = False
        self._csv_stream: TextIO = self.paths[0].open("w", encoding="utf-8", newline="")
        self._jsonl_stream: TextIO = self.paths[1].open("w", encoding="utf-8", newline="\n")
        self._csv = csv.DictWriter(self._csv_stream, fieldnames=_CSV_FIELDS)
        self._csv.writeheader()

    def write(self, message: DanmakuMessage) -> None:
        """Append one normalized message to both output formats."""

        record = {
            "timestamp": message.timestamp,
            "room_id": self._room_id,
            "user_id": message.user_id,
            "user_name": message.user_name,
            "text": message.text,
            "is_gift": message.is_gift,
            "is_super_chat": message.is_super_chat,
            "meta": message.meta,
        }
        with self._lock:
            if self._closed:
                return
            self._csv.writerow({**record, "meta": json.dumps(message.meta, ensure_ascii=False)})
            self._jsonl_stream.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            self._csv_stream.flush()
            self._jsonl_stream.flush()

    def close(self) -> None:
        """Close both streams once."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._csv_stream.close()
            self._jsonl_stream.close()


class LiveDanmakuCollector:
    """Own gateway callbacks and guarantee gateway-before-writer shutdown."""

    def __init__(self, gateway: DanmakuGateway, writer: LiveDanmakuWriter) -> None:
        self._gateway = gateway
        self._writer = writer
        self._stop_event = threading.Event()
        self._started = False
        self._stopped = False

    def start(self) -> None:
        """Register callbacks and start the gateway once."""

        if self._started:
            return
        self._started = True
        self._gateway.set_message_callback(self._writer.write)
        self._gateway.set_status_callback(self._on_status)
        self._gateway.start()

    def request_stop(self) -> None:
        """Wake a running collector without touching gateway resources."""

        self._stop_event.set()

    def run_forever(self) -> None:
        """Run until interrupted, then release resources in a fixed order."""

        self.start()
        try:
            while not self._stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            self.request_stop()
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the gateway, then close output streams, exactly once."""

        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        try:
            if self._started:
                self._gateway.stop()
        finally:
            self._writer.close()

    @staticmethod
    def _on_status(connected: bool, _message: str) -> None:
        logger.info("Live danmaku gateway status changed: connected={}", connected)


def _positive_room_id(value: str) -> int:
    room_id = int(value)
    if room_id <= 0:
        raise argparse.ArgumentTypeError("room ID must be positive")
    return room_id


def parse_live_danmaku_options(argv: Sequence[str] | None = None) -> LiveDanmakuOptions:
    """Parse the bounded live collector CLI."""

    parser = argparse.ArgumentParser(description="Collect normalized Bilibili live danmaku")
    parser.add_argument("--room-id", required=True, type=_positive_room_id)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("scripts/danmaku_output"),
    )
    args = parser.parse_args(argv)
    return LiveDanmakuOptions(room_id=args.room_id, output_dir=args.output_dir)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
) -> int:
    """Run one live-room collector process."""

    options = parse_live_danmaku_options(argv)
    gateway = create_danmaku_gateway(
        room_id=options.room_id,
        sessdata=environ.get("BILIBILI_SESSDATA", ""),
    )
    writer = LiveDanmakuWriter(options.output_dir, room_id=options.room_id)
    collector = LiveDanmakuCollector(gateway, writer)

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        collector.request_stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)
    collector.run_forever()
    return 0
