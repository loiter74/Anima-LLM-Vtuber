"""Compose bounded prompt guidance from reduced scene state."""

from __future__ import annotations

from typing import Protocol

from .models import (
    LiveSceneState,
    MemePolicy,
    ReplyScope,
    SceneEvidence,
    SceneGuidance,
    TechniqueSelection,
)


class TechniqueRetriever(Protocol):
    """Select one applicable livestream technique without exposing candidates."""

    def select(
        self,
        state: LiveSceneState,
        evidence: SceneEvidence | None,
    ) -> TechniqueSelection | None: ...


class MemeRetriever(Protocol):
    """Select one meme policy without exposing retrieved documents."""

    def select(
        self,
        state: LiveSceneState,
        evidence: SceneEvidence | None,
    ) -> MemePolicy | None: ...


class GuidanceComposer:
    """Translate current scene state and rule deltas into bounded instructions."""

    def __init__(
        self,
        *,
        technique_retriever: TechniqueRetriever | None = None,
        meme_retriever: MemeRetriever | None = None,
    ) -> None:
        self._technique_retriever = technique_retriever
        self._meme_retriever = meme_retriever

    def compose(
        self,
        state: LiveSceneState,
        evidence: SceneEvidence | None,
        *,
        now: float,
        extra_degradation_reasons: list[str] | None = None,
    ) -> SceneGuidance:
        degradation_reasons = list(state.degradation_reasons)
        degradation_reasons.extend(extra_degradation_reasons or [])
        technique = self._select_technique(state, evidence, degradation_reasons)
        meme_policy = self._select_meme(state, evidence, degradation_reasons)
        must_address: list[str] = []
        if evidence and evidence.metrics.critical_event_count:
            must_address.append("Acknowledge the paid or critical event.")

        pace_limits = {
            "slow": ReplyScope(max_sentences=3, max_chars=220),
            "normal": ReplyScope(max_sentences=2, max_chars=180),
            "fast": ReplyScope(max_sentences=2, max_chars=140),
            "very_fast": ReplyScope(max_sentences=1, max_chars=100),
        }
        tones = {
            "neutral": ["natural"],
            "warm": ["warm", "inclusive"],
            "playful": ["playful", "quick"],
            "excited": ["energetic", "concise"],
            "tense": ["calm", "de-escalating"],
        }
        avoid = [
            "Do not force or repeat an overused meme."
            for meme in state.meme_states
            if meme.lifecycle in {"overused", "cooldown"}
        ][:1]
        objective = {
            "warming": "Welcome the room and open an easy participation path.",
            "steady": "Continue the current topic and keep the room involved.",
            "topic_rising": "Build on the rising topic without derailing it.",
            "climax": "Land the peak cleanly and keep the reply short.",
            "cooldown": "Close the saturated beat and transition naturally.",
        }[state.scene_stage]

        unique_reasons = list(dict.fromkeys(degradation_reasons))[:6]
        return SceneGuidance(
            scene_revision=state.state_revision,
            scene_summary=state.scene_summary,
            response_objective=objective,
            tone=tones[state.atmosphere],
            scope=pace_limits[state.pace],
            must_address=must_address,
            avoid=avoid,
            technique=technique,
            meme_policy=meme_policy,
            confidence=state.confidence,
            degraded=state.degraded or bool(unique_reasons),
            degradation_reasons=unique_reasons,
            expires_at=max(state.expires_at, now + 5),
        )

    def _select_technique(
        self,
        state: LiveSceneState,
        evidence: SceneEvidence | None,
        degradation_reasons: list[str],
    ) -> TechniqueSelection | None:
        if self._technique_retriever is None:
            return None
        try:
            selected = self._technique_retriever.select(
                state.model_copy(deep=True),
                evidence.model_copy(deep=True) if evidence is not None else None,
            )
        except Exception:
            degradation_reasons.append("technique_retrieval_error")
            return None
        if selected is None:
            degradation_reasons.append("technique_rag_empty")
        return selected

    def _select_meme(
        self,
        state: LiveSceneState,
        evidence: SceneEvidence | None,
        degradation_reasons: list[str],
    ) -> MemePolicy:
        if self._meme_retriever is not None:
            try:
                selected = self._meme_retriever.select(
                    state.model_copy(deep=True),
                    evidence.model_copy(deep=True) if evidence is not None else None,
                )
            except Exception:
                degradation_reasons.append("meme_retrieval_error")
            else:
                if selected is not None:
                    return selected
                degradation_reasons.append("meme_rag_empty")
        if any(meme.lifecycle in {"overused", "cooldown"} for meme in state.meme_states):
            return MemePolicy(action="avoid", instruction="Let the saturated meme rest.")
        return MemePolicy()
