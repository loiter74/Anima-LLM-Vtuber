"""Public Minecraft activity is durable, scoped, ordered, and safe to broadcast."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import (
    CommandDraft,
    InMemoryCommandJournal,
    JournalCommand,
)
from animetta.tools.minecraft.voyager.public_activity import (
    PublicActivityEventPublisher,
    PublicActivityRecorder,
    RuntimePublicActivityAggregator,
    project_activity_page,
)
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal


async def _command(
    repository: InMemoryCommandJournal | SQLiteCommandJournal,
    *,
    command_id: str = "command-one",
    caller_scope: str = "conversation:one",
    request_id: str = "request-one",
    target: str = "minecraft:oak_log",
) -> JournalCommand:
    return (
        await repository.create_command(
            CommandDraft(
                command_id=command_id,
                caller_scope=caller_scope,
                request_id=request_id,
                request_hash="a" * 64,
                kind="execute",
                mode="mission",
                payload={
                    "mission_id": "mission-one",
                    "goal": {"intent": "acquire", "target": target},
                },
                requested_budget={},
                effective_budget={"max_actions": 4},
                accepted_at_ms=1,
            )
        )
    )[0]


async def test_recorder_projects_public_scoped_cursor_replay_after_commit() -> None:
    repository = InMemoryCommandJournal()
    one = await _command(repository)
    two = await _command(
        repository,
        command_id="command-two",
        caller_scope="conversation:two",
        request_id="request-two",
    )
    emitted: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        emitted.append(event)

    timestamps = iter((100, 101, 102, 103))
    recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: next(timestamps),
        publisher=PublicActivityEventPublisher(emit=emit),
    )

    first = await recorder.record_command(one, source_key="one:planning", phase="planning")
    second = await recorder.record_command(one, source_key="one:acting", phase="acting")
    third = await recorder.record_command(two, source_key="two:planning", phase="planning")
    duplicate = await recorder.record_command(one, source_key="one:planning", phase="planning")

    assert first is not None and second is not None and third is not None and duplicate is not None
    assert duplicate.sequence == first.sequence
    assert len(emitted) == 3
    page_one = project_activity_page(await repository.read_activity("conversation:one", limit=1))
    assert page_one.next_cursor == str(first.sequence)
    assert len(page_one.events) == 1
    page_two = project_activity_page(
        await repository.read_activity("conversation:one", limit=1, cursor=page_one.next_cursor)
    )
    assert page_two.next_cursor is None
    assert page_two.events[0].projection_version == second.sequence

    public = page_one.events[0].model_dump(mode="json")
    assert public == emitted[0]
    assert public["event"] == "minecraft.activity.projection"
    assert public["entity_id"] == "minecraft"
    assert public["payload"] == {
        "phase": "planning",
        "intent": "acquire",
        "focus": {"kind": "item", "label": "oak log"},
        "progress": None,
        "outcome": "active",
    }
    assert "command_id" not in public
    assert "caller_scope" not in public
    assert "source_key" not in public
    assert "command-one" not in str(public)
    assert not (await repository.read_activity("conversation:missing")).records
    recent = await repository.read_recent_activity(limit=2)
    assert [record.sequence for record in recent.records] == [second.sequence, third.sequence]


async def test_recorder_is_disabled_and_publisher_failure_is_best_effort() -> None:
    repository = InMemoryCommandJournal()
    command = await _command(repository)
    calls = 0

    async def fail_emit(_event: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("broadcast unavailable")

    disabled = PublicActivityRecorder(
        repository=repository,
        enabled=False,
        now_ms=lambda: 99,
    )
    assert await disabled.record_command(command, source_key="disabled", phase="planning") is None
    assert not (await repository.read_activity(command.caller_scope)).records

    recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 100,
        publisher=PublicActivityEventPublisher(emit=fail_emit),
    )
    record = await recorder.record_command(command, source_key="persisted", phase="planning")
    conflict = await recorder.record_command(command, source_key="persisted", phase="acting")
    invalid_public_context = command.model_copy(update={"payload": {"mission_id": "x" * 129}})
    invalid = await recorder.record_command(
        invalid_public_context,
        source_key="invalid",
        phase="planning",
    )

    assert record is not None
    assert conflict is None
    assert invalid is None
    assert calls == 1
    persisted = await repository.read_activity(command.caller_scope)
    assert [item.source_key for item in persisted.records] == ["persisted"]


async def test_focus_requires_a_canonical_id_and_drops_coordinates_or_free_text() -> None:
    repository = InMemoryCommandJournal()
    coordinate = await _command(repository, target="12,64,-5")
    free_text = await _command(
        repository,
        command_id="command-two",
        request_id="request-two",
        target="defeat a zombie",
    )
    canonical_shaped_free_text = await _command(
        repository,
        command_id="command-three",
        request_id="request-three",
        target="minecraft:defeat_a_zombie",
    )
    unknown_namespace = await _command(
        repository,
        command_id="command-four",
        request_id="request-four",
        target="private:oak_log",
    )
    recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 100,
    )

    coordinate_record = await recorder.record_command(
        coordinate, source_key="coordinate", phase="planning"
    )
    free_text_record = await recorder.record_command(
        free_text, source_key="free-text", phase="planning"
    )
    canonical_shaped_record = await recorder.record_command(
        canonical_shaped_free_text,
        source_key="canonical-shaped-free-text",
        phase="planning",
    )
    unknown_namespace_record = await recorder.record_command(
        unknown_namespace,
        source_key="unknown-namespace",
        phase="planning",
    )

    assert coordinate_record is not None and coordinate_record.payload.focus is None
    assert free_text_record is not None and free_text_record.payload.focus is None
    assert canonical_shaped_record is not None and canonical_shaped_record.payload.focus is None
    assert unknown_namespace_record is not None and unknown_namespace_record.payload.focus is None


async def test_runtime_phase_aggregator_maps_private_facts_without_exposing_raw_data() -> None:
    class Bridge:
        def __init__(self) -> None:
            self.callbacks = []

        def add_runtime_event_callback(self, callback) -> None:
            self.callbacks.append(callback)

        def emit(self, event: dict[str, Any]) -> None:
            for callback in self.callbacks:
                callback(event)

    repository = InMemoryCommandJournal()
    await _command(repository)
    emitted: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        emitted.append(event)

    bridge = Bridge()
    aggregator = RuntimePublicActivityAggregator(
        bridge=bridge,
        repository=repository,
        recorder=PublicActivityRecorder(
            repository=repository,
            enabled=True,
            now_ms=lambda: 200,
            publisher=PublicActivityEventPublisher(emit=emit),
        ),
    )
    aggregator.start()
    base = {
        "type": "action_phase",
        "schema_version": "1",
        "runtime_instance_id": "private-runtime",
        "correlation_id": "private-correlation",
        "command_id": "command-one",
        "step_id": "private-step",
        "capability": "goto",
        "occurred_at_ms": 100,
        "presentation_mode": "full",
    }
    moving = {
        **base,
        "phase_sequence": 1,
        "phase": "moving",
        "target": {"kind": "position", "position": {"x": 12, "y": 64, "z": -5}},
    }
    bridge.emit(moving)
    bridge.emit(moving)
    bridge.emit({**base, "phase_sequence": 2, "phase": "verifying"})
    bridge.emit({**base, "phase_sequence": 3, "phase": "completed"})
    bridge.emit({**base, "phase_sequence": 33, "phase": "moving"})
    await aggregator.drain()

    page = project_activity_page(await repository.read_recent_activity())
    assert [event.payload.phase for event in page.events] == ["acting", "checking"]
    assert len(emitted) == 2
    assert aggregator.invalid_events == 1
    public_json = page.model_dump_json()
    for private_value in (
        "moving",
        "verifying",
        "private-runtime",
        "private-correlation",
        "private-step",
        '"x":12',
    ):
        assert private_value not in public_json


async def test_runtime_phase_aggregator_serializes_each_correlation_by_phase_sequence() -> None:
    class DelayedRepository(InMemoryCommandJournal):
        def __init__(self) -> None:
            super().__init__()
            self.first_read_started = asyncio.Event()
            self.release_first_read = asyncio.Event()
            self.read_count = 0

        async def get_command(self, command_id: str) -> JournalCommand | None:
            self.read_count += 1
            if self.read_count == 1:
                self.first_read_started.set()
                await self.release_first_read.wait()
            return await super().get_command(command_id)

    class Bridge:
        def __init__(self) -> None:
            self.callback = None

        def add_runtime_event_callback(self, callback) -> None:
            self.callback = callback

        def emit(self, event: dict[str, Any]) -> None:
            assert self.callback is not None
            self.callback(event)

    repository = DelayedRepository()
    await _command(repository)
    bridge = Bridge()
    aggregator = RuntimePublicActivityAggregator(
        bridge=bridge,
        repository=repository,
        recorder=PublicActivityRecorder(
            repository=repository,
            enabled=True,
            now_ms=lambda: 200,
        ),
    )
    aggregator.start()
    base = {
        "type": "action_phase",
        "schema_version": "1",
        "runtime_instance_id": "runtime-one",
        "correlation_id": "correlation-one",
        "command_id": "command-one",
        "step_id": "step-one",
        "capability": "goto",
        "occurred_at_ms": 100,
        "presentation_mode": "full",
    }

    bridge.emit({**base, "phase_sequence": 1, "phase": "moving"})
    await repository.first_read_started.wait()
    bridge.emit({**base, "phase_sequence": 2, "phase": "verifying"})
    repository.release_first_read.set()
    await aggregator.drain()

    page = await repository.read_recent_activity()
    assert [record.payload.phase for record in page.records] == ["acting", "checking"]


async def test_runtime_active_phase_cannot_be_committed_after_finished() -> None:
    class DelayedRepository(InMemoryCommandJournal):
        def __init__(self) -> None:
            super().__init__()
            self.read_started = asyncio.Event()
            self.release_read = asyncio.Event()

        async def get_command(self, command_id: str) -> JournalCommand | None:
            self.read_started.set()
            await self.release_read.wait()
            return await super().get_command(command_id)

    class Bridge:
        def __init__(self) -> None:
            self.callback = None

        def add_runtime_event_callback(self, callback) -> None:
            self.callback = callback

        def emit(self, event: dict[str, Any]) -> None:
            assert self.callback is not None
            self.callback(event)

    repository = DelayedRepository()
    command = await _command(repository)
    recorder = PublicActivityRecorder(repository=repository, enabled=True, now_ms=lambda: 200)
    bridge = Bridge()
    aggregator = RuntimePublicActivityAggregator(
        bridge=bridge,
        repository=repository,
        recorder=recorder,
    )
    aggregator.start()
    bridge.emit(
        {
            "type": "action_phase",
            "schema_version": "1",
            "runtime_instance_id": "runtime-one",
            "correlation_id": "correlation-one",
            "command_id": command.command_id,
            "step_id": "step-one",
            "capability": "goto",
            "phase_sequence": 1,
            "phase": "moving",
            "occurred_at_ms": 100,
            "presentation_mode": "full",
        }
    )
    await repository.read_started.wait()
    terminal = await recorder.record_command(
        command,
        source_key="command-one:finished:succeeded",
        phase="finished",
        outcome="succeeded",
    )
    assert terminal is not None
    repository.release_read.set()
    await aggregator.drain()

    page = await repository.read_recent_activity()
    assert [record.payload.phase for record in page.records] == ["finished"]


async def test_runtime_phase_aggregator_unsubscribes_and_bounds_terminal_dedupe() -> None:
    class Bridge:
        def __init__(self) -> None:
            self.callbacks = []

        def add_runtime_event_callback(self, callback):
            self.callbacks.append(callback)

            def unsubscribe() -> None:
                self.callbacks.remove(callback)

            return unsubscribe

        def emit(self, event: dict[str, Any]) -> None:
            for callback in tuple(self.callbacks):
                callback(event)

    bridge = Bridge()
    repository = InMemoryCommandJournal()
    aggregator = RuntimePublicActivityAggregator(
        bridge=bridge,
        repository=repository,
        recorder=PublicActivityRecorder(
            repository=repository,
            enabled=True,
            now_ms=lambda: 0,
        ),
    )
    aggregator.start()
    for sequence in range(2_100):
        bridge.emit(
            {
                "type": "action_phase",
                "schema_version": "1",
                "runtime_instance_id": "runtime-1",
                "correlation_id": f"correlation-{sequence}",
                "command_id": f"command-{sequence}",
                "step_id": "step-1",
                "capability": "goto",
                "phase_sequence": 2,
                "phase": "completed",
                "occurred_at_ms": sequence,
                "presentation_mode": "full",
            }
        )

    assert len(aggregator._last_phase_sequence) == 2_048
    assert len(bridge.callbacks) == 1

    await aggregator.drain()

    assert bridge.callbacks == []
    assert aggregator._last_phase_sequence == {}


async def test_sqlite_activity_is_idempotent_replayable_and_retained(tmp_path: Path) -> None:
    path = tmp_path / "activity.db"
    repository = SQLiteCommandJournal(path)
    await repository.connect()
    command = await _command(repository)
    timestamps = iter((100, 200))
    recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: next(timestamps),
    )
    first = await recorder.record_command(command, source_key="one", phase="planning")
    second = await recorder.record_command(command, source_key="two", phase="acting")
    await repository.close()

    reopened = SQLiteCommandJournal(path)
    await reopened.connect()
    duplicate = await PublicActivityRecorder(
        repository=reopened,
        enabled=True,
        now_ms=lambda: 300,
    ).record_command(command, source_key="one", phase="planning")
    before_expiry = await reopened.read_activity(command.caller_scope)

    assert first is not None and second is not None and duplicate is not None
    assert duplicate.sequence == first.sequence
    assert [item.sequence for item in before_expiry.records] == [first.sequence, second.sequence]
    assert await reopened.expire_activity(before_ms=200) == 1
    after_expiry = await reopened.read_activity(command.caller_scope)
    assert [item.sequence for item in after_expiry.records] == [second.sequence]
    await reopened.close()


async def test_activity_retention_is_applied_atomically_on_every_append(tmp_path: Path) -> None:
    repositories = [
        InMemoryCommandJournal(),
        SQLiteCommandJournal(tmp_path / "automatic-retention.db"),
    ]
    await repositories[1].connect()
    for repository in repositories:
        command = await _command(repository)
        timestamps = iter((100, 250))
        recorder = PublicActivityRecorder(
            repository=repository,
            enabled=True,
            now_ms=lambda: next(timestamps),
            retention_ms=100,
        )
        first = await recorder.record_command(command, source_key="old", phase="planning")
        second = await recorder.record_command(command, source_key="current", phase="acting")

        assert first is not None and second is not None
        assert [
            record.source_key for record in (await repository.read_recent_activity()).records
        ] == ["current"]

    await repositories[1].close()


async def test_failed_append_does_not_commit_retention_cleanup(tmp_path: Path) -> None:
    repository = SQLiteCommandJournal(tmp_path / "atomic-retention.db")
    await repository.connect()
    command = await _command(repository)
    recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 100,
        retention_ms=100,
    )
    assert await recorder.record_command(command, source_key="old", phase="planning") is not None

    foreign_repository = InMemoryCommandJournal()
    foreign = await _command(
        foreign_repository,
        command_id="foreign-command",
        request_id="foreign-request",
    )
    failed_recorder = PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 1_000,
        retention_ms=100,
    )
    assert (
        await failed_recorder.record_command(foreign, source_key="invalid", phase="planning")
        is None
    )

    assert [record.source_key for record in (await repository.read_recent_activity()).records] == [
        "old"
    ]
    await repository.close()


async def test_terminal_payload_retention_removes_linked_activity_atomically(
    tmp_path: Path,
) -> None:
    repository = SQLiteCommandJournal(tmp_path / "terminal-retention.db")
    await repository.connect()
    command = await _command(repository)
    await PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 100,
    ).record_command(command, source_key="planning", phase="planning")
    running = await repository.transition(
        command.command_id,
        expected_version=command.state_version,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="test",
        occurred_at_ms=110,
    )
    await repository.transition(
        command.command_id,
        expected_version=running.state_version,
        target=CommandState.SUCCEEDED,
        reason_code="VERIFIED",
        actor="test",
        occurred_at_ms=120,
    )

    assert await repository.expire_terminal_payloads(before_ms=1_000) == 1
    retained = await repository.get_command(command.command_id)
    activity = await repository.read_recent_activity()
    await repository.close()

    assert retained is not None and retained.payload == {}
    assert activity.records == ()


async def test_in_memory_terminal_payload_retention_matches_sqlite() -> None:
    repository = InMemoryCommandJournal()
    command = await _command(repository)
    await PublicActivityRecorder(
        repository=repository,
        enabled=True,
        now_ms=lambda: 100,
    ).record_command(command, source_key="planning", phase="planning")
    running = await repository.transition(
        command.command_id,
        expected_version=command.state_version,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="test",
        occurred_at_ms=110,
    )
    await repository.transition(
        command.command_id,
        expected_version=running.state_version,
        target=CommandState.SUCCEEDED,
        reason_code="VERIFIED",
        actor="test",
        occurred_at_ms=120,
    )

    assert await repository.expire_terminal_payloads(before_ms=1_000) == 1
    retained = await repository.get_command(command.command_id)
    assert retained is not None and retained.payload == {}
    assert not (await repository.read_recent_activity()).records


async def test_sqlite_connect_adds_activity_schema_to_existing_journal(tmp_path: Path) -> None:
    path = tmp_path / "migration.db"
    initial = SQLiteCommandJournal(path)
    await initial.connect()
    await initial.close()
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE public_activity_events")
        db.execute("DELETE FROM journal_schema_meta WHERE schema_version=2")
        db.execute(
            "INSERT OR IGNORE INTO journal_schema_meta(schema_version,applied_at_ms) VALUES (1,0)"
        )

    migrated = SQLiteCommandJournal(path)
    await migrated.connect()
    command = await _command(migrated)
    record = await PublicActivityRecorder(
        repository=migrated,
        enabled=True,
        now_ms=lambda: 100,
    ).record_command(command, source_key="migrated", phase="planning")
    await migrated.close()

    assert record is not None
    with sqlite3.connect(path) as db:
        versions = [row[0] for row in db.execute("SELECT schema_version FROM journal_schema_meta")]
        indexes = [row[1] for row in db.execute("PRAGMA index_list(public_activity_events)")]
    assert set(versions) == {1, 2}
    assert {
        "idx_activity_command_sequence",
        "idx_activity_occurred_at",
        "idx_activity_scope_sequence",
    } <= set(indexes)
