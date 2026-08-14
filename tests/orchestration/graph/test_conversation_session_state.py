import asyncio

import pytest

from animetta.orchestration.graph.conversation_session import (
    ConversationScope,
    ConversationSessionRegistry,
    ConversationSessionState,
    resolve_conversation_scope,
)


def test_session_window_keeps_last_six_completed_pairs() -> None:
    session = ConversationSessionState()
    for index in range(8):
        assert session.commit(
            task_id=f"task-{index}", user_text=f"u{index}", final_response=f"a{index}"
        )
    assert len(session.completed_window) == 6
    assert session.completed_window[0] == ("u2", "a2")
    assert session.completed_window[-1] == ("u7", "a7")


def test_session_window_preserves_turn_provenance_atomically() -> None:
    session = ConversationSessionState()
    session.commit(
        task_id="task",
        user_text="本场暗号是蓝玻璃",
        final_response="收到。",
        actor_role="developer",
        source="developer_console",
    )

    turn = session.completed_turns[0]
    assert turn.user_text == "本场暗号是蓝玻璃"
    assert turn.final_response == "收到。"
    assert turn.task_id == "task"
    assert turn.actor_role == "developer"
    assert turn.source == "developer_console"
    assert "后台私有上下文" in session.prompt_window[0][0]
    assert "可使用回答所需的普通事实" in session.prompt_window[0][0]
    assert "不得复述整段原文" in session.prompt_window[0][0]


def test_commit_is_idempotent_and_updates_bounded_state() -> None:
    session = ConversationSessionState()
    assert session.commit(
        task_id="task",
        user_text="u",
        final_response="a",
        mood="bright",
        affinity_delta=2,
    )
    assert not session.commit(
        task_id="task",
        user_text="u",
        final_response="duplicate",
        mood="tired",
        affinity_delta=2,
    )
    assert session.completed_window == (("u", "a"),)
    assert session.mood == "bright"
    assert session.fatigue == 5
    assert session.affinity == 52


def test_state_values_are_clamped_and_reset() -> None:
    session = ConversationSessionState(affinity=99, fatigue=98)
    session.commit(task_id="task", user_text="u", final_response="a", affinity_delta=2)
    assert session.affinity == 100
    assert session.fatigue == 100
    session.reset()
    assert session.completed_window == ()
    assert session.mood == "neutral"
    assert session.fatigue == 0
    assert session.affinity == 50


def test_scope_resolution_shares_livestream_and_isolates_private_conversations() -> None:
    developer = resolve_conversation_scope(
        conversation_id="dashboard-conversation",
        session_id="dashboard-socket",
        metadata={"audience": "livestream", "live_session_id": "live-1"},
    )
    viewer = resolve_conversation_scope(
        conversation_id="danmaku-conversation",
        session_id="bilibili-socket",
        metadata={"audience": "livestream", "live_session_id": "live-1"},
    )
    other_live = resolve_conversation_scope(
        conversation_id="dashboard-conversation",
        session_id="dashboard-socket",
        metadata={"audience": "livestream", "live_session_id": "live-2"},
    )
    private = resolve_conversation_scope(
        conversation_id="dashboard-conversation",
        session_id="dashboard-socket",
        metadata={"audience": "private"},
    )

    assert developer == viewer == ConversationScope("livestream", "live-1")
    assert other_live != developer
    assert private == ConversationScope("conversation", "dashboard-conversation")


@pytest.mark.asyncio
async def test_registry_enforces_lru_limit_and_rebuild_starts_empty() -> None:
    registry = ConversationSessionRegistry(max_scopes=2)
    scopes = [ConversationScope("conversation", f"conversation-{index}") for index in range(3)]

    for index, scope in enumerate(scopes):
        async with registry.turn(scope) as session:
            session.commit(
                task_id=f"task-{index}", user_text=f"u{index}", final_response=f"a{index}"
            )

    assert registry.scope_count == 2
    assert registry.peek(scopes[0]) is None
    assert registry.peek(scopes[1]) is not None
    assert registry.peek(scopes[2]) is not None
    assert ConversationSessionRegistry(max_scopes=2).scope_count == 0


@pytest.mark.asyncio
async def test_registry_serializes_turns_in_one_scope() -> None:
    registry = ConversationSessionRegistry()
    scope = ConversationScope("livestream", "live-1")
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with registry.turn(scope):
            order.append("first")
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with registry.turn(scope):
            order.append("second")

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert order == ["first"]
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert order == ["first", "second"]
