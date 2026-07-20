"""Deterministic rule evidence for cached scene reflection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from .models import NormalizedSceneEvent, RuleHit, SceneEvidence, SceneMetrics


class SceneEvidenceBuilder:
    """Build bounded model evidence from normalized room events."""

    def build(
        self,
        events: Sequence[NormalizedSceneEvent],
        *,
        after_event_seq: int = 0,
    ) -> SceneEvidence | None:
        selected = [event for event in events if event.event_seq > after_event_seq]
        if not selected:
            return None

        first = selected[0]
        last = selected[-1]
        duration = max(last.occurred_at - first.occurred_at, 1.0)
        danmaku = [event for event in selected if event.event_type == "danmaku"]
        actors = {event.actor_id for event in selected if event.actor_id}
        texts = [event.text.strip() for event in danmaku if event.text.strip()]
        text_counts = Counter(texts)
        repeated_count = max(text_counts.values(), default=0)
        repeat_ratio = repeated_count / len(texts) if texts else 0.0
        critical_count = sum(event.critical for event in selected)

        metrics = SceneMetrics(
            event_count=len(selected),
            danmaku_per_minute=len(danmaku) * 60 / duration,
            unique_users=len(actors),
            repeat_ratio=repeat_ratio,
            critical_event_count=critical_count,
        )
        rule_hits: list[RuleHit] = []
        if repeated_count >= 3:
            phrase, count = text_counts.most_common(1)[0]
            rule_hits.append(
                RuleHit(
                    rule="repeated_phrase",
                    strength=min(1.0, count / 5),
                    subject=phrase[:80],
                )
            )
        if critical_count:
            rule_hits.append(
                RuleHit(
                    rule="critical_event",
                    strength=min(1.0, 0.5 + critical_count / 4),
                )
            )
        if metrics.danmaku_per_minute >= 90:
            rule_hits.append(
                RuleHit(
                    rule="message_rate_spike",
                    strength=min(1.0, metrics.danmaku_per_minute / 240),
                )
            )

        representatives = self._representative_events(selected)
        return SceneEvidence(
            session_id=first.session_id,
            room_id=first.room_id,
            generation_id=first.generation_id,
            from_event_seq=first.event_seq,
            to_event_seq=last.event_seq,
            duration_seconds=duration,
            metrics=metrics,
            rule_hits=rule_hits[:12],
            representative_events=representatives,
        )

    @staticmethod
    def _representative_events(
        events: Sequence[NormalizedSceneEvent],
    ) -> list[NormalizedSceneEvent]:
        if len(events) <= 8:
            return list(events)
        critical = [event for event in events if event.critical][-3:]
        recent = list(events[-8:])
        combined = {event.event_seq: event for event in [*critical, *recent]}
        return [combined[key] for key in sorted(combined)][-8:]
