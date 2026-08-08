"""Vanilla advancement adapter events are durable and de-duplicated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from animetta.tools.gamebot.contracts.v2 import AdvancementObservedEvent, canonical_json_hash
from animetta.tools.minecraft.voyager.advancement_store import (
    AdvancementEventRecorder,
    InMemoryAdvancementEventStore,
    SQLiteAdvancementEventStore,
)

ROOT = Path(__file__).resolve().parents[4]
EVENT = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]["AdvancementObservedEvent"]


async def _exercise(store) -> None:
    await store.connect()
    payload = dict(EVENT)
    payload["content_hash"] = canonical_json_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    event = AdvancementObservedEvent.model_validate(payload)

    assert await store.append(event) is True
    assert await store.append(event) is False

    events = await store.list_scope(
        world_identity_hash=event.world_identity.world_identity_hash,
        runtime_instance_id=event.runtime_instance_id,
    )
    assert events == (event,)
    assert await store.active_added(
        world_identity_hash=event.world_identity.world_identity_hash,
        runtime_instance_id=event.runtime_instance_id,
    ) == frozenset({event.advancement_id})
    await store.close()


async def test_advancement_event_stores_are_durable_and_idempotent(tmp_path) -> None:
    await _exercise(InMemoryAdvancementEventStore())
    await _exercise(SQLiteAdvancementEventStore(tmp_path / "minecraft-journal.db"))


async def test_recorder_validates_bridge_event_before_persisting() -> None:
    class Bridge:
        def add_runtime_event_callback(self, callback):
            self.callback = callback

    bridge = Bridge()
    store = InMemoryAdvancementEventStore()
    await store.connect()
    recorder = AdvancementEventRecorder(bridge=bridge, store=store)
    recorder.start()
    payload = dict(EVENT)
    payload["content_hash"] = canonical_json_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )

    bridge.callback({"type": "advancement_observed", **payload})
    await recorder.drain()

    events = await store.list_scope(
        world_identity_hash=payload["world_identity"]["world_identity_hash"],
        runtime_instance_id=payload["runtime_instance_id"],
    )
    assert len(events) == 1


async def test_recorder_drain_surfaces_async_store_failure() -> None:
    class Bridge:
        def add_runtime_event_callback(self, callback):
            self.callback = callback

    class FailingStore(InMemoryAdvancementEventStore):
        async def append(self, event):
            del event
            raise RuntimeError("ADVANCEMENT_STORE_FAILED")

    bridge = Bridge()
    store = FailingStore()
    await store.connect()
    recorder = AdvancementEventRecorder(bridge=bridge, store=store)
    recorder.start()
    payload = dict(EVENT)
    payload["content_hash"] = canonical_json_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )

    bridge.callback({"type": "advancement_observed", **payload})
    await __import__("asyncio").sleep(0)

    with pytest.raises(RuntimeError, match="ADVANCEMENT_STORE_FAILED"):
        await recorder.drain()
