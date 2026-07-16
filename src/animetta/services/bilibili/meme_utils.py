"""Shared utilities for meme collection: parsing, candidate building, semantic extraction."""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from .models import CollectedVideo, MemeCandidate
from .text_utils import STOPWORDS

logger = logging.getLogger(__name__)


def parse_llm_json(raw: str) -> list[dict[str, Any]]:
    """Parse LLM JSON response into list of dicts.

    Handles markdown code fences and common wrapper keys.
    """
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
            for key in ("memes", "candidates", "results", "items"):
                if key in data:
                    return data[key]
            return [data]
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[MemeCollector] JSON parse failed: %s", e)
    return []


def build_candidates(
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
        candidates.append(
            MemeCandidate(
                text=text,
                context_hint=item.get("context_hint", ""),
                frequency=item.get("frequency", 1),
                source_videos=list(source_bvids),
                tags=item.get("tags", []),
                format_id=str(item.get("format_id") or ""),
                format_slots=item.get("format_slots") or {},
                format_confidence=item.get("format_confidence"),
                rendered_text=str(item.get("rendered_text") or ""),
                mode=str(item.get("mode") or ""),
            )
        )

    return candidates


def extract_semantic_phrases(
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
        logger.warning(
            "[MemeCollector] jieba not installed, "
            "falling back to char n-grams for semantic extraction"
        )
        fallback: Counter[str] = Counter()
        for text in texts:
            chars = list(text.strip())
            for n in range(2, min(5, len(chars) + 1)):
                for i in range(len(chars) - n + 1):
                    phrase = "".join(chars[i : i + n])
                    if phrase.strip() and not phrase.isdigit():
                        fallback[phrase] += 1
        return fallback.most_common(top_k)

    from math import log

    total_docs = len(texts)
    if total_docs == 0:
        return []

    tokenized = [list(jieba.cut(t)) for t in texts]

    ngram_counter: Counter[str] = Counter()
    doc_frequency: Counter[str] = Counter()

    for tokens in tokenized:
        seen_in_doc: set[str] = set()
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

    scored: list[tuple[str, int]] = []
    for phrase, count in ngram_counter.items():
        if count < 2:
            continue
        if phrase in STOPWORDS:
            continue
        df = doc_frequency.get(phrase, 1)
        idf = log((total_docs + 1) / (df + 1)) + 1
        score = count * idf
        scored.append((phrase, int(score)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
