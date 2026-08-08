"""Canonical evidence-driven Minecraft technology graph and unlock verifier."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    ActionReceipt,
    GameBotObservation,
    validate_receipt_chain,
)


class TechNode(BaseModel):
    """One immutable technology milestone and its machine-verifiable evidence."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    prerequisites: frozenset[str] = frozenset()
    allowed_capabilities: frozenset[str]
    required_capabilities: tuple[str, ...]
    postconditions: dict[str, int]
    discovery_radius: int = 0
    discovery_seconds: int = 0


class UnlockRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    session_id: str
    task_id: str
    runtime_id: str
    unlocked_at: datetime
    receipt_hashes: tuple[str, ...]
    final_observation_hash: str


class TechProgress(BaseModel):
    """Committed technology state; inventory alone never mutates this model."""

    model_config = ConfigDict(frozen=True)

    unlocked_nodes: frozenset[str] = frozenset()
    records: dict[str, UnlockRecord] = Field(default_factory=dict)

    def commit(self, record: UnlockRecord) -> TechProgress:
        records = dict(self.records)
        records[record.node_id] = record
        return self.model_copy(
            update={
                "unlocked_nodes": self.unlocked_nodes | {record.node_id},
                "records": records,
            }
        )


class EvidenceFailure(BaseModel):
    code: str
    detail: str = ""


class TechEvidenceReport(BaseModel):
    valid: bool
    failures: list[EvidenceFailure] = Field(default_factory=list)
    unlock_record: UnlockRecord | None = None


class DiscoveryTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    blocked_node_id: str
    radius: int = Field(gt=0, le=128)
    seconds: int = Field(gt=0, le=600)
    capability: str = "goto"
    params: dict[str, object] = Field(default_factory=dict)


class FrontierSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["technology", "discovery"]
    node: TechNode | None = None
    discovery: DiscoveryTask | None = None


class TechGraph:
    def __init__(self, nodes: list[TechNode]):
        self._nodes = {node.id: node for node in nodes}
        if len(self._nodes) != len(nodes):
            raise ValueError("technology node ids must be unique")
        for node in nodes:
            missing = node.prerequisites - self._nodes.keys()
            if missing:
                raise ValueError(
                    f"technology node '{node.id}' has missing prerequisites: {missing}"
                )

    def get(self, node_id: str) -> TechNode:
        return self._nodes[node_id]

    def frontier(
        self,
        progress: TechProgress,
        observation: GameBotObservation,
    ) -> tuple[TechNode, ...]:
        del observation  # Inventory is not authority for unlock ordering.
        return tuple(
            node
            for node in self._nodes.values()
            if node.id not in progress.unlocked_nodes
            and node.prerequisites.issubset(progress.unlocked_nodes)
        )


class FrontierScheduler:
    """Choose a reachable node, cooling down repeatedly failing strategies."""

    def __init__(self, graph: TechGraph, *, failure_cooldown: int = 4):
        if failure_cooldown < 1:
            raise ValueError("failure_cooldown must be positive")
        self._graph = graph
        self._failure_cooldown = failure_cooldown
        self._failures: dict[str, int] = {}

    def record_failure(self, node_id: str) -> None:
        self._failures[node_id] = self._failures.get(node_id, 0) + 1

    def select(
        self,
        progress: TechProgress,
        observation: GameBotObservation,
    ) -> FrontierSelection:
        frontier = self._graph.frontier(progress, observation)
        for node in frontier:
            if self._failures.get(node.id, 0) < self._failure_cooldown:
                return FrontierSelection(kind="technology", node=node)

        blocked = frontier[0] if frontier else None
        if blocked is not None:
            self._failures[blocked.id] = 0
        capability = "goto"
        params: dict[str, object] = {}
        if blocked and blocked.id in {"cobblestone", "iron_ingot", "gold_ore"}:
            capability = "mine_shaft"
            params = {
                "target_y": {
                    "cobblestone": 50,
                    "iron_ingot": 40,
                    "gold_ore": 20,
                }[blocked.id],
            }
        return FrontierSelection(
            kind="discovery",
            discovery=DiscoveryTask(
                blocked_node_id=blocked.id if blocked else "open_world",
                radius=(blocked.discovery_radius if blocked and blocked.discovery_radius else 64),
                seconds=(
                    blocked.discovery_seconds if blocked and blocked.discovery_seconds else 120
                ),
                capability=capability,
                params=params,
            ),
        )


