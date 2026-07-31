"""Anonymous, in-memory-sanitized Twitch VOD chat capture."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType

from .cleaning import _deterministic_drop_reason, _normalize_for_duplicate
from .dataset import DatasetWriter

_TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
_TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_COMMENTS_QUERY_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


class TwitchCaptureError(RuntimeError):
    """Raised when public VOD chat cannot be read safely."""


class TwitchPageFetcher(Protocol):
    """Fetch one public VOD comment page starting at a relative video offset."""

    def __call__(self, offset_seconds: int) -> list[dict[str, object]]: ...


class TwitchGraphQLPageFetcher:
    """Small anonymous client for Twitch's public VOD comment operation."""

    def __init__(
        self,
        vod_id: str,
        *,
        client_id: str = _TWITCH_WEB_CLIENT_ID,
        timeout_seconds: float = 20,
        max_attempts: int = 4,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not vod_id.strip():
            raise ValueError("vod_id must not be empty")
        if not client_id.strip():
            raise ValueError("client_id must not be empty")
        if timeout_seconds <= 0 or max_attempts <= 0:
            raise ValueError("timeout_seconds and max_attempts must be positive")
        self._vod_id = vod_id.strip()
        self._client_id = client_id.strip()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._opener = opener
        self._sleeper = sleeper

    def __call__(self, offset_seconds: int) -> list[dict[str, object]]:
        if offset_seconds < 0:
            raise ValueError("offset_seconds must not be negative")
        payload = {
            "operationName": "VideoCommentsByOffsetOrCursor",
            "variables": {
                "videoID": self._vod_id,
                "contentOffsetSeconds": offset_seconds,
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": _COMMENTS_QUERY_HASH,
                },
            },
        }
        request = urllib.request.Request(
            _TWITCH_GQL_URL,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Client-ID": self._client_id,
                "Content-Type": "application/json",
                "User-Agent": "Animetta-Livestream-Evaluation/1",
            },
            method="POST",
        )
        for attempt in range(self._max_attempts):
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if body.get("errors"):
                    raise TwitchCaptureError("Twitch rejected the public VOD chat request")
                comments = body["data"]["video"]["comments"]
                edges = comments.get("edges") or []
                if not isinstance(edges, list):
                    raise TwitchCaptureError("Twitch returned an invalid VOD chat page")
                return [edge for edge in edges if isinstance(edge, dict)]
            except (
                KeyError,
                TypeError,
                ValueError,
                OSError,
                urllib.error.HTTPError,
                urllib.error.URLError,
            ) as exc:
                if attempt + 1 >= self._max_attempts:
                    raise TwitchCaptureError("Twitch VOD chat request failed") from exc
                self._sleeper(0.25 * (2**attempt))
        raise AssertionError("unreachable")


