from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / ".agents"
    / "skills"
    / "connect-bilibili-live"
    / "scripts"
    / "bilibili_live.py"
)


def load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bilibili_live", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeController:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int | None, float | None]] = []
        self.closed = False

    async def get_status(self) -> dict[str, Any]:
        self.calls.append(("status", None, None))
        return self.results["status"]

    async def connect_room(self, room_id: int, timeout_seconds: float) -> dict[str, Any]:
        self.calls.append(("connect", room_id, timeout_seconds))
        return self.results["connect"]

    async def switch_room(self, room_id: int, timeout_seconds: float) -> dict[str, Any]:
        self.calls.append(("switch", room_id, timeout_seconds))
        return self.results["switch"]

    async def disconnect_room(self, timeout_seconds: float) -> dict[str, Any]:
        self.calls.append(("disconnect", None, timeout_seconds))
        return self.results["disconnect"]

    async def close(self) -> None:
        self.closed = True


def result(
    *,
    ok: bool = True,
    room_id: int | None = 1234567890,
    state: str = "prelive",
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "error_code": error_code,
        "message": state,
        "status": {
            "state": state,
            "room_id": room_id,
            "generation_id": 3,
        },
    }


def fake_results(**overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = {
        "status": result(),
        "connect": result(),
        "switch": result(),
        "disconnect": result(room_id=None, state="stopped"),
    }
    values.update(overrides)
    return values


def run(
    cli: ModuleType,
    argv: list[str],
    controller: FakeController,
    config_path: Path,
    *,
    ready: bool = True,
) -> dict[str, Any]:
    args = cli.build_parser().parse_args(argv)
    return asyncio.run(
        cli.execute(
            args,
            config_path=config_path,
            controller_factory=lambda _url: controller,
            readiness_probe=lambda _url, _timeout: ready,
        )
    )


def test_connect_uses_default_room_and_closes_only_the_control_transport(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 1234567890\nsessdata: secret-marker\n", encoding="utf-8")
    controller = FakeController(fake_results())

    output = run(cli, ["connect"], controller, config)

    assert output["ok"] is True
    assert output["room_id"] == 1234567890
    assert output["state"] == "prelive"
    assert output["generation_id"] == 3
    assert output["elapsed_ms"] >= 0
    assert controller.calls == [("connect", 1234567890, 30.0)]
    assert controller.closed is True
    assert "secret-marker" not in json.dumps(output)


def test_local_override_room_wins_over_the_tracked_template(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 0\n", encoding="utf-8")
    override = tmp_path / "bilibili.local.yaml"
    override.write_text("room_id: 1234567890\n", encoding="utf-8")
    controller = FakeController(fake_results())

    output = run(cli, ["connect"], controller, config)

    assert output["ok"] is True
    assert controller.calls == [("connect", 1234567890, 30.0)]


def test_default_room_reader_stops_before_the_credential_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = load_cli()

    class StopAfterRoom:
        def __init__(self, lines: list[str]) -> None:
            self._lines = iter(lines)
            self.lines_read = 0

        def __enter__(self) -> StopAfterRoom:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self) -> StopAfterRoom:
            return self

        def __next__(self) -> str:
            line = next(self._lines)
            self.lines_read += 1
            if "sessdata" in line:
                raise AssertionError("credential line must not be read")
            return line

    reader = StopAfterRoom(["room_id: 1234567890\n", "sessdata: secret-marker\n"])

    def open_config(_path: Path, **_kwargs: object) -> StopAfterRoom:
        return reader

    monkeypatch.setattr(Path, "open", open_config)

    assert cli.load_default_room(Path("unused.yaml")) == 1234567890
    assert reader.lines_read == 1


def test_invalid_default_room_is_structured_and_never_opens_a_controller(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 0\n", encoding="utf-8")
    created = False

    def create(_url: str) -> FakeController:
        nonlocal created
        created = True
        return FakeController(fake_results())

    args = cli.build_parser().parse_args(["connect"])
    output = asyncio.run(
        cli.execute(
            args,
            config_path=config,
            controller_factory=create,
            readiness_probe=lambda _url, _timeout: True,
        )
    )

    assert output["error_code"] == "invalid_default_room"
    assert output["state"] is None
    assert created is False


def test_invalid_explicit_room_is_returned_as_a_structured_controller_error(
    tmp_path: Path,
) -> None:
    cli = load_cli()
    invalid = result(ok=False, room_id=None, state="stopped", error_code="invalid_room_id")
    controller = FakeController(fake_results(connect=invalid))

    output = run(
        cli,
        ["connect", "--room-id", "0"],
        controller,
        tmp_path / "unused.yaml",
    )

    assert output["ok"] is False
    assert output["error_code"] == "invalid_room_id"
    assert controller.calls == []


def test_runtime_unavailable_stops_before_the_room_command(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 1234567890\n", encoding="utf-8")
    controller = FakeController(fake_results())

    output = run(cli, ["connect"], controller, config, ready=False)

    assert output["error_code"] == "runtime_not_ready"
    assert controller.calls == []
    assert controller.closed is False


def test_same_room_connect_remains_idempotent(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 1234567890\n", encoding="utf-8")
    controller = FakeController(fake_results())

    output = run(cli, ["connect"], controller, config)

    assert output["ok"] is True
    assert controller.calls == [("connect", 1234567890, 30.0)]


def test_other_room_conflict_is_preserved_without_implicit_switch(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 1234567890\n", encoding="utf-8")
    conflict = result(ok=False, room_id=123, error_code="session_busy")
    controller = FakeController(fake_results(connect=conflict))

    output = run(cli, ["connect"], controller, config)

    assert output["ok"] is False
    assert output["error_code"] == "session_busy"
    assert output["room_id"] == 123
    assert controller.calls == [("connect", 1234567890, 30.0)]


def test_explicit_switch_and_timeout_are_forwarded(tmp_path: Path) -> None:
    cli = load_cli()
    controller = FakeController(fake_results(switch=result(room_id=456)))

    output = run(
        cli,
        ["switch", "--room-id", "456", "--timeout-seconds", "12"],
        controller,
        tmp_path / "unused.yaml",
    )

    assert output["room_id"] == 456
    assert controller.calls == [("switch", 456, 12.0)]


def test_timeout_above_the_hot_start_budget_is_rejected(tmp_path: Path) -> None:
    cli = load_cli()
    controller = FakeController(fake_results())

    output = run(
        cli,
        ["connect", "--room-id", "456", "--timeout-seconds", "61"],
        controller,
        tmp_path / "unused.yaml",
    )

    assert output["error_code"] == "invalid_timeout"
    assert controller.calls == []


def test_connect_timeout_remains_structured(tmp_path: Path) -> None:
    cli = load_cli()
    config = tmp_path / "bilibili.yaml"
    config.write_text("room_id: 1234567890\n", encoding="utf-8")
    timeout = result(ok=False, room_id=None, state="connecting", error_code="timeout")
    controller = FakeController(fake_results(connect=timeout))

    output = run(cli, ["connect"], controller, config)

    assert output["ok"] is False
    assert output["state"] == "connecting"
    assert output["error_code"] == "timeout"


def test_controller_start_failure_is_sanitized_as_json(tmp_path: Path) -> None:
    cli = load_cli()
    args = cli.build_parser().parse_args(["status"])

    def fail(_url: str) -> FakeController:
        raise RuntimeError("sensitive transport detail")

    output = asyncio.run(
        cli.execute(
            args,
            config_path=tmp_path / "unused.yaml",
            controller_factory=fail,
            readiness_probe=lambda _url, _timeout: True,
        )
    )

    assert output["error_code"] == "control_failed"
    assert "sensitive" not in json.dumps(output)


def test_status_and_disconnect_do_not_require_a_room_config(tmp_path: Path) -> None:
    cli = load_cli()
    controller = FakeController(fake_results())

    status = run(cli, ["status"], controller, tmp_path / "missing.yaml")
    disconnected = run(cli, ["disconnect"], controller, tmp_path / "missing.yaml")

    assert status["state"] == "prelive"
    assert disconnected["state"] == "stopped"
    assert controller.calls == [("status", None, None), ("disconnect", None, 30.0)]
