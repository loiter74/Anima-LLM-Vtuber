"""Deterministic admission policy for costly AI danmaku replies."""

from __future__ import annotations

import random
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from animetta.config import ReplyPolicyConfig

from .models import DanmakuMessage

_QUESTION_PATTERN = re.compile(
    r"[?？]|(?:为什么|怎么|怎样|什么|谁|哪里|哪儿|何时|多少|吗|呢|能否|可不可以)",
)


class ReplyPriority(IntEnum):
    """Lower numeric values are processed first."""

    SUPER_CHAT = 0
    GIFT = 1
    QUESTION = 2
    ORDINARY = 3


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Result of evaluating one raw danmaku for AI work."""

    admitted: bool
    priority: ReplyPriority | None = None
    reason: str | None = None


class ReplyAdmissionController:
    """Apply freshness, dedupe, cooldown, sampling, and token-budget rules."""

    def __init__(
        self,
        config: ReplyPolicyConfig,
        *,
        clock: Callable[[], float] = time.time,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._config = config
        self._clock = clock
        self._random_source = random_source
        self._tokens = float(config.max_replies_per_minute)
        self._last_refill = clock()
        self._duplicate_seen_at: dict[str, float] = {}
        self._user_admitted_at: dict[str, float] = {}

        self.admitted_count = 0
        self.dropped: Counter[str] = Counter()

    def decide(self, message: DanmakuMessage) -> AdmissionDecision:
        """Return a deterministic admission decision for one raw message."""
        now = self._clock()
        if not self._config.enabled:
            return self._reject("disabled")

        text = message.text.strip()
        if not text:
            return self._reject("invalid")
        priority = self._priority_for(message, text)
        if priority is None:
            return self._reject("message_type_disabled")
        if self._config.mode == "exhaustive":
            self.admitted_count += 1
            return AdmissionDecision(admitted=True, priority=priority)
        if now - message.timestamp > self._config.max_message_age_seconds:
            return self._reject("expired")
        if (
            priority is ReplyPriority.ORDINARY
            and self._random_source() >= self._config.ordinary_sample_rate
        ):
            return self._reject("not_sampled")

        normalized = " ".join(text.casefold().split())
        duplicate_at = self._duplicate_seen_at.get(normalized)
        if duplicate_at is not None and now - duplicate_at < self._config.duplicate_window_seconds:
            return self._reject("duplicate")

        user_key = self._user_key(message)
        user_admitted_at = self._user_admitted_at.get(user_key)
        if (
            user_admitted_at is not None
            and now - user_admitted_at < self._config.per_user_cooldown_seconds
        ):
            return self._reject("user_cooldown")

        self._refill(now)
        if self._tokens < 1.0:
            return self._reject("rate_limited")

        self._tokens -= 1.0
        self._duplicate_seen_at[normalized] = now
        self._user_admitted_at[user_key] = now
        self._prune_history(now)
        self.admitted_count += 1
        return AdmissionDecision(admitted=True, priority=priority)

    def _priority_for(
        self,
        message: DanmakuMessage,
        text: str,
    ) -> ReplyPriority | None:
        if message.is_super_chat:
            return ReplyPriority.SUPER_CHAT if self._config.reply_to_super_chat else None
        if message.is_gift:
            return ReplyPriority.GIFT if self._config.reply_to_gifts else None
        if _QUESTION_PATTERN.search(text):
            return ReplyPriority.QUESTION
        return ReplyPriority.ORDINARY

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        rate_per_second = self._config.max_replies_per_minute / 60.0
        self._tokens = min(
            float(self._config.max_replies_per_minute),
            self._tokens + elapsed * rate_per_second,
        )
        self._last_refill = now

    def _prune_history(self, now: float) -> None:
        duplicate_cutoff = now - self._config.duplicate_window_seconds
        cooldown_cutoff = now - self._config.per_user_cooldown_seconds
        self._duplicate_seen_at = {
            text: seen_at
            for text, seen_at in self._duplicate_seen_at.items()
            if seen_at >= duplicate_cutoff
        }
        self._user_admitted_at = {
            user: seen_at
            for user, seen_at in self._user_admitted_at.items()
            if seen_at >= cooldown_cutoff
        }

    @staticmethod
    def _user_key(message: DanmakuMessage) -> str:
        if message.user_id:
            return f"id:{message.user_id}"
        return f"name:{message.user_name.casefold()}"

    def _reject(self, reason: str) -> AdmissionDecision:
        self.dropped[reason] += 1
        return AdmissionDecision(admitted=False, reason=reason)
