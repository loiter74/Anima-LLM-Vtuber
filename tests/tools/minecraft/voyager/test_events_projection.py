"""At-least-once transition events remain secondary to journal commits."""

from __future__ import annotations

from animetta.tools.minecraft.voyager.events import (
    TransitionEventConsumer,
    TransitionEventPublisher,
)
from animetta.tools.minecraft.voyager.journal import CommandDraft, InMemoryCommandJournal


def draft() -> CommandDraft:
    return CommandDraft(
        command_id="command-1",
        caller_scope="principal:a",
        request_id="request-1",
        request_hash="a" * 64,
        kind="execute",
        mode="atomic",
        payload={},
        requested_budget={},
        effective_budget={},
        accepted_at_ms=1,
    )


async def test_event_publish_failure_never_rolls_back_command_commit() -> None:
    repository = InMemoryCommandJournal()
    command, _ = await repository.create_command(draft())

    async def failing_emit(_event: dict) -> None:
        raise ConnectionError("socket disconnected")

    publisher = TransitionEventPublisher(repository=repository, emit=failing_emit)
    published = await publisher.publish_command(command.command_id)

    assert published == 0
    assert await repository.get_command(command.command_id) is not None


async def test_duplicate_delivery_is_deduplicated_and_rehydrated_from_projection() -> None:
    repository = InMemoryCommandJournal()
    command, _ = await repository.create_command(draft())
    delivered = []

    async def emit(event: dict) -> None:
        delivered.append(event)

    publisher = TransitionEventPublisher(repository=repository, emit=emit)
    await publisher.publish_command(command.command_id)
    await publisher.publish_command(command.command_id)
    consumer = TransitionEventConsumer()
    accepted = [event for event in delivered * 2 if consumer.accept(event)]
    projection = await repository.read_projection("principal:a")

    assert len(delivered) == 1
    assert len(accepted) == 1
    assert accepted[0]["event_id"] == accepted[0]["transition_id"]
    assert projection.commands[0].command_id == command.command_id
