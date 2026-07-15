import pytest

from animetta.orchestration.graph.persistence_policy import (
    PersistenceRequest,
    decide_persistence,
)


@pytest.mark.parametrize(
    "content_class",
    [
        "probe",
        "mock",
        "static_template",
        "internal_prompt",
        "reasoner",
        "translation",
        "rejected_candidate",
    ],
)
def test_forbidden_content_is_rejected_with_content_free_reason(content_class: str) -> None:
    decision = decide_persistence(
        PersistenceRequest(
            mode="read_write",
            sink="long_term_write",
            content_class=content_class,
            completed=True,
            real_provider=True,
        )
    )
    assert not decision.allowed
    assert decision.reason == f"content_class_forbidden:{content_class}"


def test_off_allows_only_ephemeral_final_session_window_and_metadata() -> None:
    final = PersistenceRequest(
        mode="off",
        sink="session_window",
        content_class="selected_final",
        completed=True,
        real_provider=True,
    )
    assert decide_persistence(final).allowed
    assert decide_persistence(
        PersistenceRequest(
            mode="off",
            sink="stats_metadata",
            content_class="outcome_metadata",
            completed=True,
            real_provider=True,
        )
    ).allowed
    assert not decide_persistence(
        PersistenceRequest(
            mode="off",
            sink="checkpoint",
            content_class="selected_final",
            completed=True,
            real_provider=True,
        )
    ).allowed


def test_read_only_permits_recall_but_not_write() -> None:
    recall = PersistenceRequest(
        mode="read_only",
        sink="long_term_recall",
        content_class="query",
        completed=False,
        real_provider=True,
    )
    write = PersistenceRequest(
        mode="read_only",
        sink="long_term_write",
        content_class="selected_final",
        completed=True,
        real_provider=True,
    )
    assert decide_persistence(recall).allowed
    assert not decide_persistence(write).allowed
    assert decide_persistence(write).reason == "mode_read_only"
