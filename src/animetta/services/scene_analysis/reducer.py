"""Single-writer reducer for immutable livestream scene state."""

from __future__ import annotations

from .models import LiveSceneState, SceneStatePatch


class StaleScenePatchError(ValueError):
    """Raised when an analyzer patch targets an obsolete state revision."""


class SceneStateReducer:
    """Apply validated patches without mutating the previous state."""

    @staticmethod
    def apply(state: LiveSceneState, patch: SceneStatePatch) -> LiveSceneState:
        if patch.base_revision != state.state_revision:
            raise StaleScenePatchError(
                f"stale scene patch: base={patch.base_revision}, current={state.state_revision}"
            )

        topics = {item.label: item for item in state.topics}
        for label in patch.topic_removals:
            topics.pop(label, None)
        for topic in patch.topic_upserts:
            topics[topic.label] = topic

        memes = {item.meme_id: item for item in state.meme_states}
        for meme_id in patch.meme_removals:
            memes.pop(meme_id, None)
        for meme in patch.meme_upserts:
            memes[meme.meme_id] = meme

        loops = {item.loop_id: item for item in state.open_loops}
        for loop_id in patch.resolved_open_loop_ids:
            loops.pop(loop_id, None)
        for open_loop in patch.open_loop_additions:
            loops[open_loop.loop_id] = open_loop

        recent_actions = list(state.recent_host_actions)
        if patch.recent_host_action:
            recent_actions.append(patch.recent_host_action)
            recent_actions = recent_actions[-6:]

        update: dict[str, object] = {
            "state_revision": state.state_revision + 1,
            "last_event_seq": max(state.last_event_seq, patch.consumed_event_seq),
            "topics": list(topics.values())[-8:],
            "meme_states": list(memes.values())[-8:],
            "open_loops": list(loops.values())[-8:],
            "recent_host_actions": recent_actions,
            "confidence": patch.confidence,
            "generated_at": patch.generated_at,
            "expires_at": patch.generated_at + patch.ttl_seconds,
            "degraded": False,
            "degradation_reasons": [],
        }
        for name in (
            "scene_stage",
            "pace",
            "atmosphere",
            "engagement_level",
            "engagement_trend",
            "scene_summary",
        ):
            value = getattr(patch, name)
            if value is not None:
                update[name] = value

        return state.model_copy(update=update)

    @staticmethod
    def degrade(
        state: LiveSceneState,
        *,
        reasons: list[str],
        now: float,
        ttl_seconds: float = 15.0,
    ) -> LiveSceneState:
        """Record a typed degradation through the single state writer."""
        return state.model_copy(
            update={
                "state_revision": state.state_revision + 1,
                "degraded": True,
                "degradation_reasons": list(dict.fromkeys(reasons))[:6],
                "generated_at": now,
                "expires_at": now + ttl_seconds,
                "confidence": min(state.confidence, 0.35),
            }
        )
