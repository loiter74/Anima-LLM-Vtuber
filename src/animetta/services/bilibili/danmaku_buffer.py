"""DanmakuBuffer — 实时弹幕缓冲区，为 MemeCollector 提供弹幕数据源.

Collects real-time danmaku from DanmakuService, maintains a ring buffer
of recent messages, and provides frequency-based hot phrase extraction for the
meme collection pipeline.

Typical usage:
    buffer = DanmakuBuffer(max_size=1000)
    danmaku_service.set_buffer(buffer)

    # Later, in the collector:
    hot_phrases = buffer.get_hot_phrases(min_freq=3, window_minutes=30)
"""

from __future__ import annotations

import logging
import time
from collections import Counter

from .models import DanmakuPhrase
from .text_utils import STOPWORDS

logger = logging.getLogger(__name__)

# Minimum text length to consider a danmaku meaningful
_MIN_DANMAKU_LENGTH = 2


class DanmakuBuffer:
    """Ring buffer that accumulates real-time danmaku and tracks hot phrases.

    Maintains:
    - A fixed-size ring buffer of raw danmaku texts (FIFO, max_size limit)
    - An online frequency table for phrase extraction

    The buffer is designed for the meme collection pipeline: it provides
    time-windowed hot phrase queries. Data is ephemeral — nothing is persisted.
    """

    def __init__(self, max_size: int = 1000):
        """
        Args:
            max_size: Maximum number of danmaku entries in the ring buffer.
        """
        self._max_size = max_size
        self._buffer: list[str] = []  # ring buffer (list used as circular with trim)
        self._timestamps: list[float] = []  # parallel timestamp list
        self._phrase_counter: Counter = Counter()  # phrase -> total count
        self._phrase_first_seen: dict[str, float] = {}  # phrase -> first timestamp
        self._phrase_last_seen: dict[str, float] = {}  # phrase -> last timestamp
        self._room_id: int = 0

    # ── Public API ──────────────────────────────────────────────────────

    def add(self, text: str, room_id: int = 0) -> None:
        """Push a danmaku message into the buffer.

        Args:
            text: Raw danmaku text content.
            room_id: Optional source room identifier.
        """
        # Filter invalid entries
        if not text or not isinstance(text, str):
            return
        cleaned = text.strip()
        if len(cleaned) < _MIN_DANMAKU_LENGTH:
            return
        if cleaned.isdigit():
            return

        now = time.time()
        self._room_id = room_id or self._room_id

        # Ring buffer: trim oldest when full
        if len(self._buffer) >= self._max_size:
            oldest = self._buffer.pop(0)
            self._timestamps.pop(0)
            self._decrement_phrase(oldest)

        self._buffer.append(cleaned)
        self._timestamps.append(now)

        # Update phrase frequency — use 2-6 char substrings as phrases
        self._update_phrases(cleaned, now)

    def get_hot_phrases(
        self,
        min_freq: int = 3,
        window_minutes: int = 30,
    ) -> list[DanmakuPhrase]:
        """Return phrases that meet frequency and time-window criteria.

        Only phrases whose last_seen falls within the time window are included.
        Results are sorted by frequency descending.

        Args:
            min_freq: Minimum occurrence count to be considered "hot".
            window_minutes: Look-back window in minutes.

        Returns:
            List of DanmakuPhrase matching the criteria, sorted by frequency.
        """
        now = time.time()
        cutoff = now - window_minutes * 60

        result: list[DanmakuPhrase] = []
        for phrase, count in self._phrase_counter.items():
            last = self._phrase_last_seen.get(phrase, 0)
            if last < cutoff:
                continue
            if count < min_freq:
                continue
            # Also require the phrase is actually still in the buffer
            if count <= 0:
                continue
            result.append(
                DanmakuPhrase(
                    text=phrase,
                    frequency=count,
                    first_seen=self._phrase_first_seen.get(phrase, now),
                    last_seen=last,
                    source_room_id=self._room_id,
                )
            )

        result.sort(key=lambda p: p.frequency, reverse=True)
        return result

    def get_recent_danmaku(self, limit: int = 100) -> list[str]:
        """Return the most recent danmaku texts.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of recent danmaku text strings, newest first.
        """
        if not self._buffer:
            return []
        return list(reversed(self._buffer))[:limit]

    def get_stats(self) -> dict:
        """Return buffer statistics for monitoring/debugging."""
        now = time.time()
        return {
            "total_danmaku": len(self._buffer),
            "unique_phrases": len(self._phrase_counter),
            "max_size": self._max_size,
            "room_id": self._room_id,
            "oldest_timestamp": self._timestamps[0] if self._timestamps else None,
            "newest_timestamp": self._timestamps[-1] if self._timestamps else None,
            "age_seconds": (now - self._timestamps[0]) if self._timestamps else 0,
        }

    @property
    def total_count(self) -> int:
        """Number of danmaku currently in the buffer."""
        return len(self._buffer)

    def clear(self) -> None:
        """Clear all data from the buffer."""
        self._buffer.clear()
        self._timestamps.clear()
        self._phrase_counter.clear()
        self._phrase_first_seen.clear()
        self._phrase_last_seen.clear()
        logger.debug("[DanmakuBuffer] Buffer cleared")

    # ── Internal helpers ────────────────────────────────────────────────

    def _update_phrases(self, text: str, now: float) -> None:
        """Extract n-gram phrases from text and update frequency table.

        Uses simple character n-grams for Chinese text (2-6 chars).
        Filters out stopwords and pure punctuation/digit phrases.
        """
        # Simple sliding window for Chinese text
        chars = list(text)
        ngram_set = set()
        for n in range(2, min(7, len(chars) + 1)):
            for i in range(len(chars) - n + 1):
                phrase = "".join(chars[i : i + n])
                # Filter junk: skip if all digits/punctuation/whitespace
                if not phrase.strip():
                    continue
                if phrase.isdigit():
                    continue
                if phrase in STOPWORDS:
                    continue
                ngram_set.add(phrase)

        for phrase in ngram_set:
            self._phrase_counter[phrase] += 1
            if phrase not in self._phrase_first_seen:
                self._phrase_first_seen[phrase] = now
            self._phrase_last_seen[phrase] = now

    def _decrement_phrase(self, text: str) -> None:
        """Decrement frequency counts when a danmaku is evicted from the buffer."""
        chars = list(text)
        for n in range(2, min(7, len(chars) + 1)):
            for i in range(len(chars) - n + 1):
                phrase = "".join(chars[i : i + n])
                if phrase in self._phrase_counter:
                    self._phrase_counter[phrase] -= 1
                    if self._phrase_counter[phrase] <= 0:
                        del self._phrase_counter[phrase]
                        self._phrase_first_seen.pop(phrase, None)
                        self._phrase_last_seen.pop(phrase, None)
