from __future__ import annotations

import json
from pathlib import Path

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.capture import (
    AnonymousLivestreamCollector,
    CaptureDependencyError,
    require_capture_dependencies,
)
from evaluations.livestream.dataset import DatasetWriter, HeatTier


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def wait(self, timeout: float) -> bool:
        self.now += timeout
        return False


class FakeCaptureService:
    def __init__(self, room_id: int, sessdata: str = "") -> None:
        self.room_id = room_id
        self.sessdata = sessdata
        self.event_callback = None
        self.status_callback = None
        self.stopped = False

    def set_event_callback(self, callback) -> None:
        self.event_callback = callback

    def set_status_callback(self, callback) -> None:
        self.status_callback = callback

    def start(self) -> None:
        assert self.event_callback is not None
        self.event_callback(
            LivestreamEvent(
                sequence=0,
                offset_ms=0,
                event_type=LivestreamEventType.DANMAKU,
                actor_id="Alice",
                text="hello",
                payload={"user_id": 42},
            ),
        )

    def stop(self) -> None:
        self.stopped = True


def test_missing_capture_dependency_has_actionable_install_command() -> None:
    def missing(_name: str):
        raise ModuleNotFoundError

    with pytest.raises(CaptureDependencyError, match="requirements-dev.txt"):
        require_capture_dependencies(import_module=missing)


def test_collector_connects_anonymously_and_never_persists_room_identity(tmp_path: Path) -> None:
    clock = FakeClock()
    services: list[FakeCaptureService] = []

    def factory(room_id: int, sessdata: str = "") -> FakeCaptureService:
        service = FakeCaptureService(room_id, sessdata)
        services.append(service)
        return service

    writer = DatasetWriter(tmp_path, dataset_id="low-a", heat_tier=HeatTier.LOW)
    collector = AnonymousLivestreamCollector(
        room_id=123456,
        writer=writer,
        duration_seconds=60,
        service_factory=factory,
        monotonic=clock.monotonic,
        waiter=clock.wait,
        dependency_check=lambda: None,
    )

    manifest = collector.capture()

    assert services[0].sessdata == ""
    assert services[0].stopped is True
    serialized = json.dumps(manifest, ensure_ascii=False) + (tmp_path / "events.jsonl").read_text(
        encoding="utf-8",
    )
    assert "123456" not in serialized
    assert "Alice" not in serialized
    assert "42" not in serialized
