"""MemeCollector — 从 B 站热门视频采集梗候选.

Uses bilibili-api-python (via .api) to fetch trending videos and comments,
then uses LLM to identify emerging meme (梗) patterns.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from .api import fetch_comments, fetch_live_danmaku, fetch_trending_videos, fetch_video_danmaku
from .meme_prompts import (
    MEME_IDENTIFY_SYSTEM_PROMPT,
    get_meme_identify_user_prompt,
)
from .meme_prompts import (
    MEME_IDENTIFY_USER_PROMPT as MEME_IDENTIFY_USER_PROMPT,
)
from .meme_utils import build_candidates, extract_semantic_phrases, parse_llm_json
from .models import CollectedComment, CollectedDanmaku, CollectedVideo, MemeCandidate
from .text_utils import STOPWORDS, extract_title_phrases, parse_tags

logger = logging.getLogger(__name__)

__all__ = [
    "MEME_IDENTIFY_SYSTEM_PROMPT",
    "MEME_IDENTIFY_USER_PROMPT",
    "MemeCollector",
]


class MemeCollector:
    """从 B 站热门视频采集梗候选。

    采集流程：
    1. 使用 bilibili-api-python 搜索热门视频
    2. 提取标题、标签、高赞评论
    3. LLM 分析识别梗候选模式
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        config: dict[str, Any] | None = None,
        danmaku_buffer: Any | None = None,
    ):
        """
        Args:
            llm_client: LLM client with .chat(messages, **kwargs) method.
            config: Optional config dict. Keys:
                - max_videos: max videos to collect (default 50)
                - max_comments_per_video: max comments per video (default 50)
                - min_comment_likes: minimum likes for comment inclusion (default 2)
                - request_delay: delay between API requests in seconds (default 0.3)
                - search_keyword: keyword for trending search (default "")
                - request_timeout: overall timeout in seconds (default 120)
                - comment_timeout: per-comment timeout in seconds (default 15)
                - room_id: Bilibili live room ID for danmaku collection (default 0)
                - concurrency: max parallel requests for comment fetching (default 5)
            danmaku_buffer: Optional DanmakuBuffer instance for real-time danmaku.
        """
        self._llm = llm_client
        self._config = config or {}
        self._max_videos = self._config.get("max_videos", 50)
        self._max_comments_per_video = self._config.get("max_comments_per_video", 50)
        self._min_comment_likes = self._config.get("min_comment_likes", 2)
        self._request_delay = self._config.get("request_delay", 0.3)
        self._search_keyword = self._config.get("search_keyword", "")
        self._request_timeout = self._config.get("request_timeout", 120)
        self._comment_timeout = self._config.get("comment_timeout", 15)
        self._room_id = self._config.get("room_id", 0)
        self._concurrency = self._config.get("concurrency", 5)
        self._danmaku_buffer = danmaku_buffer

    # ── Public API ──────────────────────────────────────────────────────

    async def collect(self) -> list[MemeCandidate]:
        """Run the full collection pipeline: videos → comments → meme identification."""
        logger.info(
            "[MemeCollector] Starting collection "
            "(max_videos=%d, max_comments=%d, timeout=%ds)",
            self._max_videos,
            self._max_comments_per_video,
            self._request_timeout,
        )

        try:
            return await asyncio.wait_for(
                self._collect_impl(),
                timeout=self._request_timeout,
            )
        except TimeoutError:
            logger.warning(
                "[MemeCollector] Collection timed out after %ds — returning partial results",
                self._request_timeout,
            )
            return []
        except Exception as e:
            logger.error("[MemeCollector] Collection failed: %s", e, exc_info=True)
            return []

    async def collect_danmaku_for_training(
        self,
        max_danmaku: int = 1000,
        min_length: int = 5,
        max_length: int = 20,
        meme_keywords: list[str] | None = None,
    ) -> list[CollectedDanmaku]:
        """Collect danmaku specifically for training data."""
        logger.info(
            "[MemeCollector] Starting danmaku collection for training "
            "(max_danmaku=%d, length=%d-%d, keywords=%s)",
            max_danmaku, min_length, max_length, meme_keywords,
        )

        try:
            return await asyncio.wait_for(
                self._collect_danmaku_impl(max_danmaku, min_length, max_length, meme_keywords),
                timeout=self._request_timeout,
            )
        except TimeoutError:
            logger.warning(
                "[MemeCollector] Danmaku collection timed out after %ds — returning partial results",
                self._request_timeout,
            )
            return []
        except Exception as e:
            logger.error("[MemeCollector] Danmaku collection failed: %s", e, exc_info=True)
            return []

    # ── Internal collection ─────────────────────────────────────────────

    async def _collect_danmaku_impl(
        self, max_danmaku: int, min_length: int, max_length: int,
        meme_keywords: list[str] | None,
    ) -> list[CollectedDanmaku]:
        """Internal danmaku collection implementation."""
        try:
            videos = await self._fetch_trending_videos()
            if not videos:
                return []

            all_danmaku: list[CollectedDanmaku] = []
            semaphore = asyncio.Semaphore(self._concurrency)

            async def fetch_one(video: CollectedVideo) -> list[CollectedDanmaku]:
                async with semaphore:
                    await asyncio.sleep(self._request_delay)
                    return await self._fetch_video_danmaku(video)

            results = await asyncio.gather(*[fetch_one(v) for v in videos], return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    logger.warning("[MemeCollector] Danmaku fetch error: %s", r)
                    continue
                all_danmaku.extend(r)

            return self._filter_danmaku_for_training(
                all_danmaku, min_length, max_length, meme_keywords, max_danmaku,
            )
        except Exception as e:
            logger.error("[MemeCollector] Danmaku collection failed: %s", e, exc_info=True)
            return []

    async def _collect_impl(self) -> list[MemeCandidate]:
        """Internal collection implementation."""
        try:
            videos_task = asyncio.create_task(self._fetch_trending_videos())
            danmaku_task = asyncio.create_task(self._fetch_danmaku_phrases())

            videos = await videos_task
            danmaku_phrases = await danmaku_task

            if not videos:
                if danmaku_phrases:
                    return self._heuristic_danmaku_only(danmaku_phrases)
                return []

            all_comments: dict[str, list[CollectedComment]] = {}
            semaphore = asyncio.Semaphore(self._concurrency)

            async def fetch_one(video: CollectedVideo) -> tuple[str, list[CollectedComment]]:
                async with semaphore:
                    await asyncio.sleep(self._request_delay)
                    comments = await self._fetch_comments(video.bvid)
                    return video.bvid, comments

            results = await asyncio.gather(*[fetch_one(v) for v in videos], return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    continue
                bvid, comments = r
                if comments:
                    all_comments[bvid] = comments

            return await self._identify_meme_candidates(videos, all_comments, danmaku_phrases)
        except Exception as e:
            logger.error("[MemeCollector] Collection failed: %s", e, exc_info=True)
            return []

    # ── Fetching ────────────────────────────────────────────────────────

    async def _fetch_trending_videos(self) -> list[CollectedVideo]:
        raw_items = await fetch_trending_videos(
            max_videos=self._max_videos, search_keyword=self._search_keyword,
        )
        videos: list[CollectedVideo] = []
        for item in raw_items[: self._max_videos]:
            try:
                title = item.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
                description = item.get("desc", item.get("description", ""))
                description = description[:200] if isinstance(description, str) else ""
                stat = item.get("stat")
                if isinstance(stat, dict):
                    view_count = stat.get("view", 0)
                    danmaku_count = stat.get("danmaku", 0)
                    reply_count = stat.get("reply", 0)
                else:
                    view_count = item.get("play", 0)
                    danmaku_count = item.get("video_review", 0)
                    reply_count = item.get("review", 0)
                video = CollectedVideo(
                    bvid=item.get("bvid", ""), title=title, description=description,
                    tags=parse_tags(item.get("tag", "")),
                    view_count=view_count, danmaku_count=danmaku_count, reply_count=reply_count,
                )
                if video.bvid:
                    videos.append(video)
            except Exception:
                continue
        return videos

    async def _fetch_comments(self, bvid: str) -> list[CollectedComment]:
        raw_comments = await fetch_comments(
            bvid=bvid, max_count=self._max_comments_per_video,
            min_likes=self._min_comment_likes, timeout=self._comment_timeout,
        )
        return [
            CollectedComment(
                content=c.get("content", ""), likes=c.get("likes", 0),
                replies=c.get("replies", 0), publish_time=c.get("publish_time", ""),
            )
            for c in raw_comments
        ]

    async def _fetch_danmaku_phrases(self) -> list[str]:
        phrases: list[str] = []
        seen: set[str] = set()
        if self._danmaku_buffer:
            try:
                hot = self._danmaku_buffer.get_hot_phrases(min_freq=3, window_minutes=30)
                for p in hot:
                    text = p.text.strip()
                    if text and text not in seen:
                        phrases.append(text)
                        seen.add(text)
            except Exception as e:
                logger.warning("[MemeCollector] DanmakuBuffer query failed: %s", e)
        if self._room_id:
            try:
                historical = await fetch_live_danmaku(
                    room_id=self._room_id, limit=100, timeout=self._comment_timeout,
                )
                for text in historical:
                    if text and text not in seen:
                        phrases.append(text)
                        seen.add(text)
            except Exception as e:
                logger.warning("[MemeCollector] Historical danmaku fetch failed: %s", e)
        return phrases

    async def _fetch_video_danmaku(self, video: CollectedVideo) -> list[CollectedDanmaku]:
        try:
            raw = await fetch_video_danmaku(bvid=video.bvid, max_count=100, timeout=self._comment_timeout)
            return [
                CollectedDanmaku(
                    content=d.get("content", ""), source_video=video.bvid, source_type="video",
                    likes=d.get("likes", 0), publish_time=d.get("publish_time", ""),
                    mode=d.get("mode", 1), color=d.get("color", 16777215),
                )
                for d in raw if d.get("content")
            ]
        except Exception as e:
            logger.warning("[MemeCollector] Failed to fetch danmaku for %s: %s", video.bvid, e)
            return []

    def _filter_danmaku_for_training(
        self, danmaku_list: list[CollectedDanmaku], min_length: int, max_length: int,
        meme_keywords: list[str] | None, max_count: int,
    ) -> list[CollectedDanmaku]:
        filtered = [d for d in danmaku_list if min_length <= len(d.content) <= max_length]
        if meme_keywords:
            keyword_filtered = []
            for d in filtered:
                for kw in meme_keywords:
                    if kw.lower() in d.content.lower():
                        d.is_meme = True
                        d.meme_type = kw
                        keyword_filtered.append(d)
                        break
            filtered = keyword_filtered
        seen: set[str] = set()
        unique: list[CollectedDanmaku] = []
        for d in filtered:
            if d.content not in seen:
                seen.add(d.content)
                unique.append(d)
        for d in unique:
            score = 0.0
            if d.mode in (1, 2, 3):
                score += 0.3
            if d.likes > 0:
                score += min(d.likes / 100.0, 0.4)
            if d.is_meme:
                score += 0.3
            if 8 <= len(d.content) <= 15:
                score += 0.2
            d.quality_score = min(score, 1.0)
        unique.sort(key=lambda x: x.quality_score, reverse=True)
        return unique[:max_count]

    # ── Meme identification ─────────────────────────────────────────────

    async def _identify_meme_candidates(
        self, videos: list[CollectedVideo],
        comments: dict[str, list[CollectedComment]],
        danmaku_phrases: list[str] | None = None,
    ) -> list[MemeCandidate]:
        if not self._llm:
            return self._heuristic_identify(videos, comments, danmaku_phrases)

        video_lines = [
            f"视频: {v.title}\n标签: {', '.join(v.tags) if v.tags else '无'}\n"
            f"播放: {v.view_count}, 弹幕: {v.danmaku_count}"
            for v in videos
        ]
        comment_lines = [
            f"[{bvid}] {c.likes}: {c.content}"
            for bvid, clist in comments.items() for c in clist[:10]
        ]
        combined = (
            f"=== 热门视频 ===\n\n{''.join(chr(10) + line for line in video_lines[:20])}\n\n"
            f"=== 高赞评论 ===\n\n{''.join(chr(10) + line for line in comment_lines[:50])}"
        )
        danmaku_section = ""
        if danmaku_phrases:
            danmaku_section = "=== 弹幕高频短语 ===\n\n" + "\n".join(
                f"  - {phrase}" for phrase in danmaku_phrases[:30]
            )

        llm_method = None
        if hasattr(self._llm, "chat_messages"):
            llm_method = "chat_messages"
        elif hasattr(self._llm, "chat"):
            llm_method = "chat"

        if not llm_method:
            return self._heuristic_identify(videos, comments, danmaku_phrases)

        try:
            if llm_method == "chat_messages":
                result = await self._llm.chat_messages(
                    messages=[
                        {"role": "system", "content": MEME_IDENTIFY_SYSTEM_PROMPT},
                        {"role": "user", "content": get_meme_identify_user_prompt(
                            video_data=combined, danmaku_section=danmaku_section,
                        )},
                    ],
                    response_format={"type": "json_object"},
                )
            else:
                user_text = MEME_IDENTIFY_SYSTEM_PROMPT + "\n\n" + get_meme_identify_user_prompt(
                    video_data=combined, danmaku_section=danmaku_section,
                )
                result = await self._llm.chat(
                    messages=[{"role": "user", "content": user_text}],
                    response_format={"type": "json_object"},
                )
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            parsed = parse_llm_json(content)
            return build_candidates(parsed, videos)
        except Exception as e:
            logger.warning("[MemeCollector] LLM identification failed: %s", e)
            return self._heuristic_identify(videos, comments, danmaku_phrases)

    def _heuristic_identify(
        self, videos: list[CollectedVideo],
        comments: dict[str, list[CollectedComment]],
        danmaku_phrases: list[str] | None = None,
    ) -> list[MemeCandidate]:
        candidates: list[MemeCandidate] = []
        seen: set[str] = set()

        tag_counts: dict[str, int] = {}
        for v in videos:
            for tag in v.tags:
                t = tag.strip()
                if len(t) >= 2 and t not in STOPWORDS:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        for phrase, count in tag_counts.items():
            if count >= 2 and len(phrase) <= 15 and phrase not in seen:
                seen.add(phrase)
                candidates.append(MemeCandidate(
                    text=phrase, context_hint=f"出现在 {count} 个热门视频标签中",
                    frequency=count, tags=["bilibili", "trending", "tag"],
                ))

        title_phrases: Counter[str] = Counter()
        for v in videos:
            for phrase in extract_title_phrases(v.title):
                if phrase not in STOPWORDS and len(phrase) >= 2:
                    title_phrases[phrase] += 1
        for phrase, count in title_phrases.most_common(10):
            if count >= 2 and phrase not in seen:
                seen.add(phrase)
                candidates.append(MemeCandidate(
                    text=phrase, context_hint=f"出现在 {count} 个视频标题中的热门短语",
                    frequency=count, tags=["bilibili", "trending", "title"],
                ))

        all_comments_text = [c.content for clist in comments.values() for c in clist[:5]]
        if all_comments_text:
            try:
                for phrase, count in extract_semantic_phrases(all_comments_text, top_k=10):
                    if count >= 2 and phrase not in seen:
                        seen.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase, context_hint=f"在热门评论中出现 {count} 次",
                            frequency=count, tags=["bilibili", "trending", "comment"],
                        ))
            except ImportError:
                pass

        if danmaku_phrases:
            try:
                for phrase, count in extract_semantic_phrases(danmaku_phrases, top_k=20):
                    if phrase not in seen and phrase not in STOPWORDS:
                        seen.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase, context_hint=f"弹幕高频短语，出现 {count} 次以上",
                            frequency=count, tags=["bilibili", "danmaku", "hot"],
                        ))
            except ImportError:
                freq = Counter(danmaku_phrases)
                for phrase, count in freq.most_common(15):
                    if phrase not in seen and phrase not in STOPWORDS and len(phrase) >= 2:
                        seen.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase, context_hint=f"弹幕中出现 {count} 次",
                            frequency=count, tags=["bilibili", "danmaku", "hot"],
                        ))

        return candidates[:15]

    def _heuristic_danmaku_only(self, danmaku_phrases: list[str]) -> list[MemeCandidate]:
        candidates: list[MemeCandidate] = []
        seen: set[str] = set()
        try:
            for phrase, count in extract_semantic_phrases(danmaku_phrases, top_k=15):
                if phrase not in seen and phrase not in STOPWORDS and len(phrase) >= 2:
                    seen.add(phrase)
                    candidates.append(MemeCandidate(
                        text=phrase, context_hint="弹幕高频短语",
                        frequency=count, tags=["bilibili", "danmaku", "hot"],
                    ))
        except ImportError:
            freq = Counter(danmaku_phrases)
            for phrase, count in freq.most_common(10):
                if phrase not in seen and phrase not in STOPWORDS and len(phrase) >= 2:
                    seen.add(phrase)
                    candidates.append(MemeCandidate(
                        text=phrase, context_hint="弹幕高频短语",
                        frequency=count, tags=["bilibili", "danmaku", "hot"],
                    ))
        return candidates[:10]

    @staticmethod
    def _extract_semantic_phrases(
        texts: list[str],
        top_k: int = 20,
    ) -> list[tuple[str, int]]:
        """Compatibility wrapper for extracted semantic phrase utility."""
        return extract_semantic_phrases(texts, top_k=top_k)

    @staticmethod
    def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
        """Compatibility wrapper for extracted LLM JSON parser."""
        return parse_llm_json(raw)

    @staticmethod
    def _build_candidates(
        parsed: list[dict[str, Any]],
        videos: list[CollectedVideo],
    ) -> list[MemeCandidate]:
        """Compatibility wrapper for extracted candidate builder."""
        return build_candidates(parsed, videos)
