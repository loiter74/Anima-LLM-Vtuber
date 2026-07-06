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

from animetta.memory.v2.atom import Layer, MemoryAtom, Relation, RelationType
from animetta.memory.v2.character_filter import CharacterMemoryFilter
from animetta.memory.v2.compile import COMPILE_TRIGGERS, CompileEngine
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

            if len(eligible) >= trigger.min_atoms:
                compiled = await self.compile_engine.compile_layer(
                    eligible, trigger.target_layer
                )
                if compiled:
                    await self.store.create(compiled)
                    # Mark source atoms as compiled
                    for a in eligible:
                        a.relations.append(Relation(
                            source_id=compiled.id, target_id=a.id,
                            relation_type=RelationType.DERIVES,
                        ))
                        await self.store.update(a)
                    logger.info(
                        f"Compiled {len(eligible)} {source_layer.name} → "
                        f"1 {trigger.target_layer.name}: {compiled.summary[:80]}"
                    )
                    break  # One compilation per tick

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
            tags=[session_id],
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

        # Filter by session if specified
        if session_id != "default":
            all_active = [
                a for a in all_active if session_id in a.tags
            ]

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

        # Character MBTI re-ranking (post-emotion-rank)
        if mbti_ei != 50 or mbti_sn != 50 or mbti_tf != 50 or mbti_jp != 50:
            ranked = CharacterMemoryFilter.rank_by_persona(
                ranked,
                mbti_ei=mbti_ei,
                mbti_sn=mbti_sn,
                mbti_tf=mbti_tf,
                mbti_jp=mbti_jp,
            )

        # Take top-K
        top_atoms = ranked[:limit]

        # Extract profile from SEMANTIC layer
        profile_atoms = [a for a in top_atoms if a.layer == Layer.SEMANTIC]
        profile = {a.tags[0] if a.tags else "unknown": a.summary or a.content
                   for a in profile_atoms} if profile_atoms else {}

        # Extract memes from EMERGENT layer
        meme_atoms = [a for a in ranked if a.layer == Layer.EMERGENT][:5]

        result = RecallResult(
            atoms=top_atoms,
            profile=profile,
            memes=meme_atoms,
        )

        # Trigger async reconsolidation (fire-and-forget)
        asyncio.create_task(
            self._reconsolidate(top_atoms, current_emotion, query)
        )

        return result

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
        new_emotion = EmotionalField.emotion_shift(current_emotion,
            VADVector(atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance))

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
                    new_confidence = min(1.0, max(0.0,
                        atom.confidence + result.confidence_delta))
                    # Apply emotion shift from LLM
                    shifted = EmotionalField.emotion_shift(current_emotion,
                        VADVector(atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance))
                    new_emotion = shifted
            except Exception as e:
                logger.warning(f"Reconsolidation LLM call failed, using metadata fallback: {e}")

        # Reduce decay rate (recalled memories decay slower)
        new_decay_rate = max(0.02, atom.decay_rate * 0.95)

        # Write new version
        atom.summary = new_summary
        atom.confidence = new_confidence
        atom.emotion_valence = new_emotion.valence
        atom.emotion_arousal = new_emotion.arousal
        atom.emotion_dominance = new_emotion.dominance
        atom.decay_rate = new_decay_rate
        atom.version += 1
        atom.version_chain = list(atom.version_chain) + [atom.id]
        atom.rewritten_at = datetime.now(UTC)
        atom.retrieval_count += 1
        atom.last_accessed_at = datetime.now(UTC)

        await self.store.update(atom)
