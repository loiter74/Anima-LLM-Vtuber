from __future__ import annotations

import importlib
import importlib.util

import pytest
from pydantic import ValidationError


def _models():
    try:
        spec = importlib.util.find_spec("animetta.services.scene_analysis.models")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "scene-analysis contracts must exist"
    return importlib.import_module("animetta.services.scene_analysis.models")


def _reducer():
    try:
        spec = importlib.util.find_spec("animetta.services.scene_analysis.reducer")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "scene-analysis reducer must exist"
    return importlib.import_module("animetta.services.scene_analysis.reducer")


def test_normalized_event_rejects_unknown_fields() -> None:
    models = _models()

    with pytest.raises(ValidationError):
        models.NormalizedSceneEvent(
            event_id="evt-1",
            event_seq=1,
            session_id="live-1",
            room_id=42,
            generation_id=1,
            occurred_at=100.0,
            event_type="danmaku",
            text="hello",
            unexpected="nope",
        )


def test_reducer_applies_current_patch_and_advances_revision() -> None:
    models = _models()
    reducer = _reducer()
    state = models.LiveSceneState.initial(
        session_id="live-1",
        room_id=42,
        generation_id=3,
        now=100.0,
    )
    patch = models.SceneStatePatch(
        base_revision=0,
        consumed_event_seq=12,
        scene_stage="topic_rising",
        pace="fast",
        scene_summary="The room is rallying around a fresh joke.",
        confidence=0.8,
        generated_at=101.0,
        ttl_seconds=60.0,
    )

    updated = reducer.SceneStateReducer.apply(state, patch)

    assert updated.state_revision == 1
    assert updated.last_event_seq == 12
    assert updated.scene_stage == "topic_rising"
    assert updated.pace == "fast"
    assert updated.expires_at == 161.0


def test_reducer_rejects_stale_patch_without_mutating_state() -> None:
    models = _models()
    reducer = _reducer()
    state = models.LiveSceneState.initial(
        session_id="live-1",
        room_id=42,
        generation_id=3,
        now=100.0,
    ).model_copy(update={"state_revision": 2})
    patch = models.SceneStatePatch(
        base_revision=1,
        consumed_event_seq=12,
        generated_at=101.0,
    )

    with pytest.raises(reducer.StaleScenePatchError):
        reducer.SceneStateReducer.apply(state, patch)

    assert state.state_revision == 2
    assert state.last_event_seq == 0


def test_guidance_has_one_bounded_technique_and_meme_policy() -> None:
    models = _models()

    guidance = models.SceneGuidance(
        scene_revision=4,
        scene_summary="A joke is rising.",
        response_objective="Acknowledge it briefly.",
        tone=["playful", "fast"],
        scope=models.ReplyScope(max_sentences=2, max_chars=120),
        technique=models.TechniqueSelection(
            technique_id="catch-and-bounce",
            instruction="Catch the joke, then return one short hook.",
        ),
        meme_policy=models.MemePolicy(
            action="use",
            meme_id="clipping",
            instruction="Use it lightly once.",
        ),
        confidence=0.9,
        expires_at=160.0,
    )

    assert guidance.technique.technique_id == "catch-and-bounce"
    assert guidance.meme_policy.meme_id == "clipping"


def test_retriever_cannot_mutate_live_state_outside_reducer() -> None:
    models = _models()
    from animetta.services.scene_analysis.guidance import GuidanceComposer

    state = models.LiveSceneState.initial(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        now=100.0,
    )

    class MutatingRetriever:
        def select(self, detached_state, evidence):
            del evidence
            detached_state.topics.append(models.TopicState(label="injected", last_event_seq=1))
            return models.TechniqueSelection(
                technique_id="safe-selection",
                instruction="Use one short callback.",
            )

    guidance = GuidanceComposer(technique_retriever=MutatingRetriever()).compose(
        state,
        None,
        now=101.0,
    )

    assert guidance.technique is not None
    assert state.topics == []
    assert state.state_revision == 0
    with pytest.raises(ValidationError):
        models.SceneGuidance(
            scene_revision=4,
            scene_summary="x" * 301,
            response_objective="brief",
            confidence=0.9,
            expires_at=160.0,
        )
