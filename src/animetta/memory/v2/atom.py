"""MemoryAtom — unified memory atom model.

All memory types (conversation turns, episode summaries, semantic knowledge,
emergent memes) are projections of the same MemoryAtom at different layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum


class Layer(IntEnum):
    """Memory abstraction layers. Higher = more abstract / consolidated."""
    RAW = 0       # Raw conversation turn
    EPISODIC = 1  # Compiled episode summary
    SEMANTIC = 2  # Digested semantic knowledge
    EMERGENT = 3  # Emergent meme or synthesis


class MemoryScope(StrEnum):
    """Livestream memory domains sharing one physical corpus."""

    CHARACTER = "character"
    COMMUNITY = "community"
    VIEWER = "viewer"
    STREAM = "stream"
    WORLD = "world"


class MemoryVisibility(StrEnum):
    """Who may receive an atom during scoped recall."""

    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


class RelationType:
    """Types of relationships between memory atoms."""
    UPDATES = "UPDATES"
    EXTENDS = "EXTENDS"
    DERIVES = "DERIVES"
    EVOKES = "EVOKES"
    CONTRADICTS = "CONTRADICTS"
    CONSOLIDATED_INTO = "CONSOLIDATED_INTO"


@dataclass
class Relation:
    """A directed relationship between two memory atoms."""
    source_id: str
    target_id: str
    relation_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)


@dataclass
class MemoryAtom:
    """Unified memory atom — the fundamental unit of living memory.

    Every memory, regardless of its layer of abstraction, is a MemoryAtom.
    What changes between layers is the content's level of detail and the
    atom's lifecycle parameters.

    Bi-temporal design:
      occurred_at  — when the fact actually happened
      rewritten_at — when the memory was last altered by reconsolidation
      For a never-recalled memory: occurred_at == rewritten_at
      For a memory recalled 10 times: rewritten_at >> occurred_at, version > 1
    """

    # ── Identity ──
    id: str
    layer: Layer
    content: str
    occurred_at: datetime

    # ── Content ──
    summary: str | None = None

    # ── Bi-temporal (the soul of living memory) ──
    rewritten_at: datetime | None = None
    version: int = 1
    version_chain: list[str] = field(default_factory=list)

    # ── Vitality metrics ──
    confidence: float = 0.5
    salience: float = 0.5
    retrieval_count: int = 0
    last_accessed_at: datetime | None = None

    # ── Emotion vector (VAD: Valence / Arousal / Dominance) ──
    emotion_valence: float = 0.0     # -1.0 (negative) to +1.0 (positive)
    emotion_arousal: float = 0.0     # 0.0 (calm) to 1.0 (intense)
    emotion_dominance: float = 0.0   # -1.0 (passive) to +1.0 (dominant)

    # ── Knowledge graph ──
    source_ids: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # ── Livestream identity and policy ──
    scope: MemoryScope = MemoryScope.COMMUNITY
    visibility: MemoryVisibility = MemoryVisibility.INTERNAL
    subject_ids: list[str] = field(default_factory=list)
    origin: dict = field(default_factory=dict)
    trust_level: float = 0.5
    retention_policy: str = "standard"
    index_state: str = "pending"

    # ── Metabolism parameters ──
    decay_rate: float = 0.1
    forget_at: datetime | None = None
    is_archived: bool = False

    def __post_init__(self):
        if self.rewritten_at is None:
            self.rewritten_at = self.occurred_at

    @property
    def is_recalled(self) -> bool:
        """Has this memory ever been recalled? (rewritten_at > occurred_at)"""
        return self.rewritten_at > self.occurred_at

    @property
    def recall_age_hours(self) -> float | None:
        """Hours since last recall, or None if never recalled."""
        if self.last_accessed_at is None:
            return None
        now = datetime.now(UTC)
        return (now - self.last_accessed_at).total_seconds() / 3600.0
