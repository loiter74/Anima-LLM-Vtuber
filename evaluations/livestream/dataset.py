"""Streaming dataset sanitization, manifest creation, and validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType

SCHEMA_VERSION = 1
SCHEMA_VERSION_V2 = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION, SCHEMA_VERSION_V2})
SANITIZER_VERSION = "1"
_REPLYABLE_TYPES = {
    LivestreamEventType.DANMAKU,
    LivestreamEventType.GIFT,
    LivestreamEventType.SUPER_CHAT,
}
_PROVENANCE_KEYS = frozenset(
    {"origin", "source_sequence", "intent", "scenario", "parent_sequence"},
)
_EVENT_KEYS = frozenset({"sequence", "offset_ms", "event_type", "actor_id", "text", "payload"})
_BANNED_SOURCE_KEYS = frozenset(
    {
        "absolute_time",
        "comment_id",
        "login",
        "nickname",
        "raw_payload",
        "room_id",
        "source_url",
        "uid",
        "uname",
        "user_id",
        "vod_id",
    }
)
_PROCESSING_STRING_FIELDS = frozenset(
    {
        "profile",
        "target_language",
        "cleaner_version",
        "prompt_version",
        "provider",
        "model",
    }
)
_PAYLOAD_KEYS: dict[LivestreamEventType, frozenset[str]] = {
    LivestreamEventType.DANMAKU: _PROVENANCE_KEYS,
    LivestreamEventType.GIFT: frozenset({"gift_name", "gift_num"}) | _PROVENANCE_KEYS,
    LivestreamEventType.SUPER_CHAT: frozenset({"price"}) | _PROVENANCE_KEYS,
    LivestreamEventType.ENTER: frozenset(),
    LivestreamEventType.FOLLOW: frozenset(),
    LivestreamEventType.LIKE_BATCH: frozenset({"count"}),
    LivestreamEventType.POPULARITY_SNAPSHOT: frozenset({"popularity"}),
    LivestreamEventType.CONNECTION_STATE: frozenset({"connected", "message"}),
    LivestreamEventType.UNKNOWN: frozenset({"command"}),
}
_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE), "[邮箱]"),
    (re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"), "[电话]"),
    (re.compile(r"https?://[^\s]+", re.IGNORECASE), "[链接]"),
    (re.compile(r"@[A-Za-z0-9_\-\u4e00-\u9fff]+"), "[账号]"),
    (
        re.compile(r"(?:QQ|微信|VX|WeChat)\s*[:：]?\s*[A-Za-z0-9_-]{5,}", re.IGNORECASE),
        "[账号]",
    ),
    (re.compile(r"(?:我叫|姓名\s*[:：])\s*[\u4e00-\u9fff]{2,4}"), "姓名[姓名]"),
)
_SYNTHETIC_ACTOR_PATTERN = re.compile(r"synthetic_\d{4}")
_REAL_ACTOR_PATTERN = re.compile(r"viewer_\d{4}")
_SYNTHETIC_PREFIX = "[合成补充]"
_ALLOWED_LATIN_TERMS = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:GPS(?:\s*-\s*|\s+)sama|Fus\s+Ro\s+Dah|Fus|Ro|Dah|Vo|Neuro-sama|Neuro|Skyrim|"
    r"VTuber|Bilibili|Twitch|Live2D|NPC|AI|SC|Qwen|Aura|GPS)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_ENGLISH_SENTENCE = re.compile(r"\b(?:[A-Za-z]{2,}[\s,.'!?-]+){3,}[A-Za-z]{2,}\b")
_LATIN_TERM = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*")


class HeatTier(StrEnum):
    """Replyable-message workload tiers measured per 60-second window."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_HEAT_LIMITS = {
    HeatTier.LOW: (1, 10),
    HeatTier.MEDIUM: (11, 60),
    HeatTier.HIGH: (61, 300),
}


