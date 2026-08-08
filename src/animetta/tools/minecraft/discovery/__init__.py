"""Evidence-backed, world-scoped Minecraft discovery domain."""

from .exploration import (
    ExplorationBounds,
    ExplorationDecision,
    ExplorationInput,
    ExplorationProposer,
    ExplorationSeed,
)
from .models import (
    AcquisitionEvidence,
    DiscoveryObservation,
    ObservedFact,
    WorldFact,
    WorldFactIdentity,
    WorldFactState,
)
from .projector import DiscoveryProjector
from .runtime import RuntimeDiscoveryProjector, RuntimeDiscoveryResult
from .store import InMemoryWorldFactStore, SQLiteWorldFactStore, WorldFactStore

__all__ = [
    "AcquisitionEvidence",
    "DiscoveryObservation",
    "DiscoveryProjector",
    "ExplorationBounds",
    "ExplorationDecision",
    "ExplorationInput",
    "ExplorationProposer",
    "ExplorationSeed",
    "InMemoryWorldFactStore",
    "ObservedFact",
    "SQLiteWorldFactStore",
    "WorldFact",
    "WorldFactIdentity",
    "WorldFactState",
    "WorldFactStore",
    "RuntimeDiscoveryProjector",
    "RuntimeDiscoveryResult",
]
