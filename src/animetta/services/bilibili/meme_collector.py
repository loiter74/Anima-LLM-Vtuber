"""MemeCollector — 从 B 站热门视频采集梗候选.

Uses bilibili-api-python (via .api) to fetch trending videos and comments,
then uses LLM to identify emerging meme (梗) patterns.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from typing import Any

from .api import fetch_comments, fetch_live_danmaku, fetch_trending_videos, fetch_video_danmaku
from .models import CollectedComment, CollectedDanmaku, CollectedVideo, MemeCandidate
from .text_utils import STOPWORDS, extract_title_phrases, parse_tags

logger = logging.getLogger(__name__)


# ── LLM Prompt for meme candidate identification ─────────────────────

MEME_IDENTIFY_SYSTEM_PROMPT = """你是一个中文互联网梗（meme）分析专家。从B站热门视频的标题、标签、评论和弹幕中识别新兴的网络梗。

梗的特征：
- 在多个视频或评论中重复出现的特定短语、句式或概念
- 具有幽默、反讽、荒诞或自指等特征
- 通常由某个视频引发，在评论区被大量复制和改编
- **在弹幕中高频重复出现的短语**（弹幕是梗的重要发酵地）

分析要求：
- 识别重复出现的特定短语（非通用词汇）
- 判断是否具有梗的结构特征（双关、反讽、谐音、荒诞、反差等）
- **优先关注弹幕高频短语中具有梗特征的表达**
- **跨视频交叉验证**：如果某个短语在多个视频的弹幕/评论中出现，优先识别
- 区分"通用流行语"和"特定场景梗"
- 不要将普通的流行语或日常用语误判为梗

返回 JSON 数组（不要 markdown 包裹）：
[
  {
    "text": "梗的文本",
    "context_hint": "梗的使用场景（如：吐槽某事时、表达无奈时）",
    "frequency": 出现频次估计,
    "tags": ["双关", "自指", "弹幕高频"],
    "description": "梗的简要说明"
  }
]"""

MEME_IDENTIFY_USER_PROMPT = """分析以下B站热门内容，识别其中出现的新兴梗：

{video_data}

{danmaku_section}