@dataclass(slots=True)
class DatasetValidationResult:
    """Validation result with stable machine-readable rejection codes."""

    valid: bool
    errors: list[dict[str, str]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    events: list[LivestreamEvent] = field(default_factory=list)

    @property
    def error_codes(self) -> list[str]:
        return [error["code"] for error in self.errors]


class EventSanitizer:
    """Sanitize one capture in memory without persisting source identities."""

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    def sanitize(self, event: LivestreamEvent) -> LivestreamEvent:
        """Return a detached event containing only dataset-safe fields."""
        synthetic_actor = (
            event.payload.get("origin") == "synthetic"
            and _SYNTHETIC_ACTOR_PATTERN.fullmatch(event.actor_id) is not None
        )
        actor_key = self._actor_key(event)
        actor_alias = (
            event.actor_id if synthetic_actor else self._alias(actor_key) if actor_key else ""
        )
        text = self._sanitize_text(event.text, event.actor_id, actor_alias)
        allowed = _PAYLOAD_KEYS[event.event_type]
        payload = {
            key: self._sanitize_value(value)
            for key, value in event.payload.items()
            if key in allowed
        }
        return LivestreamEvent(
            sequence=event.sequence,
            offset_ms=event.offset_ms,
            event_type=event.event_type,
            actor_id=actor_alias,
            text=text,
            payload=payload,
        )

    def _actor_key(self, event: LivestreamEvent) -> str:
        raw_id = event.payload.get("user_id")
        if raw_id not in {None, "", 0, "0"}:
            return f"uid:{raw_id}"
        return f"name:{event.actor_id}" if event.actor_id else ""

    def _alias(self, actor_key: str) -> str:
        alias = self._aliases.get(actor_key)
        if alias is None:
            alias = f"viewer_{len(self._aliases) + 1:04d}"
            self._aliases[actor_key] = alias
        return alias

    def _sanitize_text(self, value: str, actor: str, alias: str) -> str:
        clean = value
        if actor:
            clean = re.sub(re.escape(actor), alias or "[昵称]", clean, flags=re.IGNORECASE)
        for pattern, replacement in _SENSITIVE_PATTERNS:
            clean = pattern.sub(replacement, clean)
        return clean

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            clean = value
            for pattern, replacement in _SENSITIVE_PATTERNS:
                clean = pattern.sub(replacement, clean)
            return clean
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return str(value)[:128]


class DatasetWriter:
    """Write already-sanitized events incrementally and finalize a manifest."""

    def __init__(
        self,
        dataset_dir: Path,
        *,
        dataset_id: str,
        heat_tier: HeatTier,
        sanitizer: EventSanitizer | None = None,
        collector_version: str = "1",
        schema_version: int = SCHEMA_VERSION,
        parent_dataset: dict[str, object] | None = None,
        processing: dict[str, object] | None = None,
        cleaning_counts: dict[str, int] | None = None,
        derivation: dict[str, object] | None = None,
        variant: str | None = None,
        synthetic_ratio: float = 0.0,
    ) -> None:
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported dataset schema_version: {schema_version}")
        if schema_version == SCHEMA_VERSION_V2:
            if not parent_dataset or not processing or cleaning_counts is None or not variant:
                raise ValueError(
                    "schema v2 requires parent_dataset, processing, cleaning_counts, and variant",
                )
            if variant not in {"clean-real", "clean-enriched"}:
                raise ValueError("schema v2 variant must be clean-real or clean-enriched")
            if synthetic_ratio < 0:
                raise ValueError("synthetic_ratio must not be negative")
            if any(
                not isinstance(cleaning_counts.get(key), int) or int(cleaning_counts[key]) < 0
                for key in ("dropped", "translated")
            ):
                raise ValueError("schema v2 cleaning counts must be non-negative integers")
        self.dataset_dir = Path(dataset_dir)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_id = dataset_id
        self.heat_tier = HeatTier(heat_tier)
        self.sanitizer = sanitizer or EventSanitizer()
        self.collector_version = collector_version
        self.schema_version = schema_version
        self.parent_dataset = dict(parent_dataset or {})
        self.processing = dict(processing or {})
        self.cleaning_counts = dict(cleaning_counts or {})
        self.derivation = dict(derivation) if derivation is not None else None
        self.variant = variant
        self.synthetic_ratio = float(synthetic_ratio)
        self._events_path = self.dataset_dir / "events.jsonl"
        self._file: TextIO = self._events_path.open("w", encoding="utf-8", newline="\n")
        self._counts: Counter[str] = Counter()
        self._replyable_offsets: list[int] = []
        self._real_replyable_offsets: list[int] = []
        self._event_count = 0
        self._closed = False

    def write(self, event: LivestreamEvent) -> LivestreamEvent:
        """Sanitize and persist one event without retaining its source payload."""
        if self._closed:
            raise RuntimeError("dataset writer is already finalized")
        clean = self.sanitizer.sanitize(event)
        self._file.write(
            json.dumps(clean.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n",
        )
        self._counts[clean.event_type.value] += 1
        self._event_count += 1
        if clean.event_type in _REPLYABLE_TYPES:
            self._replyable_offsets.append(clean.offset_ms)
            if clean.payload.get("origin", "real") != "synthetic":
                self._real_replyable_offsets.append(clean.offset_ms)
        return clean

    def abort(self) -> None:
        """Close an unfinished dataset so its staging directory can be removed."""
        if self._closed:
            return
        self._file.close()
        self._closed = True

    def finalize(
        self,
        *,
        duration_ms: int,
        capture_derivation: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        """Close the stream and atomically define its verifiable manifest."""
        if self._closed:
            raise RuntimeError("dataset writer is already finalized")
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        self._file.flush()
        self._file.close()
        self._closed = True
        canonical_offsets = (
            self._real_replyable_offsets
            if self.schema_version == SCHEMA_VERSION_V2
            else self._replyable_offsets
        )
        workload = _compute_workload(
            canonical_offsets,
            duration_ms=duration_ms,
            heat_tier=self.heat_tier,
            rolling=self.schema_version == SCHEMA_VERSION_V2,
        )
        manifest: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "heat_tier": self.heat_tier.value,
            "duration_ms": duration_ms,
            "event_count": self._event_count,
            "event_counts": dict(sorted(self._counts.items())),
            "workload": workload,
            "sanitizer_version": SANITIZER_VERSION,
            "collector_version": self.collector_version,
            "events_sha256": _sha256(self._events_path),
        }
        if capture_derivation is not None:
            manifest["capture_derivation"] = dict(capture_derivation)
        if self.schema_version == SCHEMA_VERSION_V2:
            synthetic_count = len(self._replyable_offsets) - len(self._real_replyable_offsets)
            cleaning_counts = {
                **self.cleaning_counts,
                "retained": len(self._real_replyable_offsets),
                "synthetic": synthetic_count,
            }
            manifest.update(
                {
                    "parent_dataset": self.parent_dataset,
                    "processing": self.processing,
                    "cleaning_counts": cleaning_counts,
                    "derivation": self.derivation,
                    "variant": self.variant,
                    "synthetic_ratio": self.synthetic_ratio,
                    "effective_workload": _compute_workload(
                        self._replyable_offsets,
                        duration_ms=duration_ms,
                        heat_tier=self.heat_tier,
                        rolling=True,
                    ),
                },
            )
        (self.dataset_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest


class DatasetValidator:
    """Validate schema, timeline, privacy, counts, workload, and checksum."""

    def validate(
        self,
        dataset_dir: Path,
        *,
        parent_dir: Path | None = None,
    ) -> DatasetValidationResult:
        dataset_dir = Path(dataset_dir)
        manifest_path = dataset_dir / "manifest.json"
        events_path = dataset_dir / "events.jsonl"
        errors: list[dict[str, str]] = []
        if not manifest_path.is_file() or not events_path.is_file():
            return DatasetValidationResult(
                valid=False,
                errors=[
                    self._error(
                        "missing_dataset_file", "manifest.json and events.jsonl are required"
                    )
                ],
            )

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DatasetValidationResult(
                valid=False,
                errors=[self._error("invalid_manifest", "manifest.json is not valid JSON")],
            )

        schema_version = manifest.get("schema_version")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            errors.append(self._error("unknown_schema", "unsupported dataset schema_version"))
        expected_checksum = manifest.get("events_sha256")
        if expected_checksum != _sha256(events_path):
            errors.append(
                self._error("checksum_mismatch", "events.jsonl checksum does not match manifest")
            )

        events = self._load_events(events_path, errors, schema_version=schema_version)
        self._validate_timeline(events, errors)
        actual_counts = Counter(event.event_type.value for event in events)
        if manifest.get("event_count") != len(events) or manifest.get("event_counts") != dict(
            sorted(actual_counts.items())
        ):
            errors.append(
                self._error("event_count_mismatch", "manifest event counts do not match JSONL")
            )
        if self._contains_sensitive_data(
            manifest,
            events_path,
            events,
            schema_version=schema_version,
        ):
            errors.append(
                self._error(
                    "privacy_violation", "dataset contains a raw identity or contact pattern"
                )
            )
        if schema_version == SCHEMA_VERSION_V2:
            parent_manifest = self._validate_parent(
                dataset_dir,
                manifest,
                errors,
                parent_dir=parent_dir,
            )
            self._validate_chinese(events, errors)
            self._validate_v2_provenance(manifest, events, errors)
            self._validate_v2_manifest(manifest, events, parent_manifest, errors)
        self._validate_workload(manifest, events, errors)
        return DatasetValidationResult(
            valid=not errors,
            errors=errors,
            manifest=manifest,
            events=events,
        )

    def _load_events(
        self,
        path: Path,
        errors: list[dict[str, str]],
        *,
        schema_version: object,
    ) -> list[LivestreamEvent]:
        events: list[LivestreamEvent] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError
                event_type = LivestreamEventType(value["event_type"])
                payload = value.get("payload", {})
                if not isinstance(payload, dict):
                    raise TypeError
                if schema_version == SCHEMA_VERSION_V2 and set(value) - _EVENT_KEYS:
                    errors.append(
                        self._error(
                            "invalid_event",
                            f"events.jsonl line {line_number} contains unknown event fields",
                        )
                    )
                extra_payload_keys = set(payload) - _PAYLOAD_KEYS[event_type]
                if extra_payload_keys:
                    errors.append(
                        self._error(
                            "payload_not_whitelisted",
                            "event payload contains non-whitelisted keys; "
                            f"line={line_number}; keys={','.join(sorted(extra_payload_keys))}",
                        )
                    )
                events.append(
                    LivestreamEvent(
                        sequence=int(value["sequence"]),
                        offset_ms=int(value["offset_ms"]),
                        event_type=event_type,
                        actor_id=str(value.get("actor_id", "")),
                        text=str(value.get("text", "")),
                        payload=dict(payload),
                    ),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                errors.append(
                    self._error("invalid_event", f"events.jsonl line {line_number} is invalid"),
                )
        return events

    def _validate_timeline(
        self,
        events: list[LivestreamEvent],
        errors: list[dict[str, str]],
    ) -> None:
        for index, event in enumerate(events):
            if (
                event.sequence != index
                or event.offset_ms < 0
                or (index > 0 and event.offset_ms < events[index - 1].offset_ms)
            ):
                errors.append(
                    self._error(
                        "invalid_timeline", "event sequence or relative timeline is out of order"
                    ),
                )
                return

    def _contains_sensitive_data(
        self,
        manifest: dict[str, Any],
        path: Path,
        events: list[LivestreamEvent],
        *,
        schema_version: object,
    ) -> bool:
        raw_text = path.read_text(encoding="utf-8")
        if any(pattern.search(raw_text) for pattern, _replacement in _SENSITIVE_PATTERNS):
            return True
        if _contains_banned_key(manifest):
            return True
        banned_pattern = "|".join(re.escape(key) for key in sorted(_BANNED_SOURCE_KEYS))
        if re.search(rf'"(?:{banned_pattern})"\s*:', raw_text, re.IGNORECASE):
            return True
        allowed_actor_patterns: tuple[re.Pattern[str], ...] = (_REAL_ACTOR_PATTERN,)
        if schema_version == SCHEMA_VERSION_V2:
            allowed_actor_patterns += (_SYNTHETIC_ACTOR_PATTERN,)
        return any(
            event.actor_id
            and not any(pattern.fullmatch(event.actor_id) for pattern in allowed_actor_patterns)
            for event in events
        )

    def _validate_workload(
        self,
        manifest: dict[str, Any],
        events: list[LivestreamEvent],
        errors: list[dict[str, str]],
    ) -> None:
        try:
            heat_tier = HeatTier(manifest["heat_tier"])
            duration_ms = int(manifest["duration_ms"])
        except (KeyError, TypeError, ValueError):
            errors.append(self._error("invalid_manifest", "heat_tier and duration_ms are required"))
            return
        schema_version = manifest.get("schema_version", SCHEMA_VERSION)
        offsets = [
            event.offset_ms
            for event in events
            if event.event_type in _REPLYABLE_TYPES
            and (
                schema_version == SCHEMA_VERSION
                or event.payload.get("origin", "real") != "synthetic"
            )
        ]
        workload = _compute_workload(
            offsets,
            duration_ms=duration_ms,
            heat_tier=heat_tier,
            rolling=schema_version == SCHEMA_VERSION_V2,
        )
        if manifest.get("workload") != workload:
            errors.append(
                self._error("workload_mismatch", "manifest workload does not match JSONL events")
            )
        if schema_version == SCHEMA_VERSION_V2:
            effective_workload = _compute_workload(
                [event.offset_ms for event in events if event.event_type in _REPLYABLE_TYPES],
                duration_ms=duration_ms,
                heat_tier=heat_tier,
                rolling=True,
            )
            if manifest.get("effective_workload") != effective_workload:
                errors.append(
                    self._error(
                        "effective_workload_mismatch",
                        "manifest effective_workload does not match JSONL events",
                    )
                )
        if workload["qualification_ratio"] < 0.8:
            errors.append(
                self._error(
                    "heat_tier_mismatch",
                    "fewer than 80% of 60-second windows match the heat tier; "
                    f"tier={heat_tier.value}; "
                    f"qualification_ratio={workload['qualification_ratio']}",
                ),
            )

    def _validate_parent(
        self,
        dataset_dir: Path,
        manifest: dict[str, Any],
        errors: list[dict[str, str]],
        *,
        parent_dir: Path | None,
    ) -> dict[str, Any] | None:
        parent = manifest.get("parent_dataset")
        if not isinstance(parent, dict):
            errors.append(
                self._error("invalid_parent_dataset", "schema v2 parent_dataset is required")
            )
            return None
        dataset_id = parent.get("dataset_id")
        expected_checksum = parent.get("events_sha256")
        if not isinstance(dataset_id, str) or not isinstance(expected_checksum, str):
            errors.append(
                self._error("invalid_parent_dataset", "parent dataset ID and checksum are required")
            )
            return None
        resolved_parent = (
            Path(parent_dir)
            if parent_dir is not None
            else self._discover_parent(dataset_dir.parent, dataset_id, expected_checksum)
        )
        parent_manifest_path = resolved_parent / "manifest.json"
        parent_events_path = resolved_parent / "events.jsonl"
        try:
            parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(self._error("parent_dataset_missing", "parent dataset could not be read"))
            return None
        if (
            parent_manifest.get("dataset_id") != dataset_id
            or not parent_events_path.is_file()
            or _sha256(parent_events_path) != expected_checksum
        ):
            errors.append(
                self._error(
                    "parent_dataset_mismatch", "parent dataset identity or checksum does not match"
                )
            )
            return None
        return parent_manifest

    @staticmethod
    def _discover_parent(root: Path, dataset_id: str, expected_checksum: str) -> Path:
        """Locate a co-located parent by manifest identity, not directory spelling."""
        conventional = root / dataset_id
        if conventional.is_dir():
            return conventional
        identity_match: Path | None = None
        try:
            candidates = sorted(
                (candidate for candidate in root.iterdir() if candidate.is_dir()),
                key=lambda candidate: candidate.name,
            )
        except OSError:
            return conventional
        for candidate in candidates:
            try:
                manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("dataset_id") != dataset_id:
                continue
            identity_match = candidate
            if manifest.get("events_sha256") == expected_checksum:
                return candidate
        return identity_match or conventional

    def _validate_chinese(
        self,
        events: list[LivestreamEvent],
        errors: list[dict[str, str]],
    ) -> None:
        invalid_sequences = [
            event.sequence
            for event in events
            if event.event_type in _REPLYABLE_TYPES and not is_chinese_dominant(event.text)
        ]
        if invalid_sequences:
            sequence_summary = ",".join(str(value) for value in invalid_sequences[:20])
            if len(invalid_sequences) > 20:
                sequence_summary += ",..."
            errors.append(
                self._error(
                    "non_chinese_text",
                    "schema v2 replyable text must be Chinese-dominant; "
                    f"sequences={sequence_summary}",
                )
            )

    def _validate_v2_provenance(
        self,
        manifest: dict[str, Any],
        events: list[LivestreamEvent],
        errors: list[dict[str, str]],
    ) -> None:
        replyable = [event for event in events if event.event_type in _REPLYABLE_TYPES]
        synthetic = [event for event in replyable if event.payload.get("origin") == "synthetic"]
        real = [event for event in replyable if event.payload.get("origin") != "synthetic"]
        invalid_synthetic = any(
            not event.text.startswith(_SYNTHETIC_PREFIX)
            or _SYNTHETIC_ACTOR_PATTERN.fullmatch(event.actor_id) is None
            or not _nonempty_string(event.payload.get("scenario"))
            or not _nonnegative_int(event.payload.get("parent_sequence"))
            or not _nonempty_string(event.payload.get("intent"))
            or "source_sequence" in event.payload
            for event in synthetic
        )
        disguised_synthetic = any(
            event.actor_id.startswith("synthetic_") or event.text.startswith(_SYNTHETIC_PREFIX)
            for event in real
        )
        if invalid_synthetic or disguised_synthetic:
            errors.append(
                self._error(
                    "invalid_synthetic_marker",
                    "synthetic events require matching text, actor, and payload markers",
                ),
            )

        invalid_real = any(
            event.payload.get("origin") != "real"
            or not _nonnegative_int(event.payload.get("source_sequence"))
            or not _nonempty_string(event.payload.get("intent"))
            or "scenario" in event.payload
            or "parent_sequence" in event.payload
            for event in real
        )
        if invalid_real:
            errors.append(
                self._error(
                    "invalid_real_provenance",
                    "real events require origin=real, integer source_sequence, and intent",
                )
            )

        variant = manifest.get("variant")
        try:
            ratio = float(manifest.get("synthetic_ratio", 0.0))
        except (TypeError, ValueError):
            ratio = -1.0
        expected_synthetic = math.ceil(len(real) * ratio) if ratio >= 0 else -1
        if (
            variant not in {"clean-real", "clean-enriched"}
            or (variant == "clean-real" and (synthetic or ratio != 0.0))
            or (variant == "clean-enriched" and len(synthetic) != expected_synthetic)
        ):
            errors.append(
                self._error(
                    "synthetic_ratio_mismatch",
                    "synthetic event count does not match the dataset variant and ratio",
                ),
            )

    def _validate_v2_manifest(
        self,
        manifest: dict[str, Any],
        events: list[LivestreamEvent],
        parent_manifest: dict[str, Any] | None,
        errors: list[dict[str, str]],
    ) -> None:
        processing = manifest.get("processing")
        processing_valid = isinstance(processing, dict) and all(
            _nonempty_string(processing.get(field)) for field in _PROCESSING_STRING_FIELDS
        )
        processing_valid = bool(
            processing_valid
            and processing.get("target_language") == "zh-CN"
            and _nonnegative_int(processing.get("seed"))
        )
        if not processing_valid:
            errors.append(
                self._error(
                    "invalid_processing",
                    "schema v2 processing metadata is incomplete or invalid",
                )
            )

        counts = manifest.get("cleaning_counts")
        count_keys = {"retained", "dropped", "translated", "synthetic"}
        if (
            not isinstance(counts, dict)
            or set(counts) != count_keys
            or any(not _nonnegative_int(counts.get(key)) for key in count_keys)
        ):
            errors.append(
                self._error(
                    "cleaning_counts_mismatch",
                    "schema v2 cleaning_counts are incomplete or invalid",
                )
            )
            return

        replyable = [event for event in events if event.event_type in _REPLYABLE_TYPES]
        real_count = sum(event.payload.get("origin") == "real" for event in replyable)
        synthetic_count = sum(event.payload.get("origin") == "synthetic" for event in replyable)
        parent_is_v2 = bool(
            parent_manifest is not None
            and parent_manifest.get("schema_version") == SCHEMA_VERSION_V2
        )
        consistent = (
            counts["retained"] == real_count
            and counts["synthetic"] == synthetic_count
            and (parent_is_v2 or counts["translated"] <= counts["retained"])
        )
        if parent_manifest is not None:
            parent_counts = parent_manifest.get("cleaning_counts")
            parent_replyable = _manifest_replyable_count(parent_manifest)
            if manifest.get("variant") == "clean-enriched":
                consistent = bool(
                    consistent
                    and isinstance(parent_counts, dict)
                    and real_count == int(parent_counts.get("retained", -1))
                    and counts["dropped"] == int(parent_counts.get("dropped", -1))
                    and counts["translated"] == int(parent_counts.get("translated", -1))
                )
            else:
                consistent = bool(consistent and counts["dropped"] == parent_replyable - real_count)
                if isinstance(parent_counts, dict):
                    consistent = bool(
                        consistent
                        and counts["translated"] == int(parent_counts.get("translated", -1))
                    )
        if not consistent:
            errors.append(
                self._error(
                    "cleaning_counts_mismatch",
                    "manifest cleaning_counts do not match JSONL events and parent provenance",
                )
            )

    @staticmethod
    def _error(code: str, message: str) -> dict[str, str]:
        return {"code": code, "message": message}


def _contains_banned_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _BANNED_SOURCE_KEYS or _contains_banned_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_banned_key(item) for item in value)
    return False


def _manifest_replyable_count(manifest: dict[str, Any]) -> int:
    event_counts = manifest.get("event_counts")
    if not isinstance(event_counts, dict):
        return -1
    return sum(int(event_counts.get(event_type.value, 0)) for event_type in _REPLYABLE_TYPES)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _compute_workload(
    replyable_offsets: list[int],
    *,
    duration_ms: int,
    heat_tier: HeatTier,
    rolling: bool = False,
) -> dict[str, float | int]:
    if rolling:
        starts = list(range(0, max(0, duration_ms - 60_000) + 1, 1_000))
        if not starts:
            starts = [0]
    else:
        starts = [index * 60_000 for index in range(max(1, math.ceil(duration_ms / 60_000)))]
    rates = []
    for start in starts:
        end = min(duration_ms, start + 60_000)
        rates.append(sum(start <= offset < end for offset in replyable_offsets))
    lower, upper = _HEAT_LIMITS[heat_tier]
    matching = sum(lower <= rate <= upper for rate in rates)
    workload: dict[str, float | int] = {
        "window_seconds": 60,
        "window_count": len(starts),
        "rate_min": min(rates),
        "rate_max": max(rates),
        "rate_p50": _percentile(rates, 0.50),
        "rate_p95": _percentile(rates, 0.95),
        "qualification_ratio": round(matching / len(starts), 6),
    }
    if rolling:
        workload["window_step_ms"] = 1_000
    return workload


def is_chinese_dominant(text: str) -> bool:
    """Return whether user-visible text satisfies the shared zh-CN output policy."""
    candidate = text.removeprefix(_SYNTHETIC_PREFIX).strip()
    candidate = _ALLOWED_LATIN_TERMS.sub("", candidate)
    if _ENGLISH_SENTENCE.search(candidate):
        return False
    chinese_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", candidate))
    if chinese_count == 0:
        return False
    latin_terms = _LATIN_TERM.findall(candidate)
    if len(latin_terms) <= 2:
        return chinese_count > len(latin_terms)
    return len(latin_terms) <= 4 and chinese_count >= len(latin_terms) * 2


def _percentile(values: list[int], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
