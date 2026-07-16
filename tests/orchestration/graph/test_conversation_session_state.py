from animetta.orchestration.graph.conversation_session import ConversationSessionState


def test_session_window_keeps_last_six_completed_pairs() -> None:
    session = ConversationSessionState()
    for index in range(8):
        assert session.commit(
            task_id=f"task-{index}", user_text=f"u{index}", final_response=f"a{index}"
        )
    assert len(session.completed_window) == 6
    assert session.completed_window[0] == ("u2", "a2")
    assert session.completed_window[-1] == ("u7", "a7")


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
