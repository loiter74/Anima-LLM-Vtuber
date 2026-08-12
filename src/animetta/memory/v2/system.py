"""LivingMemorySystem — entry point for the living memory architecture.

Orchestrates: AtomStore → MemorySearch → EmotionalField → Reconsolidation → Metabolism.

Replaces MemorySystem with unified encode/recall API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from animetta.memory.v2.atom import (
    Layer,
    MemoryAtom,
    MemoryScope,
    MemoryVisibility,
    Relation,
    RelationType,
)
from animetta.memory.v2.character_filter import CharacterMemoryFilter
from animetta.memory.v2.compile import COMPILE_TRIGGERS, CompileEngine
from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.emotion_field import EmotionalField, VADVector
from animetta.memory.v2.metabolism import MetabolismScheduler
from animetta.memory.v2.reconsolidation import get_reconsolidation_client
from animetta.memory.v2.search import MemorySearch
from animetta.memory.v2.store import AtomStore

logger = logging.getLogger(__name__)


@dataclass
class RecallResult:
    """Result of a memory recall operation.

    atoms:    Recall output atoms sorted by emotion congruence.
             Each atom's `summary` field is the reconsolidated version
             (or original content if never recalled).
    profile:  User profile extracted from SEMANTIC layer atoms.
    memes:    Active memes from EMERGENT layer.
    """

    atoms: list[MemoryAtom] = field(default_factory=list)
    profile: dict = field(default_factory=dict)
    memes: list[MemoryAtom] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class LivingMemorySystem:
    """Living memory system — encode, recall, reconsolidate, metabolize.

    USAGE:
        system = LivingMemorySystem()
        await system.initialize()

        # Encode a conversation turn
        atom = await system.encode(
            user_input="今天喝了拿铁",
            agent_response="拿铁不错！",
            emotion_vad=VAD_MAP["happy"],
            session_id="s1",
        )

        # Recall memories with emotion bias
        result = await system.recall(
            query="咖啡",
            session_id="s1",
            current_emotion=VAD_MAP["happy"],
        )
        # result.atoms contain memories with summaries
        # Reconsolidation runs async in background
    """

    # Reconsolidation cooldown (minutes)
    RECONSOLIDATION_COOLDOWN_MINUTES = 30

    # Maximum atoms to reconsolidate per recall
    MAX_RECONSOLIDATION_PER_RECALL = 3

    # Minimum salience for reconsolidation
    MIN_RECONSOLIDATION_SALIENCE = 0.3

    def __init__(self, db_path: str = "memory_db/living_memory.sqlite"):
        self.store = AtomStore(db_path=db_path)
        self._initialized = False
        self._metabolism_task: asyncio.Task | None = None
        self._metabolism_interval = 6 * 3600  # 6 hours in seconds
        self.compile_engine = CompileEngine()

    async def initialize(self) -> None:
        await self.store.initialize()
        self._initialized = True

    async def start_metabolism(self) -> None:
        """Start the background metabolism loop (decay + consolidation + compile)."""
        if self._metabolism_task and not self._metabolism_task.done():
            return
        self._metabolism_task = asyncio.create_task(self._metabolism_loop())
        logger.info("Metabolism loop started (every 6h)")

    async def stop_metabolism(self) -> None:
        """Stop the background metabolism loop."""
        if self._metabolism_task and not self._metabolism_task.done():
            self._metabolism_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._metabolism_task
        logger.info("Metabolism loop stopped")

    async def _metabolism_loop(self) -> None:
        """Background loop: periodically run metabolism tick."""
        while True:
            try:
                await asyncio.sleep(self._metabolism_interval)
                await self.run_metabolism_tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Metabolism tick failed: {e}")

    async def run_metabolism_tick(self) -> None:
        """Execute one metabolism tick through the public memory API."""
        await self._run_metabolism_tick()

    async def list_wiki_pages(self, limit: int = 50) -> list[dict[str, object]]:
        """Return active memory atoms as frontend-compatible wiki pages."""
        atoms = await self.store.get_all_active(limit=limit)
        return [self._atom_to_wiki_page(atom) for atom in atoms]

    async def list_memories(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        scope: str | None = None,
    ) -> dict[str, object]:
        """Return a revisioned, cursor-paginated canonical atom page."""
        try:
            offset = int(cursor or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("cursor must be a non-negative integer") from exc
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")
        page_size = max(1, min(int(limit), 100))
        atoms = await self.store.get_all_active(limit=1000)
        if scope:
            try:
                expected_scope = MemoryScope(scope)
            except ValueError as exc:
                raise ValueError(f"unknown memory scope: {scope}") from exc
            atoms = [atom for atom in atoms if atom.scope is expected_scope]
        page = atoms[offset : offset + page_size]
        next_offset = offset + len(page)
        index_health = self.store.get_index_health()
        return {
            "items": [self.atom_to_dto(atom) for atom in page],
            "revision": await self.store.get_revision(),
            "next_cursor": str(next_offset) if next_offset < len(atoms) else None,
            "total": len(atoms),
            "health": {
                "degraded": bool(index_health["degraded"]),
                "last_error": index_health["last_error"] or "",
                "index_backlog": await self.store.get_index_backlog(),
            },
        }

    async def get_memory(self, atom_id: str) -> dict[str, object] | None:
        atom = await self.store.get(atom_id)
        return self.atom_to_dto(atom) if atom is not None else None

    async def search_memories(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> dict[str, object]:
        if not query.strip():
            raise ValueError("query is required")
        atoms = await self.store.hybrid_search(query, max(1, min(limit, 100)))
        return {
            "items": [self.atom_to_dto(atom) for atom in atoms],
            "revision": await self.store.get_revision(),
            "next_cursor": None,
            "total": len(atoms),
        }

    async def pin_memory(
        self,
        atom_id: str,
        *,
        pinned: bool,
    ) -> dict[str, object] | None:
        atom = await self.store.get(atom_id)
        if atom is None:
            return None
        target_policy = "pinned" if pinned else "standard"
        if atom.retention_policy == target_policy:
            return self.atom_to_dto(atom)
        atom.retention_policy = target_policy
        if pinned:
            atom.forget_at = None
            atom.salience = max(atom.salience, 0.95)
        await self.store.update(atom)
        return self.atom_to_dto(atom)

    async def forget_memory(self, atom_id: str) -> dict[str, object] | None:
        atom = await self.store.get(atom_id)
        if atom is None:
            return None
        if atom.is_archived:
            return self.atom_to_dto(atom)
        atom.is_archived = True
        await self.store.update(atom)
        return self.atom_to_dto(atom)

    async def change_memory(
        self,
        atom_id: str,
        *,
        summary: str,
    ) -> dict[str, object] | None:
        corrected = summary.strip()
        if not corrected:
            raise ValueError("summary is required")
        atom = await self.store.get(atom_id)
        if atom is None:
            return None
        if atom.summary == corrected:
            return self.atom_to_dto(atom)
        updated = await self.store.create_version(
            atom_id,
            corrected,
            max(atom.confidence, 0.9),
            (
                atom.emotion_valence,
                atom.emotion_arousal,
                atom.emotion_dominance,
            ),
        )
        updated.origin = {**updated.origin, "corrected": True}
        updated.trust_level = 1.0
        await self.store.update(updated)
        return self.atom_to_dto(updated)

    @staticmethod
    def atom_to_dto(atom: MemoryAtom) -> dict[str, object]:
        """Serialize the single canonical backend/frontend atom contract."""
        layer_to_type = {
            Layer.RAW: "source",
            Layer.EPISODIC: "entity",
            Layer.SEMANTIC: "concept",
            Layer.EMERGENT: "synthesis",
        }
        updated_at = atom.rewritten_at or atom.occurred_at
        return {
            "id": atom.id,
            "path": atom.id,
            "title": atom.summary or atom.content[:80],
            "content": atom.content,
            "summary": atom.summary,
            "layer": atom.layer.name.lower(),
            "page_type": layer_to_type.get(atom.layer, atom.layer.name.lower()),
            "scope": atom.scope.value,
            "visibility": atom.visibility.value,
            "subject_ids": list(atom.subject_ids),
            "origin": dict(atom.origin),
            "confidence": float(atom.confidence),
            "salience": float(atom.salience),
            "trust_level": float(atom.trust_level),
            "retention_policy": atom.retention_policy,
            "index_state": atom.index_state,
            "relations": [
                {
                    "source_id": relation.source_id,
                    "target_id": relation.target_id,
                    "relation_type": (
                        relation.relation_type.value
                        if hasattr(relation.relation_type, "value")
                        else str(relation.relation_type)
                    ),
                    "created_at": relation.created_at.isoformat(),
                    "metadata": dict(relation.metadata),
                }
                for relation in atom.relations
            ],
            "tags": list(atom.tags),
            "source_ids": list(atom.source_ids),
            "version": atom.version,
            "is_archived": atom.is_archived,
            "occurred_at": atom.occurred_at.isoformat(),
            "updated_at": updated_at.isoformat(),
        }

    @staticmethod
    def _atom_to_wiki_page(atom: MemoryAtom) -> dict[str, object]:
        layer_to_type = {
            Layer.RAW: "source",
            Layer.EPISODIC: "entity",
            Layer.SEMANTIC: "concept",
            Layer.EMERGENT: "synthesis",
        }
        updated_at = atom.rewritten_at or atom.occurred_at
        return {
            "path": atom.id,
            "title": atom.summary or atom.content[:80],
            "content": atom.content,
            "page_type": layer_to_type.get(atom.layer, atom.layer.name.lower()),
            "tags": atom.tags or [],
            "updated_at": updated_at.isoformat() if updated_at else "",
        }

    async def _run_metabolism_tick(self) -> None:
        """Execute one metabolism tick: decay + compile + forget."""
        # Get all active atoms
        atoms = await self.store.get_all_active()
        if not atoms:
            return

        count = len(atoms)

        # Phase 1: Decay — recalculate salience
        for atom in atoms:
            atom.salience = MetabolismScheduler.compute_salience(atom)
            await self.store.update_salience(atom.id, atom.salience)

        # Phase 2: Compile — try layer progression
        await self._try_compile(atoms)

        # Phase 3: Forget — archive low-salience atoms
        threshold = MetabolismScheduler.adaptive_threshold(count)
        archived = await self.store.archive_below_threshold(threshold)
        if archived:
            logger.info(f"Metabolism: archived {archived} atoms (threshold={threshold:.3f})")

    async def _try_compile(self, atoms: list[MemoryAtom]) -> None:
        """Try compiling atoms up through layers."""
        for source_layer in [Layer.RAW, Layer.EPISODIC, Layer.SEMANTIC]:
            trigger = COMPILE_TRIGGERS[source_layer]
            eligible = CompileEngine.get_eligible_atoms(atoms, source_layer, trigger)

            partitions: dict[tuple[object, ...], list[MemoryAtom]] = {}
            for atom in eligible:
                key = self.compile_engine.boundary_key(atom)
                partitions.setdefault(key, []).append(atom)

            for partition in partitions.values():
                if len(partition) < trigger.min_atoms:
                    continue
                compiled = await self.compile_engine.compile_layer(partition, trigger.target_layer)
                if compiled:
                    await self.store.create(compiled)
                    # Mark source atoms as compiled
                    for a in partition:
                        a.relations.append(
                            Relation(
                                source_id=compiled.id,
                                target_id=a.id,
                                relation_type=RelationType.DERIVES,
                            )
                        )
                        await self.store.update(a)
                    logger.info(
                        f"Compiled {len(partition)} {source_layer.name} → "
                        f"1 {trigger.target_layer.name}: {compiled.summary[:80]}"
                    )
                    return  # One privacy partition per tick

    async def shutdown(self) -> None:
        await self.stop_metabolism()
        await self.store.close()

    # ── Encode ──

    async def encode(
        self,
        user_input: str,
        agent_response: str,
        emotion_vad: VADVector | None = None,
        session_id: str = "default",
        *,
        context: MemoryContext | None = None,
        scope: MemoryScope | None = None,
        visibility: MemoryVisibility | None = None,
        retention_policy: str = "standard",
    ) -> MemoryAtom:
        """Encode a conversation turn as a RAW layer MemoryAtom.

        Confidence is computed from emotion intensity (flashbulb memory effect).
        High-arousal events get higher initial confidence.
        """
        if emotion_vad is None:
            emotion_vad = VADVector(0.0, 0.0, 0.0)

        content = f"用户: {user_input}\n助手: {agent_response}"
        now = datetime.now(UTC)

        conf = EmotionalField.encoding_confidence(emotion_vad)

        if scope is None:
            if context and context.actor_id:
                scope = MemoryScope.VIEWER
            elif context and context.stream_id:
                scope = MemoryScope.STREAM
            else:
                scope = MemoryScope.COMMUNITY
        if visibility is None:
            visibility = (
                MemoryVisibility.PRIVATE
                if scope is MemoryScope.VIEWER
                else MemoryVisibility.INTERNAL
            )
        subject_ids = (
            [context.actor_id]
            if scope is MemoryScope.VIEWER and context and context.actor_id
            else []
        )
        origin = context.to_origin() if context else {}
        if not context and session_id != "default":
            # Preserve legacy provenance without making transport IDs visible.
            origin["legacy_session_id"] = session_id

        atom = MemoryAtom(
            id=f"raw-{uuid.uuid4().hex[:12]}",
            layer=Layer.RAW,
            content=content,
            summary=None,
            occurred_at=now,
            rewritten_at=now,
            version=1,
            confidence=conf,
            salience=conf,
            emotion_valence=emotion_vad.valence,
            emotion_arousal=emotion_vad.arousal,
            emotion_dominance=emotion_vad.dominance,
            tags=[],
            scope=scope,
            visibility=visibility,
            subject_ids=subject_ids,
            origin=origin,
            retention_policy=retention_policy,
        )
        await self.store.create(atom)
        return atom

    # ── Recall ──

    async def recall(
        self,
        query: str,
        session_id: str = "default",
        current_emotion: VADVector | None = None,
        limit: int = 20,
        character_known: list[str] | None = None,
        character_unknown: list[str] | None = None,
        mbti_ei: int = 50,
        mbti_sn: int = 50,
        mbti_tf: int = 50,
        mbti_jp: int = 50,
        *,
        context: MemoryContext | None = None,
    ) -> RecallResult:
        """Recall memories relevant to the query, biased by current emotion.

        Optionally filters and re-ranks results by character persona when
        knowledge boundary or MBTI parameters are provided.

        Returns RecallResult with emotion-ranked atoms, user profile, and memes.
        Asynchronously triggers reconsolidation for high-salience recalled atoms.
        """
        if current_emotion is None:
            current_emotion = VADVector(0.0, 0.0, 0.0)

        # Get matching atoms via hybrid search (Chroma vector + FTS5 keyword)
        all_active = await self.store.hybrid_search(query, limit * 3)

        # Scope policy is based on stable identities, never transport session IDs.
        all_active = [atom for atom in all_active if self._is_visible_in_context(atom, context)]

        # Character persona filtering (pre-rank)
        if character_unknown:
            all_active = CharacterMemoryFilter.filter_by_boundaries(
                all_active,
                known=character_known or [],
                unknown=character_unknown,
                query=query,
            )

        # Emotion-biased ranking
        ranked = MemorySearch.rank_by_emotion(all_active, current_emotion)

        # Stable actor and stream matches refine relevance. MBTI belongs to
        # personality presentation and deliberately does not rank facts.
        ranked = self._rank_for_context(ranked, context)

        # Take top-K
        top_atoms = ranked[:limit]

        # Extract profile from SEMANTIC layer
        profile_atoms = [
            atom
            for atom in top_atoms
            if atom.layer == Layer.SEMANTIC
            and atom.scope is MemoryScope.VIEWER
            and context is not None
            and context.actor_id in atom.subject_ids
        ]
        profile = {atom.id: atom.summary or atom.content for atom in profile_atoms}

        # Extract memes from EMERGENT layer
        meme_atoms = [a for a in ranked if a.layer == Layer.EMERGENT][:5]

        result = RecallResult(
            atoms=top_atoms,
            profile=profile,
            memes=meme_atoms,
            metadata={
                "revision": await self.store.get_revision(),
                "scopes": sorted({atom.scope.value for atom in top_atoms}),
                "actor_id": context.actor_id if context else None,
            },
        )

        # Trigger async reconsolidation (fire-and-forget)
        asyncio.create_task(self._reconsolidate(top_atoms, current_emotion, query))

        return result

    @staticmethod
    def _is_visible_in_context(
        atom: MemoryAtom,
        context: MemoryContext | None,
    ) -> bool:
        if atom.scope is MemoryScope.VIEWER:
            return bool(context and context.actor_id and context.actor_id in atom.subject_ids)
        if atom.scope is MemoryScope.STREAM:
            return bool(
                context and context.stream_id and atom.origin.get("stream_id") == context.stream_id
            )
        return atom.scope in {
            MemoryScope.CHARACTER,
            MemoryScope.COMMUNITY,
            MemoryScope.WORLD,
        }

    @staticmethod
    def _rank_for_context(
        atoms: list[MemoryAtom],
        context: MemoryContext | None,
    ) -> list[MemoryAtom]:
        total = max(1, len(atoms))

        def score(item: tuple[int, MemoryAtom]) -> float:
            index, atom = item
            relevance = 1.0 - (index / total)
            subject = 1.0 if context and context.actor_id in atom.subject_ids else 0.0
            stream = (
                1.0
                if (
                    context
                    and context.stream_id
                    and atom.origin.get("stream_id") == context.stream_id
                )
                else 0.0
            )
            return (
                0.55 * relevance
                + 0.18 * subject
                + 0.10 * stream
                + 0.10 * atom.trust_level
                + 0.07 * atom.salience
            )

        return [atom for _, atom in sorted(enumerate(atoms), key=score, reverse=True)]

    # ── Reconsolidation (integrated) ──

    async def _reconsolidate(
        self,
        atoms: list[MemoryAtom],
        current_emotion: VADVector,
        query: str,
    ) -> None:
        """Async reconsolidation — recall triggers memory rewriting.

        Throttled: max 3 atoms per recall, 30min cooldown, salience > 0.3.
        The LLM rewrite is a placeholder — in production, this calls the
        actual LLM service with the reconsolidation prompt.
        """
        now = datetime.now(UTC)
        cooldown = timedelta(minutes=self.RECONSOLIDATION_COOLDOWN_MINUTES)
        reconsolidated = 0

        for atom in atoms:
            if reconsolidated >= self.MAX_RECONSOLIDATION_PER_RECALL:
                break

            # Cooldown check
            if atom.last_accessed_at and (now - atom.last_accessed_at) < cooldown:
                continue

            # Salience threshold
            if atom.salience <= self.MIN_RECONSOLIDATION_SALIENCE:
                continue

            # Perform reconsolidation
            try:
                await self._reconsolidate_atom(atom, current_emotion, query)
                reconsolidated += 1
            except Exception:
                # Reconsolidation failure is non-fatal
                pass

    async def _reconsolidate_atom(
        self,
        atom: MemoryAtom,
        current_emotion: VADVector,
        query: str,
    ) -> None:
        """Reconsolidate a single atom — LLM-driven memory rewriting.

        Uses ReconsolidationClient when available (real LLM).
        Falls back to metadata-only reconsolidation when unavailable.
        """
        new_summary = atom.summary or atom.content
        new_confidence = min(1.0, atom.confidence + 0.02)
        new_emotion = EmotionalField.emotion_shift(
            current_emotion,
            VADVector(atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance),
        )

        # Try LLM-driven reconsolidation
        client = get_reconsolidation_client()
        if client and client.is_available:
            try:
                result = await client.reconsolidate(
                    content=atom.content,
                    version=atom.version,
                    rewritten_at=atom.rewritten_at.isoformat(),
                    valence=current_emotion.valence,
                    arousal=current_emotion.arousal,
                    dominance=current_emotion.dominance,
                    query=query,
                )
                if result:
                    new_summary = result.summary
                    new_confidence = min(1.0, max(0.0, atom.confidence + result.confidence_delta))
                    # Apply emotion shift from LLM
                    shifted = EmotionalField.emotion_shift(
                        current_emotion,
                        VADVector(
                            atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance
                        ),
                    )
                    new_emotion = shifted
            except Exception as e:
                logger.warning(f"Reconsolidation LLM call failed, using metadata fallback: {e}")

        # Reduce decay rate (recalled memories decay slower)
        new_decay_rate = max(0.02, atom.decay_rate * 0.95)

        # Version through the store so the previous evidence/summary remains
        # auditable in memory_versions. RAW content is never rewritten.
        if await self.store.get(atom.id) is None:
            await self.store.create(atom)
        updated = await self.store.create_version(
            atom.id,
            new_summary,
            new_confidence,
            (new_emotion.valence, new_emotion.arousal, new_emotion.dominance),
        )
        updated.decay_rate = new_decay_rate
        await self.store.update(updated)

        # Keep the caller's in-memory object coherent for existing graph/tests.
        for field_name in (
            "summary",
            "confidence",
            "emotion_valence",
            "emotion_arousal",
            "emotion_dominance",
            "decay_rate",
            "version",
            "version_chain",
            "rewritten_at",
            "retrieval_count",
            "last_accessed_at",
        ):
            setattr(atom, field_name, getattr(updated, field_name))
