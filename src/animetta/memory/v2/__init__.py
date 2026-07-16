"""Living Memory V2 — Active memory architecture.

Recall is rewriting. Emotion is a field. Forgetting is a feature.
"""

from animetta.memory.v2.atom import Layer, MemoryAtom, Relation, RelationType
from animetta.memory.v2.emotion_field import VAD_MAP, EmotionalField, VADVector
from animetta.memory.v2.metabolism import MetabolismScheduler
from animetta.memory.v2.reconsolidation import (
    ReconsolidationClient,
    get_reconsolidation_client,
    set_reconsolidation_client,
)
from animetta.memory.v2.search import MemorySearch
from animetta.memory.v2.store import AtomStore
from animetta.memory.v2.system import LivingMemorySystem, RecallResult

__all__ = [
    "MemoryAtom",
    "Layer",
    "Relation",
    "RelationType",
    "VADVector",
    "VAD_MAP",
    "EmotionalField",
    "MetabolismScheduler",
    "MemorySearch",
    "AtomStore",
    "LivingMemorySystem",
    "RecallResult",
    "ReconsolidationClient",
    "set_reconsolidation_client",
    "get_reconsolidation_client",
]
