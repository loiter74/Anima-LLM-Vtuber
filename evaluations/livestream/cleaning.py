"""Balanced contextual cleaning for sanitized livestream datasets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType

from .dataset import is_chinese_dominant

_REPLYABLE_TYPES = {
    LivestreamEventType.DANMAKU,
    LivestreamEventType.GIFT,
    LivestreamEventType.SUPER_CHAT,
}
_EMOTES = {
    "copege",
    "eliv tutel",
    "eliv vedal",
    "evilflooshed",
    "gamba",
    "giganeuro",
    "kappa",
    "kekw",
    "latege",
    "lul",
    "lule",
    "megalul",
    "monka",
    "monkas",
    "neurojam",
    "neurosocute",
    "nuru",
    "omegalul",
    "pagman",
    "pepehands",
    "pog",
    "pogchamp",
    "tutel",
    "tutelbedge",
    "vedal eliv",
    "vedalissues",
    "vedalnuru",
    "wokege",
    "xdd",
    "xdx",
}
_MEANINGLESS_ABBREVIATIONS = {"o7", "om", "ok"}
_O7_NOISE = re.compile(r"^o7(?:\s+[a-z0-9_-]+)?$", re.IGNORECASE)
_LAUGHTER_ONLY = re.compile(
    r"^(?:哈{2,}|呵{2,}|嘿{2,}|草{1,}|h{2,}|lol+|w{2,})[!！?？~～。\.\s]*$",
    re.IGNORECASE,
)
_QUESTION_MARKERS = ("?", "？", "吗", "呢", "为什么", "怎么", "什么", "哪个", "哪里", "多少")
_INSTRUCTION_MARKERS = ("快去", "打开", "走", "按", "使用", "别", "左边", "右边", "上面", "下面")
_GREETING_MARKERS = ("你好", "早上好", "晚上好", "初见", "第一次来", "欢迎")
_CORRECTION_MARKERS = ("不对", "其实", "应该", "不是", "搞错")
_EMOTION_MARKERS = ("太", "喜欢", "可爱", "厉害", "离谱", "难受", "加油", "笑死")
_EMBEDDED_TERM_TRANSLATIONS = (
    (re.compile(r"(?<![A-Za-z0-9])nwero(?![A-Za-z0-9])", re.IGNORECASE), "Neuro"),
    (
        re.compile(r"(?<![A-Za-z0-9])vedalok(?![A-Za-z0-9])", re.IGNORECASE),
        "（赞同）",
    ),
    (re.compile(r"(?<![A-Za-z0-9])o7(?![A-Za-z0-9])", re.IGNORECASE), "（敬礼）"),
    (re.compile(r"(?<![A-Za-z0-9])xdd(?![A-Za-z0-9])", re.IGNORECASE), "（笑）"),
    (
        re.compile(r"(?<![A-Za-z0-9])tutelbedge(?![A-Za-z0-9])", re.IGNORECASE),
        "（催促）",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9])dinkdonk(?![A-Za-z0-9])", re.IGNORECASE),
        "（提醒）",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9])groan\s+tube(?![A-Za-z0-9])", re.IGNORECASE),
        "呻吟管",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9])jumpscare(?![A-Za-z0-9])", re.IGNORECASE),
        "突脸惊吓",
    ),
    (re.compile(r"(?<![A-Za-z0-9])poke(?![A-Za-z0-9])", re.IGNORECASE), "戳戳"),
    (re.compile(r"(?<![A-Za-z0-9])sadge(?![A-Za-z0-9])", re.IGNORECASE), "（难过）"),
)


@dataclass(frozen=True, slots=True)
class ContextMessage:
    """One sanitized neighboring message used only in an in-memory prompt."""

    sequence: int
    offset_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class SemanticRequest:
    """One message requiring contextual intent classification or translation."""

    sequence: int
    text: str
    context_before: tuple[ContextMessage, ...] = ()
    context_after: tuple[ContextMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticDecision:
    """Structured semantic processor result."""

    sequence: int
    keep: bool
    intent: str
    text_zh: str
    reason: str = "unrecognized_intent"


class SemanticProcessor(Protocol):
    """Injectable batch semantic processor contract."""

    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]: ...


class DecisionCache:
    """Hash-keyed semantic decision cache that never stores source text."""

    def __init__(self, path: Path, *, source_checksum: str) -> None:
        self.path = Path(path)
        self.source_checksum = source_checksum
        self._entries: dict[tuple[str, int, str], SemanticDecision] = {}
        if self.path.is_file():
            self._load()

    def get(self, event: LivestreamEvent) -> SemanticDecision | None:
        """Return a cached decision for the exact source event text hash."""
        return self._entries.get(self._key(event))

    def put(self, event: LivestreamEvent, decision: SemanticDecision) -> None:
        """Persist one accepted decision without persisting the source text."""
        key = self._key(event)
        if key in self._entries:
            return
        payload = {
            "source_checksum": self.source_checksum,
            "source_sequence": event.sequence,
            "text_hash": key[2],
            "keep": decision.keep,
            "intent": decision.intent,
            "text_zh": decision.text_zh,
            "reason": decision.reason,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._entries[key] = decision

    def _key(self, event: LivestreamEvent) -> tuple[str, int, str]:
        return (
            self.source_checksum,
            event.sequence,
            hashlib.sha256(event.text.encode("utf-8")).hexdigest(),
        )

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            key = (
                str(value["source_checksum"]),
                int(value["source_sequence"]),
                str(value["text_hash"]),
            )
            self._entries[key] = SemanticDecision(
                sequence=int(value["source_sequence"]),
                keep=bool(value["keep"]),
                intent=str(value["intent"]),
                text_zh=str(value["text_zh"]),
                reason=str(value.get("reason", "unrecognized_intent")),
            )


@dataclass(frozen=True, slots=True)
class DropRecord:
    """Auditable drop record that never copies source text."""

    source_sequence: int
    text_hash: str
    reason: str


@dataclass(slots=True)
class CleaningResult:
    """Cleaned real events and aggregate cleaning evidence."""

    events: list[LivestreamEvent] = field(default_factory=list)
    drops: list[DropRecord] = field(default_factory=list)
    translated_count: int = 0
    intent_counts: dict[str, int] = field(default_factory=dict)


class BalancedCleaner:
    """Apply deterministic balanced rules before contextual semantic processing."""

    def __init__(
        self,
        *,
        processor: SemanticProcessor,
        context_window_ms: int = 20_000,
        duplicate_window_ms: int = 30_000,
        batch_size: int = 40,
        cache: DecisionCache | None = None,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._processor = processor
        self._context_window_ms = context_window_ms
        self._duplicate_window_ms = duplicate_window_ms
        self._batch_size = batch_size
        self._cache = cache
        self._max_concurrency = max_concurrency

    async def clean(self, events: list[LivestreamEvent]) -> CleaningResult:
        """Return a resequenced Chinese real-only stream and hash-only drop evidence."""
        kept: list[tuple[LivestreamEvent, str, str]] = []
        drops: list[DropRecord] = []
        semantic_requests: list[SemanticRequest] = []
        semantic_sequences: set[int] = set()
        decisions: dict[int, SemanticDecision] = {}
        events_by_sequence = {event.sequence: event for event in events}
        last_kept_by_actor_text: dict[tuple[str, str], int] = {}
        normalized_counts = Counter(
            _normalize_for_duplicate(event.text)
            for event in events
            if event.event_type in _REPLYABLE_TYPES
            and len(_normalize_for_duplicate(event.text)) >= 24
        )
        kept_copypasta: set[str] = set()

        for index, event in enumerate(events):
            if event.event_type not in _REPLYABLE_TYPES:
                kept.append((event, event.text, "non_replyable"))
                continue
            text = event.text.strip()
            drop_reason = _deterministic_drop_reason(text)
            normalized = _normalize_for_duplicate(text)
            if drop_reason is None and normalized_counts[normalized] >= 3:
                if normalized in kept_copypasta:
                    drop_reason = "copypasta"
                else:
                    kept_copypasta.add(normalized)
            duplicate_key = (event.actor_id, normalized)
            last_offset = last_kept_by_actor_text.get(duplicate_key)
            if (
                drop_reason is None
                and last_offset is not None
                and event.offset_ms - last_offset <= self._duplicate_window_ms
            ):
                drop_reason = "same_actor_duplicate"
            if drop_reason is not None:
                drops.append(_drop(event, drop_reason))
                continue
            if is_chinese_dominant(text):
                intent = _infer_chinese_intent(text)
                if intent is not None:
                    kept.append((event, text, intent))
                    last_kept_by_actor_text[duplicate_key] = event.offset_ms
                    continue
            semantic_sequences.add(event.sequence)
            cached = self._cache.get(event) if self._cache is not None else None
            if cached is not None:
                decisions[event.sequence] = cached
                last_kept_by_actor_text[duplicate_key] = event.offset_ms
                continue
            semantic_requests.append(self._semantic_request(events, index))
            last_kept_by_actor_text[duplicate_key] = event.offset_ms

        batches = [
            semantic_requests[start : start + self._batch_size]
            for start in range(0, len(semantic_requests), self._batch_size)
        ]
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def process_batch(batch: list[SemanticRequest]) -> list[SemanticDecision]:
            async with semaphore:
                batch_decisions = await self._processor.process_batch(batch)
            if self._cache is not None:
                for decision in batch_decisions:
                    self._cache.put(events_by_sequence[decision.sequence], decision)
            return batch_decisions

        batch_results = await asyncio.gather(*(process_batch(batch) for batch in batches))
        for batch_decisions in batch_results:
            for decision in batch_decisions:
                decisions[decision.sequence] = decision
        if set(decisions) != semantic_sequences:
            raise RuntimeError("semantic processor returned incomplete or unexpected decisions")

        translated_count = 0
        for source_sequence in sorted(semantic_sequences):
            event = events_by_sequence[source_sequence]
            decision = decisions[source_sequence]
            if not decision.keep:
                drops.append(_drop(event, decision.reason))
                continue
            text_zh = localize_embedded_terms(decision.text_zh.strip())
            if not text_zh:
                raise RuntimeError("semantic processor returned empty retained text")
            kept.append((event, text_zh, decision.intent))
            if text_zh != event.text.strip():
                translated_count += 1

        kept.sort(key=lambda item: (item[0].offset_ms, item[0].sequence))
        cleaned_events = [
            _as_real_event(event, sequence, text=text, intent=intent)
            for sequence, (event, text, intent) in enumerate(kept)
        ]
        intent_counts = Counter(
            str(event.payload["intent"])
            for event in cleaned_events
            if event.event_type in _REPLYABLE_TYPES
        )
        drops.sort(key=lambda item: item.source_sequence)
        return CleaningResult(
            events=cleaned_events,
            drops=drops,
            translated_count=translated_count,
            intent_counts=dict(sorted(intent_counts.items())),
        )

    def _semantic_request(
        self,
        events: list[LivestreamEvent],
        index: int,
    ) -> SemanticRequest:
        event = events[index]
        before = [
            _context(candidate)
            for candidate in events[max(0, index - 3) : index]
            if candidate.event_type in _REPLYABLE_TYPES
            and event.offset_ms - candidate.offset_ms <= self._context_window_ms
        ]
        after = [
            _context(candidate)
            for candidate in events[index + 1 : index + 4]
            if candidate.event_type in _REPLYABLE_TYPES
            and candidate.offset_ms - event.offset_ms <= self._context_window_ms
        ]
        return SemanticRequest(
            sequence=event.sequence,
            text=event.text,
            context_before=tuple(before),
            context_after=tuple(after),
        )


def localize_embedded_terms(text: str) -> str:
    """Normalize observed embedded chat emotes and ordinary terms into Chinese."""
    localized = text
    for pattern, replacement in _EMBEDDED_TERM_TRANSLATIONS:
        localized = pattern.sub(replacement, localized)
    return localized


def _deterministic_drop_reason(text: str) -> str | None:
    if not text:
        return "empty"
    if re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]", text) is None:
        return "symbol_only"
    if _LAUGHTER_ONLY.fullmatch(text):
        return "laughter_only"
    folded = text.casefold()
    emote_candidate = folded.strip(" \t\r\n!?！？~～.,。，")
    if emote_candidate in _EMOTES:
        return "emote_only"
    if folded in _MEANINGLESS_ABBREVIATIONS or _O7_NOISE.fullmatch(folded):
        return "meaningless_abbreviation"
    return None


def _normalize_for_duplicate(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", "", text.casefold())


def _infer_chinese_intent(text: str) -> str | None:
    if any(marker in text for marker in _QUESTION_MARKERS):
        return "question"
    if any(marker in text for marker in _INSTRUCTION_MARKERS):
        return "game_instruction"
    if any(marker in text for marker in _GREETING_MARKERS):
        return "greeting"
    if any(marker in text for marker in _CORRECTION_MARKERS):
        return "correction"
    if any(marker in text for marker in _EMOTION_MARKERS):
        return "emotion"
    chinese_chars = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
    if len(chinese_chars) >= 6 and len(set(chinese_chars)) / len(chinese_chars) >= 0.4:
        return "opinion"
    return None


def _drop(event: LivestreamEvent, reason: str) -> DropRecord:
    return DropRecord(
        source_sequence=event.sequence,
        text_hash=hashlib.sha256(event.text.encode("utf-8")).hexdigest(),
        reason=reason,
    )


def _context(event: LivestreamEvent) -> ContextMessage:
    return ContextMessage(sequence=event.sequence, offset_ms=event.offset_ms, text=event.text)


def _as_real_event(
    event: LivestreamEvent,
    sequence: int,
    *,
    text: str,
    intent: str,
) -> LivestreamEvent:
    payload = dict(event.payload)
    payload.update(
        {
            "origin": "real",
            "source_sequence": event.sequence,
            "intent": intent,
        },
    )
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=event.offset_ms,
        event_type=event.event_type,
        actor_id=event.actor_id,
        text=text,
        payload=payload,
    )
