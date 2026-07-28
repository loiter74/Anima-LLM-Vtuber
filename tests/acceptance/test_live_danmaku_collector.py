from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from animetta.acceptance.live_danmaku_collector import (
    LiveDanmakuCollector,
    LiveDanmakuWriter,
    parse_live_danmaku_options,
)
from animetta.services.bilibili.models import DanmakuMessage


class FakeGateway:
    room_id = 123

    def __init__(self) -> None:
        self.message_callback = None
        self.status_callback = None
        self.started = 0
        self.stopped = 0

    def set_message_callback(self, callback) -> None:
        self.message_callback = callback

    def set_status_callback(self, callback) -> None:
        self.status_callback = callback

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def test_live_writer_escapes_csv_and_keeps_jsonl_to_one_physical_line(tmp_path: Path) -> None:
    writer = LiveDanmakuWriter(tmp_path, room_id=123, timestamp="20260729T010203Z")
    message = DanmakuMessage(
        text='第一行,\n"第二行"',
        user_name='测试,"用户"',
        user_id=42,
        timestamp=1234.5,
        meta={"gift": "花\n束"},
    )

    writer.write(message)
    writer.close()
    writer.close()

    csv_path, jsonl_path = writer.paths
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["text"] == message.text
    assert rows[0]["user_name"] == message.user_name
    physical_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(physical_lines) == 1
    assert json.loads(physical_lines[0])["meta"] == message.meta


def test_collector_registers_gateway_callbacks_and_closes_in_order(tmp_path: Path) -> None:
    events: list[str] = []

    class RecordingWriter(LiveDanmakuWriter):
        def write(self, message: DanmakuMessage) -> None:
            events.append("write")
            super().write(message)

        def close(self) -> None:
            events.append("writer-close")
            super().close()

    class RecordingGateway(FakeGateway):
        def stop(self) -> None:
            events.append("gateway-stop")
            super().stop()

    gateway = RecordingGateway()
    writer = RecordingWriter(tmp_path, room_id=123, timestamp="20260729T010203Z")
    collector = LiveDanmakuCollector(gateway, writer)

    collector.start()
    assert gateway.message_callback is not None
    gateway.message_callback(DanmakuMessage(text="你好"))
    collector.stop()
    collector.stop()

    assert gateway.started == 1
    assert gateway.stopped == 1
    assert events == ["write", "gateway-stop", "writer-close"]


def test_cli_requires_positive_room_and_uses_local_default_output() -> None:
    options = parse_live_danmaku_options(["--room-id", "123"])

    assert options.room_id == 123
    assert options.output_dir == Path("scripts/danmaku_output")
    with pytest.raises(SystemExit):
        parse_live_danmaku_options(["--room-id", "0"])
    with pytest.raises(SystemExit):
        parse_live_danmaku_options([])