class TechEvidenceVerifier:
    def __init__(self, graph: TechGraph):
        self._graph = graph

    def verify(
        self,
        *,
        node_id: str,
        progress: TechProgress,
        receipts: list[ActionReceipt],
        before: GameBotObservation,
        after: GameBotObservation,
        session_id: str,
        task_id: str,
        runtime_id: str,
    ) -> TechEvidenceReport:
        node = self._graph.get(node_id)
        failures: list[EvidenceFailure] = []

        missing_prerequisites = node.prerequisites - progress.unlocked_nodes
        if missing_prerequisites:
            failures.append(
                EvidenceFailure(
                    code="MISSING_PREREQUISITE",
                    detail=",".join(sorted(missing_prerequisites)),
                )
            )

        chain = validate_receipt_chain(
            receipts,
            session_id=session_id,
            task_id=task_id,
            runtime_id=runtime_id,
        )
        failures.extend(
            EvidenceFailure(code=error.code, detail=error.receipt_id or "")
            for error in chain.errors
        )

        if receipts:
            if receipts[0].before_observation_hash != before.content_hash:
                failures.append(EvidenceFailure(code="START_OBSERVATION_MISMATCH"))
            if receipts[-1].after_observation_hash != after.content_hash:
                failures.append(EvidenceFailure(code="FINAL_OBSERVATION_MISMATCH"))

        actual_capabilities = [receipt.capability for receipt in receipts]
        for receipt in receipts:
            if receipt.capability not in node.allowed_capabilities:
                failures.append(
                    EvidenceFailure(
                        code="DISALLOWED_EVIDENCE_CAPABILITY",
                        detail=receipt.capability,
                    )
                )
            if receipt.outcome is not ActionOutcome.SUCCESS:
                failures.append(
                    EvidenceFailure(code="UNSUCCESSFUL_ACTION", detail=receipt.receipt_id)
                )

        missing_evidence = [
            capability
            for capability in node.required_capabilities
            if capability not in actual_capabilities
        ]
        if missing_evidence:
            failures.append(
                EvidenceFailure(
                    code="MISSING_REQUIRED_EVIDENCE",
                    detail=",".join(missing_evidence),
                )
            )

        for item, minimum in node.postconditions.items():
            before_count = before.inventory.get(item, 0)
            after_count = after.inventory.get(item, 0)
            if after_count < minimum:
                failures.append(
                    EvidenceFailure(
                        code="POSTCONDITION_FAILED",
                        detail=f"{item}:{after_count}<{minimum}",
                    )
                )
            if after_count > before_count and (not receipts or missing_evidence):
                failures.append(
                    EvidenceFailure(
                        code="UNEXPLAINED_INVENTORY_DELTA",
                        detail=f"{item}:{before_count}->{after_count}",
                    )
                )

        if failures:
            return TechEvidenceReport(valid=False, failures=failures)

        record = UnlockRecord(
            node_id=node.id,
            session_id=session_id,
            task_id=task_id,
            runtime_id=runtime_id,
            unlocked_at=datetime.now(UTC),
            receipt_hashes=tuple(receipt.content_hash for receipt in receipts),
            final_observation_hash=after.content_hash,
        )
        return TechEvidenceReport(valid=True, unlock_record=record)


def build_survival_tech_graph() -> TechGraph:
    """Initial survival progression from empty inventory through iron tools."""

    movement = frozenset({"observe", "status", "goto"})
    return TechGraph(
        [
            TechNode(
                id="wood_collection",
                name="Collect wood",
                allowed_capabilities=movement | {"collect"},
                required_capabilities=("collect",),
                postconditions={"oak_log": 1},
                discovery_radius=64,
                discovery_seconds=120,
            ),
            TechNode(
                id="crafting_table",
                name="Craft a crafting table",
                prerequisites=frozenset({"wood_collection"}),
                allowed_capabilities=movement | {"collect", "craft", "place"},
                required_capabilities=("craft",),
                postconditions={"crafting_table": 1},
            ),
            TechNode(
                id="wooden_pickaxe",
                name="Craft a wooden pickaxe",
                prerequisites=frozenset({"crafting_table"}),
                allowed_capabilities=movement | {"collect", "craft", "place"},
                required_capabilities=("craft",),
                postconditions={"wooden_pickaxe": 1},
            ),
            TechNode(
                id="cobblestone",
                name="Collect cobblestone",
                prerequisites=frozenset({"wooden_pickaxe"}),
                allowed_capabilities=movement | {"collect", "craft", "mine", "equip", "mine_shaft"},
                required_capabilities=("mine_shaft",),
                postconditions={"cobblestone": 1},
                discovery_radius=48,
                discovery_seconds=120,
            ),
            TechNode(
                id="stone_pickaxe",
                name="Craft a stone pickaxe",
                prerequisites=frozenset({"cobblestone", "crafting_table"}),
                allowed_capabilities=movement | {"collect", "craft", "place", "mine_shaft"},
                required_capabilities=("craft",),
                postconditions={"stone_pickaxe": 1},
            ),
            TechNode(
                id="furnace",
                name="Craft a furnace",
                prerequisites=frozenset({"cobblestone", "crafting_table"}),
                allowed_capabilities=movement | {"collect", "craft", "place"},
                required_capabilities=("craft",),
                postconditions={"furnace": 1},
            ),
            TechNode(
                id="iron_ingot",
                name="Smelt an iron ingot",
                prerequisites=frozenset({"stone_pickaxe", "furnace"}),
                allowed_capabilities=movement
                | {
                    "collect",
                    "craft",
                    "mine",
                    "smelt",
                    "equip",
                    "place",
                    "mine_shaft",
                },
                required_capabilities=("collect", "smelt"),
                postconditions={"iron_ingot": 1},
                discovery_radius=96,
                discovery_seconds=300,
            ),
            TechNode(
                id="iron_pickaxe",
                name="Craft an iron pickaxe",
                prerequisites=frozenset({"iron_ingot", "crafting_table"}),
                allowed_capabilities=movement | {"collect", "craft", "place", "smelt"},
                required_capabilities=("craft",),
                postconditions={"iron_pickaxe": 1},
            ),
            TechNode(
                id="gold_ore",
                name="Discover and collect gold ore",
                prerequisites=frozenset({"iron_pickaxe"}),
                allowed_capabilities=movement | {"collect", "mine", "equip"},
                required_capabilities=("collect",),
                postconditions={"raw_gold": 1},
                discovery_radius=128,
                discovery_seconds=420,
            ),
        ]
    )