请识别重复出现的梗模式，返回 JSON 数组。"""


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
        """Run the full collection pipeline: videos → comments → meme identification.

        Returns:
            List of MemeCandidate identified from trending content.
        """
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
                "[MemeCollector] Collection timed out after %ds — "
                "returning partial results",
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
        """Collect danmaku specifically for training data.

        This method focuses on collecting high-quality danmaku for training purposes,
        with filtering for length, meme keywords, and originality.

        Args:
            max_danmaku: Maximum number of danmaku to collect.
            min_length: Minimum character length for danmaku.
            max_length: Maximum character length for danmaku.
            meme_keywords: Optional list of meme keywords to filter by.

        Returns:
            List of CollectedDanmaku filtered for training quality.
        """
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
                "[MemeCollector] Danmaku collection timed out after %ds — "
                "returning partial results",
                self._request_timeout,
            )
            return []
        except Exception as e:
            logger.error("[MemeCollector] Danmaku collection failed: %s", e, exc_info=True)
            return []

    async def _collect_danmaku_impl(
        self,
        max_danmaku: int,
        min_length: int,
        max_length: int,
        meme_keywords: list[str] | None,
    ) -> list[CollectedDanmaku]:
        """Internal danmaku collection implementation."""
        try:
            # Phase 1: Fetch trending videos
            videos = await self._fetch_trending_videos()
            if not videos:
                logger.info("[MemeCollector] No trending videos found for danmaku collection")
                return []

            logger.info("[MemeCollector] Fetched %d videos for danmaku collection", len(videos))

            # Phase 2: Collect danmaku from videos in parallel
            all_danmaku: list[CollectedDanmaku] = []
            semaphore = asyncio.Semaphore(self._concurrency)

            async def fetch_one(video: CollectedVideo) -> list[CollectedDanmaku]:
                async with semaphore:
                    await asyncio.sleep(self._request_delay)
                    return await self._fetch_video_danmaku(video)

            results = await asyncio.gather(
                *[fetch_one(v) for v in videos],
                return_exceptions=True,
            )

            for r in results:
                if isinstance(r, BaseException):
                    logger.warning("[MemeCollector] Danmaku fetch error: %s", r)
                    continue
                all_danmaku.extend(r)

            logger.info("[MemeCollector] Collected %d raw danmaku", len(all_danmaku))

            # Phase 3: Filter danmaku for training quality
            filtered_danmaku = self._filter_danmaku_for_training(
                all_danmaku, min_length, max_length, meme_keywords, max_danmaku,
            )

            logger.info(
                "[MemeCollector] Filtered to %d danmaku for training",
                len(filtered_danmaku),
            )
            return filtered_danmaku

        except Exception as e:
            logger.error("[MemeCollector] Danmaku collection failed: %s", e, exc_info=True)
            return []

    async def _collect_impl(self) -> list[MemeCandidate]:
        """Internal collection implementation (wrapped with timeout by collect())."""
        try:
            # Phase 1: Fetch trending videos (existing path)
            videos_task = asyncio.create_task(self._fetch_trending_videos())

            # Phase 2: Fetch danmaku phrases (new path — runs in parallel with videos)
            danmaku_task = asyncio.create_task(self._fetch_danmaku_phrases())

            videos = await videos_task
            danmaku_phrases = await danmaku_task

            if not videos:
                logger.info("[MemeCollector] No trending videos found")
                # If we have danmaku phrases but no videos, still do heuristic
                if danmaku_phrases:
                    logger.info(
                        "[MemeCollector] %d danmaku phrases collected, "
                        "running heuristic-only identification",
                        len(danmaku_phrases),
                    )
                    return self._heuristic_danmaku_only(danmaku_phrases)
                return []

            logger.info("[MemeCollector] Fetched %d videos", len(videos))
            if danmaku_phrases:
                logger.info(
                    "[MemeCollector] Collected %d danmaku hot phrases",
                    len(danmaku_phrases),
                )

            # Phase 3: Collect comments in parallel with semaphore control
            all_comments: dict[str, list[CollectedComment]] = {}
            semaphore = asyncio.Semaphore(self._concurrency)

            async def fetch_one(video: CollectedVideo) -> tuple[str, list[CollectedComment]]:
                async with semaphore:
                    await asyncio.sleep(self._request_delay)
                    comments = await self._fetch_comments(video.bvid)
                    return video.bvid, comments

            results = await asyncio.gather(
                *[fetch_one(v) for v in videos],
                return_exceptions=True,
            )

            for r in results:
                if isinstance(r, BaseException):
                    logger.warning("[MemeCollector] Comment fetch error: %s", r)
                    continue
                bvid, comments = r
                if comments:
                    all_comments[bvid] = comments

            logger.info(
                "[MemeCollector] Collected comments for %d/%d videos",
                len(all_comments), len(videos),
            )

            # Phase 4: Identify meme candidates via LLM (includes danmaku context)
            candidates = await self._identify_meme_candidates(
                videos, all_comments, danmaku_phrases,
            )
            logger.info(
                "[MemeCollector] Identified %d meme candidates",
                len(candidates),
            )
            return candidates

        except Exception as e:
            logger.error("[MemeCollector] Collection failed: %s", e, exc_info=True)
            return []

    # ── Video collection ────────────────────────────────────────────────

    async def _fetch_trending_videos(self) -> list[CollectedVideo]:
        """Fetch trending videos from B站 via api.fetch_trending_videos().

        Builds CollectedVideo list from raw API dicts.
        """
        raw_items = await fetch_trending_videos(
            max_videos=self._max_videos,
            search_keyword=self._search_keyword,
        )

        logger.info(
            "[MemeCollector] fetch_trending_videos returned %d raw items",
            len(raw_items),
        )

        videos: list[CollectedVideo] = []
        for item in raw_items[: self._max_videos]:
            try:
                title = item.get("title", "")
                # Strip HTML tags from search results
                title = title.replace('<em class="keyword">', "").replace("</em>", "")

                # Hot API uses "desc", search API uses "description"
                description = item.get("desc", item.get("description", ""))
                if isinstance(description, str):
                    description = description[:200]
                else:
                    description = ""

                # Hot API uses stat.view, search API uses play
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
                    bvid=item.get("bvid", ""),
                    title=title,
                    description=description,
                    tags=parse_tags(item.get("tag", "")),
                    view_count=view_count,
                    danmaku_count=danmaku_count,
                    reply_count=reply_count,
                )
                if video.bvid:
                    videos.append(video)
            except Exception as e:
                logger.debug("[MemeCollector] Skipped video item: %s", e)
                continue

        logger.info(
            "[MemeCollector] _fetch_trending_videos returning %d videos",
            len(videos),
        )
        return videos

    # ── Comment collection ──────────────────────────────────────────────

    async def _fetch_comments(self, bvid: str) -> list[CollectedComment]:
        """Fetch top comments for a video via api.fetch_comments().

        Builds CollectedComment list from raw API dicts.
        """
        raw_comments = await fetch_comments(
            bvid=bvid,
            max_count=self._max_comments_per_video,
            min_likes=self._min_comment_likes,
            timeout=self._comment_timeout,
        )

        return [
            CollectedComment(
                content=c.get("content", ""),
                likes=c.get("likes", 0),
                replies=c.get("replies", 0),
                publish_time=c.get("publish_time", ""),
            )
            for c in raw_comments
        ]

    # ── Danmaku collection ──────────────────────────────────────────────

    async def _fetch_danmaku_phrases(self) -> list[str]:
        """Collect hot danmaku phrases from DanmakuBuffer and historical API.

        Two sources:
        1. Real-time buffer (DanmakuBuffer.get_hot_phrases)
        2. Historical danmaku API (api.fetch_live_danmaku)

        Returns:
            List of hot danmaku phrase texts, deduplicated.
        """
        phrases: list[str] = []
        seen: set[str] = set()

        # Source 1: Real-time buffer
        if self._danmaku_buffer:
            try:
                hot = self._danmaku_buffer.get_hot_phrases(
                    min_freq=3, window_minutes=30,
                )
                for p in hot:
                    text = p.text.strip()
                    if text and text not in seen:
                        phrases.append(text)
                        seen.add(text)
                if hot:
                    logger.info(
                        "[MemeCollector] Got %d hot phrases from DanmakuBuffer",
                        len(hot),
                    )
            except Exception as e:
                logger.warning(
                    "[MemeCollector] DanmakuBuffer query failed: %s", e,
                )

        # Source 2: Historical danmaku API
        if self._room_id:
            try:
                historical = await fetch_live_danmaku(
                    room_id=self._room_id,
                    limit=100,
                    timeout=self._comment_timeout,
                )
                for text in historical:
                    if text and text not in seen:
                        phrases.append(text)
                        seen.add(text)
                if historical:
                    logger.info(
                        "[MemeCollector] Got %d historical danmaku texts",
                        len(historical),
                    )
            except Exception as e:
                logger.warning(
                    "[MemeCollector] Historical danmaku fetch failed: %s", e,
                )

        return phrases

    # ── Video danmaku collection for training ───────────────────────────

    async def _fetch_video_danmaku(self, video: CollectedVideo) -> list[CollectedDanmaku]:
        """Fetch danmaku from a single video for training data.

        Args:
            video: CollectedVideo to fetch danmaku from.

        Returns:
            List of CollectedDanmaku from the video.
        """
        try:
            raw_danmaku = await fetch_video_danmaku(
                bvid=video.bvid,
                max_count=100,
                timeout=self._comment_timeout,
            )

            return [
                CollectedDanmaku(
                    content=d.get("content", ""),
                    source_video=video.bvid,
                    source_type="video",
                    likes=d.get("likes", 0),
                    publish_time=d.get("publish_time", ""),
                    mode=d.get("mode", 1),
                    color=d.get("color", 16777215),
                )
                for d in raw_danmaku
                if d.get("content")
            ]

        except Exception as e:
            logger.warning("[MemeCollector] Failed to fetch danmaku for %s: %s", video.bvid, e)
            return []

    def _filter_danmaku_for_training(
        self,
        danmaku_list: list[CollectedDanmaku],
        min_length: int,
        max_length: int,
        meme_keywords: list[str] | None,
        max_count: int,
    ) -> list[CollectedDanmaku]:
        """Filter danmaku for training quality.

        Filters based on:
        1. Length (5-20 characters)
        2. Meme keywords (if provided)
        3. Originality (remove duplicates)
        4. Quality score (likes, mode, etc.)

        Args:
            danmaku_list: Raw danmaku list.
            min_length: Minimum character length.
            max_length: Maximum character length.
            meme_keywords: Optional list of meme keywords.
            max_count: Maximum number to return.

        Returns:
            Filtered list of CollectedDanmaku.
        """
        # Step 1: Filter by length
        length_filtered = [
            d for d in danmaku_list
            if min_length <= len(d.content) <= max_length
        ]

        # Step 2: Filter by meme keywords if provided
        if meme_keywords:
            keyword_filtered = []
            for d in length_filtered:
                content_lower = d.content.lower()
                for keyword in meme_keywords:
                    if keyword.lower() in content_lower:
                        d.is_meme = True
                        d.meme_type = keyword
                        keyword_filtered.append(d)
                        break
            length_filtered = keyword_filtered

        # Step 3: Remove duplicates (keep first occurrence)
        seen_content: set[str] = set()
        unique_danmaku = []
        for d in length_filtered:
            if d.content not in seen_content:
                seen_content.add(d.content)
                unique_danmaku.append(d)

        # Step 4: Calculate quality score and sort
        for d in unique_danmaku:
            score = 0.0
            # Higher score for scroll danmaku (mode 1-3)
            if d.mode in (1, 2, 3):
                score += 0.3
            # Higher score for more likes
            if d.likes > 0:
                score += min(d.likes / 100.0, 0.4)
            # Higher score for meme keywords
            if d.is_meme:
                score += 0.3
            # Higher score for reasonable length
            if 8 <= len(d.content) <= 15:
                score += 0.2
            d.quality_score = min(score, 1.0)

        # Sort by quality score (descending)
        unique_danmaku.sort(key=lambda x: x.quality_score, reverse=True)

        return unique_danmaku[:max_count]

    # ── Meme identification ─────────────────────────────────────────────

    async def _identify_meme_candidates(
        self,
        videos: list[CollectedVideo],
        comments: dict[str, list[CollectedComment]],
        danmaku_phrases: list[str] | None = None,
    ) -> list[MemeCandidate]:
        """Use LLM to identify meme patterns from collected data.

        Args:
            videos: Collected trending videos.
            comments: Collected comments per video.
            danmaku_phrases: Optional hot danmaku phrases from buffer/history.

        Returns:
            List of MemeCandidate identified by LLM or heuristic fallback.
        """
        if not self._llm:
            logger.info("[MemeCollector] No LLM client, using heuristic identification")
            return self._heuristic_identify(videos, comments, danmaku_phrases)

        # Build context for LLM
        video_lines: list[str] = []
        for v in videos:
            video_lines.append(
                f"视频: {v.title}\n"
                f"标签: {', '.join(v.tags) if v.tags else '无'}\n"
                f"播放: {v.view_count}, 弹幕: {v.danmaku_count}"
            )

        comment_lines: list[str] = []
        for bvid, clist in comments.items():
            for c in clist[:10]:  # Limit comments to avoid token overflow
                comment_lines.append(f"[{bvid}] 👍{c.likes}: {c.content}")

        video_text = "\n\n".join(video_lines[:20])
        comment_text = "\n".join(comment_lines[:50])

        combined = f"=== 热门视频 ===\n\n{video_text}\n\n=== 高赞评论 ===\n\n{comment_text}"

        # Build danmaku section if available
        danmaku_section = ""
        if danmaku_phrases:
            danmaku_lines = "\n".join(f"  - {p}" for p in danmaku_phrases[:30])
            danmaku_section = f"=== 弹幕高频短语 ===\n\n{danmaku_lines}"

        # Try chat_messages first (new interface), fall back to chat (legacy)
        llm_method = None
        if hasattr(self._llm, 'chat_messages'):
            llm_method = 'chat_messages'
        elif hasattr(self._llm, 'chat'):
            llm_method = 'chat'
            logger.info("[MemeCollector] LLM lacks chat_messages, using chat() fallback")

        if not llm_method:
            logger.warning(
                "[MemeCollector] LLM has neither chat_messages nor chat(), "
                "using heuristic"
            )
            return self._heuristic_identify(videos, comments, danmaku_phrases)

        try:
            if llm_method == 'chat_messages':
                result = await self._llm.chat_messages(
                    messages=[
                        {"role": "system", "content": MEME_IDENTIFY_SYSTEM_PROMPT},
                        {"role": "user", "content": MEME_IDENTIFY_USER_PROMPT.format(
                            video_data=combined,
                            danmaku_section=danmaku_section,
                        )},
                    ],
                    response_format={"type": "json_object"},
                )
            else:
                # Legacy chat() interface — build single user message
                user_text = MEME_IDENTIFY_SYSTEM_PROMPT + "\n\n" + MEME_IDENTIFY_USER_PROMPT.format(
                    video_data=combined,
                    danmaku_section=danmaku_section,
                )
                result = await self._llm.chat(
                    messages=[{"role": "user", "content": user_text}],
                    response_format={"type": "json_object"},
                )

            content = result.get("content", "") if isinstance(result, dict) else str(result)
            parsed = self._parse_llm_json(content)
            return self._build_candidates(parsed, videos)

        except Exception as e:
            logger.warning("[MemeCollector] LLM identification failed: %s", e)
            return self._heuristic_identify(videos, comments, danmaku_phrases)

    def _heuristic_identify(
        self,
        videos: list[CollectedVideo],
        comments: dict[str, list[CollectedComment]],
        danmaku_phrases: list[str] | None = None,
    ) -> list[MemeCandidate]:
        """Fallback: identify meme candidates from high-frequency phrases.

        Three strategies combined:
        1. Repeated tags across videos
        2. Meaningful phrases from video titles
        3. Semantic phrases from top comments
        4. Hot danmaku phrases (new)
        """
        candidates: list[MemeCandidate] = []
        seen_texts: set[str] = set()

        # ── Strategy 1: Repeated tags ──
        tag_counts: dict[str, int] = {}
        for v in videos:
            for tag in v.tags:
                t = tag.strip()
                if len(t) >= 2 and t not in STOPWORDS:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        for phrase, count in tag_counts.items():
            if count >= 2 and len(phrase) <= 15 and phrase not in seen_texts:
                seen_texts.add(phrase)
                candidates.append(MemeCandidate(
                    text=phrase,
                    context_hint=f"出现在 {count} 个热门视频标签中",
                    frequency=count,
                    tags=["bilibili", "trending", "tag"],
                ))

        # ── Strategy 2: Extract meaningful phrases from titles ──
        title_phrases: Counter[str] = Counter()
        for v in videos:
            for phrase in extract_title_phrases(v.title):
                if phrase not in STOPWORDS and len(phrase) >= 2:
                    title_phrases[phrase] += 1
        for phrase, count in title_phrases.most_common(10):
            if count >= 2 and phrase not in seen_texts:
                seen_texts.add(phrase)
                candidates.append(MemeCandidate(
                    text=phrase,
                    context_hint=f"出现在 {count} 个视频标题中的热门短语",
                    frequency=count,
                    tags=["bilibili", "trending", "title"],
                ))

        # ── Strategy 3: Semantic phrases from top comments ──
        all_comments_text: list[str] = []
        for clist in comments.values():
            for c in clist[:5]:
                all_comments_text.append(c.content)
        if all_comments_text:
            try:
                comment_phrases = self._extract_semantic_phrases(all_comments_text, top_k=10)
                for phrase, count in comment_phrases:
                    if count >= 2 and phrase not in seen_texts:
                        seen_texts.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase,
                            context_hint=f"在热门评论中出现 {count} 次",
                            frequency=count,
                            tags=["bilibili", "trending", "comment"],
                        ))
            except ImportError:
                logger.warning(
                    "[MemeCollector] jieba not installed, skipping comment semantic extraction"
                )

        # ── Strategy 4: Hot danmaku phrases (new) ──
        if danmaku_phrases:
            # Use semantic extraction if available, else simple frequency
            try:
                semantic = self._extract_semantic_phrases(danmaku_phrases, top_k=20)
                for phrase, count in semantic:
                    if phrase not in seen_texts and phrase not in STOPWORDS:
                        seen_texts.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase,
                            context_hint=f"弹幕高频短语，出现 {count} 次以上",
                            frequency=count,
                            tags=["bilibili", "danmaku", "hot"],
                        ))
            except ImportError:
                # jieba not available — use simple frequency
                from collections import Counter as _Counter
                freq = _Counter(danmaku_phrases)
                for phrase, count in freq.most_common(15):
                    if (phrase not in seen_texts and phrase not in STOPWORDS
                            and len(phrase) >= 2):
                        seen_texts.add(phrase)
                        candidates.append(MemeCandidate(
                            text=phrase,
                            context_hint=f"弹幕中出现 {count} 次",
                            frequency=count,
                            tags=["bilibili", "danmaku", "hot"],
                        ))

        logger.info(
            "[MemeCollector] Heuristic identify: %d candidates from "
            "%d videos, %d comments, %d danmaku phrases",
            len(candidates), len(videos),
            sum(len(c) for c in comments.values()),
            len(danmaku_phrases) if danmaku_phrases else 0,
        )
        return candidates[:15]

    def _heuristic_danmaku_only(
        self,
        danmaku_phrases: list[str],
    ) -> list[MemeCandidate]:
        """Fallback when only danmaku data is available (no videos)."""
        candidates: list[MemeCandidate] = []
        seen: set[str] = set()

        try:
            semantic = self._extract_semantic_phrases(danmaku_phrases, top_k=15)
            for phrase, count in semantic:
                if phrase not in seen and phrase not in STOPWORDS and len(phrase) >= 2:
                    seen.add(phrase)
                    candidates.append(MemeCandidate(
                        text=phrase,
                        context_hint="弹幕高频短语",
                        frequency=count,
                        tags=["bilibili", "danmaku", "hot"],
                    ))
        except ImportError:
            from collections import Counter as _Counter
            freq = _Counter(danmaku_phrases)
            for phrase, count in freq.most_common(10):
                if (phrase not in seen and phrase not in STOPWORDS
                        and len(phrase) >= 2):
                    seen.add(phrase)
                    candidates.append(MemeCandidate(
                        text=phrase,
                        context_hint="弹幕高频短语",
                        frequency=count,
                        tags=["bilibili", "danmaku", "hot"],
                    ))

        return candidates[:10]

    @staticmethod
    def _extract_semantic_phrases(
        texts: list[str],
        top_k: int = 20,
    ) -> list[tuple[str, int]]:
        """Extract meaningful phrases using jieba segmentation + TF-IDF filtering.

        Uses jieba for Chinese word segmentation, extracts 2-4 word n-grams,
        and applies TF-IDF to filter stopwords.

        Falls back to simple character n-grams if jieba is not installed.
        """
        try:
            import jieba
        except ImportError:
            # Fallback: use character 2-gram like old method
            logger.warning(
                "[MemeCollector] jieba not installed, "
                "falling back to char n-grams for semantic extraction"
            )
            from collections import Counter as _Counter
            fallback: _Counter[str] = _Counter()
            for text in texts:
                chars = list(text.strip())
                for n in range(2, min(5, len(chars) + 1)):
                    for i in range(len(chars) - n + 1):
                        phrase = "".join(chars[i:i + n])
                        if phrase.strip() and not phrase.isdigit():
                            fallback[phrase] += 1
            return fallback.most_common(top_k)

        from collections import Counter
        from math import log

        # Jieba-based semantic extraction
        total_docs = len(texts)
        if total_docs == 0:
            return []

        # Tokenize all texts
        tokenized = [list(jieba.cut(t)) for t in texts]

        # Extract 2-4 word n-grams
        ngram_counter: Counter[str] = Counter()
        doc_frequency: Counter[str] = Counter()

        for tokens in tokenized:
            seen_in_doc = set()
            for i in range(len(tokens)):
                for j in range(i + 1, min(i + 4, len(tokens) + 1)):
                    phrase = "".join(tokens[i:j])
                    if len(phrase) < 2 or len(phrase) > 15:
                        continue
                    if phrase.isdigit():
                        continue
                    ngram_counter[phrase] += 1
                    seen_in_doc.add(phrase)
            for phrase in seen_in_doc:
                doc_frequency[phrase] += 1

        # TF-IDF scoring: score = count * log(total_docs / (1 + doc_freq))
        scored = []
        for phrase, count in ngram_counter.items():
            if count < 2:  # Must appear at least twice
                continue
            if phrase in STOPWORDS:
                continue
            df = doc_frequency.get(phrase, 1)
            # Boost phrases that appear across multiple documents
            idf = log((total_docs + 1) / (df + 1)) + 1
            score = count * idf
            scored.append((phrase, int(score)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
        """Parse LLM JSON response into list of dicts."""
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Try common wrapper keys
                for key in ("memes", "candidates", "results", "items"):
                    if key in data:
                        return data[key]
                return [data]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[MemeCollector] JSON parse failed: %s", e)
        return []

    @staticmethod
    def _build_candidates(
        parsed: list[dict[str, Any]],
        videos: list[CollectedVideo],
    ) -> list[MemeCandidate]:
        """Build MemeCandidate from parsed LLM output."""
        candidates: list[MemeCandidate] = []
        source_bvids = [v.bvid for v in videos[:3]] if videos else []

        for item in parsed:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            candidates.append(MemeCandidate(
                text=text,
                context_hint=item.get("context_hint", ""),
                frequency=item.get("frequency", 1),
                source_videos=list(source_bvids),
                tags=item.get("tags", []),
            ))

        return candidates
