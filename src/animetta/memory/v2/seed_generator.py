"""PersonaSeedGenerator — auto-generate seed MemoryAtoms from persona configuration.

Converts static persona YAML into pre-populated MemoryAtoms at three layers:
- RAW: from example dialogues and canonical quotes
- EPISODIC: from identity/role/story context
- SEMANTIC: from personality traits, catchphrases, knowledge boundaries

These seed atoms give the character "pre-existing memories" before any real
conversations occur. All atoms are tagged with character:{name} and high confidence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from animetta.memory.v2.atom import Layer, MemoryAtom

logger = logging.getLogger(__name__)


@dataclass
class SeedResult:
    """Result of seed memory generation."""

    atoms: list[MemoryAtom] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"raw": 0, "episodic": 0, "semantic": 0})


@dataclass
class CanonicalQuote:
    """A canonical dialogue quote from source material."""

    speaker: str  # "草十郎" or "青子" etc.
    text: str
    context: str  # scene description
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0


class PersonaSeedGenerator:
    """Generates seed MemoryAtoms from PersonaConfig data.

    Usage:
        generator = PersonaSeedGenerator(persona_config, atom_store)
        result = await generator.generate(quotes=canonical_quotes)
        # result.atoms can be written to AtomStore
    """

    def __init__(self, persona, store=None):
        """Initialize seed generator.

        Args:
            persona: PersonaConfig instance with identity, personality, examples, knowledge_boundaries.
            store: Optional AtomStore for checking existing seeds (for skip logic).
        """
        self.persona = persona
        self.store = store

    async def generate(
        self,
        quotes: list[CanonicalQuote] | None = None,
        force: bool = False,
    ) -> SeedResult:
        """Generate all seed atoms.

        Args:
            quotes: Optional canonical dialogue quotes from source material.
            force: If True, skip the "already exists" check and regenerate.

        Returns:
            SeedResult with generated atoms and stats.
        """
        # Check if seeds already exist
        if not force and self.store:
            char_tag = f"character:{self.persona.name}"
            try:
                all_active = await self.store.get_all_active(limit=5000)
                existing = [a for a in all_active if char_tag in a.tags]
                if existing:
                    logger.info(
                        f"Seed atoms already exist for {self.persona.name} "
                        f"({len(existing)} atoms). Skipping generation."
                    )
                    return SeedResult()
            except Exception as e:
                logger.debug(f"Could not check existing seeds: {e}")

        atoms: list[MemoryAtom] = []

        # RAW layer: from examples and quotes
        raw = self._generate_raw(quotes or [])
        atoms.extend(raw)

        # EPISODIC layer: from identity and story context
        episodic = self._generate_episodic()
        atoms.extend(episodic)

        # SEMANTIC layer: from traits, catchphrases, boundaries
        semantic = self._generate_semantic()
        atoms.extend(semantic)

        stats = {
            "raw": len(raw),
            "episodic": len(episodic),
            "semantic": len(semantic),
        }

        logger.info(
            f"Generated {len(atoms)} seed atoms for {self.persona.name}: "
            f"RAW={stats['raw']}, EPISODIC={stats['episodic']}, SEMANTIC={stats['semantic']}"
        )

        return SeedResult(atoms=atoms, stats=stats)

    def _make_atom(
        self,
        content: str,
        layer: Layer,
        confidence: float = 0.9,
        tags: list[str] | None = None,
        valence: float = 0.0,
        arousal: float = 0.0,
    ) -> MemoryAtom:
        """Create a seed MemoryAtom with character tagging and high confidence."""
        char_tag = f"character:{self.persona.name}"
        base_tags = [char_tag, "seed"]
        if tags:
            base_tags.extend(tags)

        now = datetime.now(UTC)
        return MemoryAtom(
            id=f"{layer.name.lower()}-seed-{uuid.uuid4().hex[:8]}",
            layer=layer,
            content=content,
            summary=None,
            occurred_at=now,
            rewritten_at=now,
            version=1,
            confidence=confidence,
            salience=confidence,
            emotion_valence=valence,
            emotion_arousal=arousal,
            emotion_dominance=0.0,
            tags=base_tags,
        )

    # ── RAW generation ──

    def _generate_raw(self, quotes: list[CanonicalQuote]) -> list[MemoryAtom]:
        """Generate RAW atoms from example dialogues and canonical quotes.

        Each example/quote becomes a RAW atom representing a "conversation
        草十郎 experienced." Quoted from source material with high confidence.
        """
        atoms: list[MemoryAtom] = []

        # From persona examples
        for i, ex in enumerate(self.persona.examples):
            user = ex.get("user", "")
            ai = ex.get("ai", "")
            if not user or not ai:
                continue

            content = f"会話の記憶:\n相手: {user}\n草十郎: {ai}"
            # Extract emotion tag if present in ai response
            valence = 0.0
            arousal = 0.1
            if "[happy]" in ai:
                valence, arousal = 0.3, 0.2
            elif "[sad]" in ai:
                valence, arousal = -0.3, 0.1
            elif "[thinking]" in ai:
                valence, arousal = 0.0, 0.05

            atom = self._make_atom(
                content=content,
                layer=Layer.RAW,
                confidence=0.9,
                tags=["example_dialogue", f"example_{i}"],
                valence=valence,
                arousal=arousal,
            )
            atoms.append(atom)

        # From canonical quotes
        for i, q in enumerate(quotes):
            content = f"原作の台詞（{q.context}）:\n{q.speaker}: {q.text}"
            atom = self._make_atom(
                content=content,
                layer=Layer.RAW,
                confidence=0.95,
                tags=["canonical_quote", f"quote_{i}", q.speaker],
                valence=q.emotion_valence,
                arousal=q.emotion_arousal,
            )
            atoms.append(atom)

        return atoms

    # ── EPISODIC generation ──

    def _generate_episodic(self) -> list[MemoryAtom]:
        """Generate EPISODIC atoms from identity and role context.

        Creates narrative memories that summarize the character's background
        as first-person recollections.
        """
        atoms: list[MemoryAtom] = []

        identity = self.persona.identity.strip()
        if not identity:
            return atoms

        # Create an episodic summary of the character's origin
        name = self.persona.name
        role = self.persona.role

        episode_content = (
            f"私（{name}）の記憶:\n役割: {role}\n自分が誰で、どこから来たのか:\n{identity}"
        )

        atom = self._make_atom(
            content=episode_content,
            layer=Layer.EPISODIC,
            confidence=0.95,
            tags=["origin_story", "identity"],
            valence=0.1,
            arousal=0.05,
        )
        atoms.append(atom)

        return atoms

    # ── SEMANTIC generation ──

    def _generate_semantic(self) -> list[MemoryAtom]:
        """Generate SEMANTIC atoms from personality traits, catchphrases,
        and knowledge boundaries.

        Creates belief/self-knowledge atoms that encode the character's
        explicit understanding of themselves.
        """
        atoms: list[MemoryAtom] = []
        personality = self.persona.personality

        # From personality traits
        if personality.traits:
            traits_text = "\n".join(f"- {t}" for t in personality.traits)
            content = f"自分の性格について:\n{traits_text}"
            atom = self._make_atom(
                content=content,
                layer=Layer.SEMANTIC,
                confidence=0.9,
                tags=["self_knowledge", "personality"],
                valence=0.1,
                arousal=0.02,
            )
            atoms.append(atom)

        # From catchphrases (core beliefs expressed as self-statements)
        if personality.catchphrases:
            phrases_text = "\n".join(f"- {c}" for c in personality.catchphrases)
            content = f"自分の信念や大切にしている言葉:\n{phrases_text}"
            atom = self._make_atom(
                content=content,
                layer=Layer.SEMANTIC,
                confidence=1.0,  # Core beliefs — highest confidence
                tags=["core_beliefs", "catchphrases"],
                valence=0.2,
                arousal=0.1,
            )
            atoms.append(atom)

        # From knowledge boundaries (self-awareness of ignorance)
        kb = self.persona.knowledge_boundaries
        if kb:
            if kb.known:
                known_text = "、".join(kb.known)
                atom = self._make_atom(
                    content=f"自分が詳しいこと:\n{known_text}\nこれらはよく知っている。",
                    layer=Layer.SEMANTIC,
                    confidence=0.9,
                    tags=["self_knowledge", "known_domains"],
                    valence=0.1,
                    arousal=0.02,
                )
                atoms.append(atom)

            if kb.unknown:
                unknown_text = "、".join(kb.unknown)
                atom = self._make_atom(
                    content=(
                        f"自分がよくわからないこと:\n{unknown_text}\n"
                        f"これらはまだよく知らない。聞かれても正直に'わからない'と言う。"
                    ),
                    layer=Layer.SEMANTIC,
                    confidence=0.95,
                    tags=["self_knowledge", "unknown_domains", "knowledge_gap"],
                    valence=0.0,
                    arousal=0.01,
                )
                atoms.append(atom)

        return atoms