class TwitchVodCollector:
    """Capture one continuous VOD window without persisting its source identity."""

    def __init__(
        self,
        *,
        vod_id: str,
        writer: DatasetWriter,
        start_seconds: int,
        duration_seconds: int,
        page_step_seconds: int = 5,
        fetch_page: TwitchPageFetcher | None = None,
        max_workers: int = 20,
        rate_cap_per_minute: int | None = None,
        deterministic_prefilter: bool = False,
    ) -> None:
        if not vod_id.strip():
            raise ValueError("vod_id must not be empty")
        if start_seconds < 0:
            raise ValueError("start_seconds must not be negative")
        if duration_seconds <= 0 or page_step_seconds <= 0 or max_workers <= 0:
            raise ValueError("duration, page step, and worker count must be positive")
        if rate_cap_per_minute is not None and not 1 <= rate_cap_per_minute <= 300:
            raise ValueError("rate_cap_per_minute must be between 1 and 300")
        self._vod_id = vod_id.strip()
        self._writer = writer
        self._start_seconds = start_seconds
        self._duration_seconds = duration_seconds
        self._page_step_seconds = page_step_seconds
        self._fetch_page = fetch_page or TwitchGraphQLPageFetcher(self._vod_id)
        self._max_workers = max_workers
        self._rate_cap_per_minute = rate_cap_per_minute
        self._deterministic_prefilter = deterministic_prefilter

    def capture(self) -> dict[str, Any]:
        """Fetch, deduplicate, sanitize, and finalize one continuous chat window."""
        end_seconds = self._start_seconds + self._duration_seconds
        initial_offsets = list(
            range(
                self._start_seconds,
                end_seconds + 1,
                self._page_step_seconds,
            ),
        )
        pages = self._fetch_offsets(initial_offsets)
        dense_offsets = [
            offset for offset, edges in pages if self._page_needs_refinement(offset, edges)
        ]
        extra_offsets = [
            offset
            for dense_start in dense_offsets
            for offset in range(dense_start + 1, dense_start + self._page_step_seconds)
            if offset <= end_seconds
        ]
        if extra_offsets:
            pages.extend(self._fetch_offsets(extra_offsets))

        records: dict[str, tuple[float, str, str, str]] = {}
        for _requested_offset, edges in pages:
            for edge in edges:
                parsed = self._parse_edge(edge)
                if parsed is None:
                    continue
                comment_id, source_offset, actor_id, actor_name, text = parsed
                if self._start_seconds <= source_offset <= end_seconds:
                    records[comment_id] = (source_offset, actor_id, actor_name, text)

        ordered = sorted(records.values(), key=lambda item: (item[0], item[1], item[3]))
        eligible = self._prefilter(ordered)
        selected = self._shape_rate(eligible)
        for sequence, (source_sequence, record) in enumerate(selected):
            source_offset, actor_id, actor_name, text = record
            payload: dict[str, object] = {"user_id": actor_id}
            if self._rate_cap_per_minute is not None or self._deterministic_prefilter:
                payload["source_sequence"] = source_sequence
            self._writer.write(
                LivestreamEvent(
                    sequence=sequence,
                    offset_ms=round((source_offset - self._start_seconds) * 1000),
                    event_type=LivestreamEventType.DANMAKU,
                    actor_id=actor_name,
                    text=text,
                    payload=payload,
                ),
            )
        capture_derivation: dict[str, object] | None = None
        if self._rate_cap_per_minute is not None or self._deterministic_prefilter:
            if self._rate_cap_per_minute is not None and self._deterministic_prefilter:
                kind = "deterministic_real_quality_rate_cap"
            elif self._rate_cap_per_minute is not None:
                kind = "deterministic_real_rate_cap"
            else:
                kind = "deterministic_real_quality_selection"
            capture_derivation = {"kind": kind}
            if self._rate_cap_per_minute is not None:
                capture_derivation["rate_cap_per_minute"] = self._rate_cap_per_minute
            if self._deterministic_prefilter:
                capture_derivation["deterministic_prefilter"] = True
            capture_derivation.update(
                {
                    "observed_replyable": len(ordered),
                    "eligible_replyable": len(eligible),
                    "selected_replyable": len(selected),
                },
            )
            if not self._deterministic_prefilter:
                capture_derivation.pop("eligible_replyable")
        return self._writer.finalize(
            duration_ms=self._duration_seconds * 1000,
            capture_derivation=capture_derivation,
        )

    def _shape_rate(
        self,
        records: Sequence[tuple[int, tuple[float, str, str, str]]],
    ) -> list[tuple[int, tuple[float, str, str, str]]]:
        if self._rate_cap_per_minute is None:
            return list(records)
        selected: list[tuple[int, tuple[float, str, str, str]]] = []
        selected_offsets: deque[float] = deque()
        for source_sequence, record in records:
            source_offset = record[0]
            while selected_offsets and selected_offsets[0] <= source_offset - 60:
                selected_offsets.popleft()
            if len(selected_offsets) >= self._rate_cap_per_minute:
                continue
            selected_offsets.append(source_offset)
            selected.append((source_sequence, record))
        return selected

    def _prefilter(
        self,
        records: Sequence[tuple[float, str, str, str]],
    ) -> list[tuple[int, tuple[float, str, str, str]]]:
        indexed = list(enumerate(records))
        if not self._deterministic_prefilter:
            return indexed
        normalized_counts = Counter(
            normalized
            for _offset, _actor_id, _actor_name, text in records
            if len(normalized := _normalize_for_duplicate(text)) >= 24
        )
        kept_copypasta: set[str] = set()
        last_kept_by_actor_text: dict[tuple[str, str], float] = {}
        eligible: list[tuple[int, tuple[float, str, str, str]]] = []
        for source_sequence, record in indexed:
            offset, actor_id, _actor_name, text = record
            normalized = _normalize_for_duplicate(text)
            reason = _deterministic_drop_reason(text.strip())
            if reason is None and normalized_counts[normalized] >= 3:
                if normalized in kept_copypasta:
                    reason = "copypasta"
                else:
                    kept_copypasta.add(normalized)
            duplicate_key = (actor_id, normalized)
            previous = last_kept_by_actor_text.get(duplicate_key)
            if reason is None and previous is not None and offset - previous <= 30:
                reason = "same_actor_duplicate"
            if reason is not None:
                continue
            last_kept_by_actor_text[duplicate_key] = offset
            eligible.append((source_sequence, record))
        return eligible

    def _fetch_offsets(
        self,
        offsets: Sequence[int],
    ) -> list[tuple[int, list[dict[str, object]]]]:
        pages: list[tuple[int, list[dict[str, object]]]] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(self._fetch_page, offset): offset for offset in offsets}
            for future in as_completed(futures):
                pages.append((futures[future], future.result()))
        pages.sort(key=lambda item: item[0])
        return pages

    def _page_needs_refinement(
        self,
        requested_offset: int,
        edges: Sequence[Mapping[str, object]],
    ) -> bool:
        if len(edges) < 59:
            return False
        final_offset = self._edge_offset(edges[-1])
        return (
            final_offset is not None and final_offset < requested_offset + self._page_step_seconds
        )

    @staticmethod
    def _edge_offset(edge: Mapping[str, object]) -> float | None:
        node = edge.get("node")
        if not isinstance(node, Mapping):
            return None
        value = node.get("contentOffsetSeconds")
        return float(value) if isinstance(value, int | float) else None

    @staticmethod
    def _parse_edge(
        edge: Mapping[str, object],
    ) -> tuple[str, float, str, str, str] | None:
        node = edge.get("node")
        if not isinstance(node, Mapping):
            return None
        comment_id = node.get("id") or edge.get("cursor")
        source_offset = node.get("contentOffsetSeconds")
        message = node.get("message")
        if not isinstance(comment_id, str) or not isinstance(source_offset, int | float):
            return None
        if not isinstance(message, Mapping):
            return None
        fragments = message.get("fragments")
        if not isinstance(fragments, list):
            return None
        text = "".join(
            str(fragment.get("text") or "")
            for fragment in fragments
            if isinstance(fragment, Mapping)
        ).strip()
        commenter = node.get("commenter")
        commenter = commenter if isinstance(commenter, Mapping) else {}
        actor_id = str(commenter.get("id") or commenter.get("login") or comment_id)
        actor_name = str(commenter.get("login") or commenter.get("displayName") or "")
        return comment_id, float(source_offset), actor_id, actor_name, text
