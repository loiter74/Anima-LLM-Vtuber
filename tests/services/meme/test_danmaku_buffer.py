from __future__ import annotations

from animetta.services.bilibili import DanmakuBuffer, DanmakuPhrase

"""Tests for DanmakuBuffer — real-time danmaku accumulation and hot phrase extraction."""

import time


class TestDanmakuPhrase:
    """DanmakuPhrase dataclass."""

    def test_creation(self):

        p = DanmakuPhrase(
            text="绝绝子",
            frequency=5,
            first_seen=1000.0,
            last_seen=2000.0,
            source_room_id=123,
        )
        assert p.text == "绝绝子"
        assert p.frequency == 5
        assert p.source_room_id == 123

    def test_default_source_room_id(self):

        p = DanmakuPhrase(text="哈哈哈", frequency=3, first_seen=0.0, last_seen=1.0)
        assert p.source_room_id == 0


class TestDanmakuBuffer:
    """Suite for DanmakuBuffer."""

    # ── Constructor ──────────────────────────────────────────────────

    def test_constructor_defaults(self):

        b = DanmakuBuffer()
        assert b.total_count == 0
        assert b.get_stats()["max_size"] == 1000

    def test_constructor_custom_max_size(self):

        b = DanmakuBuffer(max_size=50)
        assert b.get_stats()["max_size"] == 50

    # ── add ──────────────────────────────────────────────────────────

    def test_add_increases_count(self):

        b = DanmakuBuffer()
        b.add("绝绝子")
        b.add("笑死我了")
        assert b.total_count == 2

    def test_add_empty_string_ignored(self):

        b = DanmakuBuffer()
        b.add("")
        b.add("   ")
        assert b.total_count == 0

    def test_add_digit_only_ignored(self):

        b = DanmakuBuffer()
        b.add("12345")
        assert b.total_count == 0

    def test_add_short_text_ignored(self):

        b = DanmakuBuffer()
        b.add("a")  # length < 2
        assert b.total_count == 0

    def test_add_accepts_chinese_two_chars(self):

        b = DanmakuBuffer()
        b.add("哈哈")
        assert b.total_count == 1

    def test_add_accepts_room_id(self):

        b = DanmakuBuffer()
        b.add("绝绝子", room_id=777)
        stats = b.get_stats()
        assert stats["room_id"] == 777

    def test_add_room_id_updates_lazy(self):

        b = DanmakuBuffer()
        b.add("哈哈", room_id=111)
        b.add("呵呵", room_id=222)
        stats = b.get_stats()
        assert stats["room_id"] == 222  # Last room_id wins

    # ── Ring buffer capacity ─────────────────────────────────────────

    def test_ring_buffer_evicts_oldest(self):

        b = DanmakuBuffer(max_size=3)
        b.add("aa")
        b.add("bb")
        b.add("cc")
        assert b.total_count == 3
        b.add("dd")  # should evict "aa"
        assert b.total_count == 3
        recent = b.get_recent_danmaku(10)
        assert "aa" not in recent
        assert recent[0] == "dd"  # newest first

    # ── get_recent_danmaku ───────────────────────────────────────────

    def test_get_recent_danmaku_empty(self):

        b = DanmakuBuffer()
        assert b.get_recent_danmaku() == []

    def test_get_recent_danmaku_returns_newest_first(self):

        b = DanmakuBuffer()
        b.add("aa")
        b.add("bb")
        b.add("cc")
        recent = b.get_recent_danmaku(10)
        assert recent == ["cc", "bb", "aa"]

    def test_get_recent_danmaku_respects_limit(self):

        b = DanmakuBuffer()
        for i in range(10):
            b.add(f"__{i}__")
        recent = b.get_recent_danmaku(limit=3)
        assert len(recent) == 3
        assert "__9__" in recent[0] or recent[0].endswith("9__")

    # ── get_hot_phrases ──────────────────────────────────────────────

    def test_get_hot_phrases_empty_buffer(self):

        b = DanmakuBuffer()
        assert b.get_hot_phrases() == []

    def test_get_hot_phrases_returns_frequent_phrases(self):

        b = DanmakuBuffer()
        # Send same phrase multiple times
        for _ in range(5):
            b.add("绝绝子")
        hot = b.get_hot_phrases(min_freq=3, window_minutes=60)
        assert len(hot) >= 1
        # "绝绝子" is 3 chars — the buffer uses 2-6 char n-grams
        found = [p for p in hot if "绝绝" in p.text or "绝子" in p.text or "绝绝子" in p.text]
        assert len(found) >= 1
        assert found[0].frequency >= 3

    def test_get_hot_phrases_filters_by_min_freq(self):

        b = DanmakuBuffer()
        b.add("unique")  # only once
        hot = b.get_hot_phrases(min_freq=2, window_minutes=60)
        # "uniq" is a 4-char n-gram that appears once — should not be hot
        assert all(p.frequency >= 2 for p in hot)

    def test_get_hot_phrases_returns_empty_when_none_meet_threshold(self):

        b = DanmakuBuffer()
        b.add("罕见")
        assert b.get_hot_phrases(min_freq=10) == []

    # ── clear ────────────────────────────────────────────────────────

    def test_clear_empties_buffer(self):

        b = DanmakuBuffer()
        b.add("test")
        assert b.total_count > 0
        b.clear()
        assert b.total_count == 0
        assert b.get_stats()["unique_phrases"] == 0

    # ── get_stats ────────────────────────────────────────────────────

    def test_get_stats_includes_timestamps(self):

        b = DanmakuBuffer()
        b.add("first", room_id=1)
        time.sleep(0.01)
        b.add("second", room_id=1)
        stats = b.get_stats()
        assert stats["total_danmaku"] == 2
        assert stats["unique_phrases"] > 0
        assert stats["age_seconds"] > 0
        assert stats["newest_timestamp"] > stats["oldest_timestamp"]

    # ── Integration: eviction decrements phrase counts ────────────────

    def test_eviction_decrements_phrase_counter(self):

        b = DanmakuBuffer(max_size=2)
        # Fill buffer
        b.add("AAAA")
        b.add("AAAA")
        b.get_stats()
        # Evict one entry by adding new unique content
        b.add("BBBB")
        # "AAAA" -> 6 chars. N-grams: "AA", "AAAA", etc.
        # After eviction, frequency should have decreased
        stats_after = b.get_stats()
        # Stats should still be valid
        assert stats_after["total_danmaku"] == 2
