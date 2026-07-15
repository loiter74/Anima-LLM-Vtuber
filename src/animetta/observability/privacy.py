"""Profile-aware content minimization applied before ledger persistence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from .domain import AttributeValue, ContentFacts, ErrorFacts, PrivacyMode
from .errors import normalize_error_type

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "atom_count",
        "atom_id",
        "character_count",
        "critical_path",
        "degradation_reason",
        "duration_ms",
        "error_type",
        "event_name",
        "index_backlog",
        "input_type",
        "language",
        "method",
        "model",
        "node_name",
        "outcome",
        "payload_size",
        "phase",
        "provider",
        "queue_depth",
        "result_count",
        "retryable",
        "revision",
        "runtime_profile",
        "source",
        "status",
        "strategy",
        "token_type",
        "token_count",
    }
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*)?bearer\s+[^\s,;]+")
_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[=:]\s*[^\s,;]+")


class ObservationContentPolicy:
    def __init__(self, mode: PrivacyMode, *, salt: str) -> None:
        if not salt:
            raise ValueError("observation digest salt must not be empty")
        self.mode = mode
        self._salt = salt.encode("utf-8")

    @classmethod
    def for_profile(cls, profile: str, *, salt: str) -> ObservationContentPolicy:
        normalized = profile.strip().lower()
        mode = (
            PrivacyMode.REDACTED
            if normalized in {"golden", "production", "prod"}
            else PrivacyMode.FULL
        )
        return cls(mode, salt=salt)

    def content_facts(self, text: str) -> ContentFacts:
        encoded = text.encode("utf-8")
        digest = hashlib.sha256(self._salt + b"\0" + encoded).hexdigest()
        return ContentFacts(
            text=text if self.mode is PrivacyMode.FULL else None,
            character_count=len(text),
            byte_count=len(encoded),
            digest=digest,
        )

    def filter_attributes(self, values: Mapping[str, object]) -> dict[str, AttributeValue]:
        filtered: dict[str, AttributeValue] = {}
        for key, value in values.items():
            if key not in _ALLOWED_ATTRIBUTES:
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                filtered[key] = value
        return filtered

    def sanitize_error(self, message: str, *, error_type: str) -> ErrorFacts:
        normalized_type = normalize_error_type(error_type).value
        summary = _BEARER_RE.sub("[REDACTED]", message)
        summary = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", summary)
        summary = " ".join(summary.split())[:200]
        return ErrorFacts(error_type=normalized_type, summary=summary)
