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
        "actor_role",
        "arguments_byte_count",
        "arguments_character_count",
        "arguments_digest",
        "arguments_text",
        "audience",
        "approval_result",
        "character_count",
        "critical_path",
        "conversation_committed",
        "conversation_scope_kind",
        "conversation_window_pairs_after",
        "conversation_window_pairs_before",
        "degradation_reason",
        "duration_ms",
        "error_type",
        "event_name",
        "index_backlog",
        "input_type",
        "language",
        "method",
        "minecraft_command_id",
        "minecraft_request_id",
        "mcp_server",
        "model",
        "node_name",
        "outcome",
        "payload_size",
        "phase",
        "provider",
        "queue_depth",
        "result_byte_count",
        "result_character_count",
        "result_digest",
        "result_text",
        "result_count",
        "retryable",
        "retry_count",
        "revision",
        "runtime_profile",
        "source",
        "status",
        "strategy",
        "token_type",
        "token_count",
        "tool_call_id",
        "tool_effect",
        "tool_name",
        "tool_source",
        "usage_cached_input_cost_usd",
        "usage_cached_input_tokens",
        "usage_estimated",
        "usage_input_cost_usd",
        "usage_input_tokens",
        "usage_model",
        "usage_output_cost_usd",
        "usage_output_tokens",
        "usage_provider",
        "usage_schema_version",
        "usage_total_cost_usd",
        "live_session_id",
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
