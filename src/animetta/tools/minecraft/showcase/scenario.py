"""Declarative disposable-world setup with a closed pre-mission RCON catalog."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

MonsterEntityType = Literal[
    "minecraft:zombie",
    "minecraft:skeleton",
    "minecraft:spider",
]
GameRuleName = Literal[
    "doDaylightCycle",
    "doWeatherCycle",
    "doMobSpawning",
    "keepInventory",
]

_NAMESPACED_ID = r"^[a-z0-9_.-]+:[a-z0-9_./-]+$"
_SAFE_ID = r"^[A-Za-z0-9_.:\-]{1,128}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BlockPosition(_FrozenModel):
    x: int = Field(ge=-30_000_000, le=30_000_000)
    y: int = Field(ge=-64, le=320)
    z: int = Field(ge=-30_000_000, le=30_000_000)


class BoundedRegion(_FrozenModel):
    minimum: BlockPosition
    maximum: BlockPosition

    @model_validator(mode="after")
    def _ordered_and_bounded(self) -> Self:
        if any(
            low > high
            for low, high in (
                (self.minimum.x, self.maximum.x),
                (self.minimum.y, self.maximum.y),
                (self.minimum.z, self.maximum.z),
            )
        ):
            raise ValueError("region minimum exceeds maximum")
        if self.volume > 32_768:
            raise ValueError("scenario region exceeds the setup volume limit")
        return self

    @property
    def volume(self) -> int:
        return (
            (self.maximum.x - self.minimum.x + 1)
            * (self.maximum.y - self.minimum.y + 1)
            * (self.maximum.z - self.minimum.z + 1)
        )

    def contains(self, position: BlockPosition) -> bool:
        return (
            self.minimum.x <= position.x <= self.maximum.x
            and self.minimum.y <= position.y <= self.maximum.y
            and self.minimum.z <= position.z <= self.maximum.z
        )


class MonsterZone(_FrozenModel):
    zone_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    entity_type: MonsterEntityType
    spawn: BlockPosition
    bounds: BoundedRegion

    @model_validator(mode="after")
    def _spawn_is_inside_zone(self) -> Self:
        if not self.bounds.contains(self.spawn):
            raise ValueError("monster spawn lies outside its zone")
        return self


class LoadoutItem(_FrozenModel):
    item_id: str = Field(pattern=_NAMESPACED_ID)
    count: int = Field(gt=0, le=256)


class HiddenResource(_FrozenModel):
    item_id: Literal["minecraft:copper_ore"] = "minecraft:copper_ore"
    position: BlockPosition
    exploration_radius: float = Field(gt=0, le=128)
    initially_known: Literal[False] = False


class ScenarioGameRules(_FrozenModel):
    do_daylight_cycle: Literal[False] = False
    do_weather_cycle: Literal[False] = False
    do_mob_spawning: Literal[False] = False
    keep_inventory: Literal[True] = True


class ScenarioSpec(_FrozenModel):
    schema_version: Literal["2"] = "2"
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    world_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    world_seed: int
    bot_username: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    viewer_username: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    bot_spawn: BlockPosition
    traversal_surface: BoundedRegion
    monster_zones: tuple[MonsterZone, ...] = Field(min_length=3, max_length=3)
    build_area: BoundedRegion
    build_origin: BlockPosition
    loadout: tuple[LoadoutItem, ...] = Field(min_length=1, max_length=32)
    hidden_resources: tuple[HiddenResource, ...] = Field(min_length=3, max_length=3)
    clean_stores: tuple[Literal["mission", "discovery", "skill"], ...] = (
        "mission",
        "discovery",
        "skill",
    )
    fixed_time: Literal["midnight"] = "midnight"
    game_rules: ScenarioGameRules = ScenarioGameRules()

    @model_validator(mode="after")
    def _complete_showcase_scene(self) -> Self:
        expected = {"minecraft:zombie", "minecraft:skeleton", "minecraft:spider"}
        if {zone.entity_type for zone in self.monster_zones} != expected:
            raise ValueError("scenario requires one zone for each declared monster")
        if len({zone.zone_id for zone in self.monster_zones}) != 3:
            raise ValueError("monster zone IDs must be unique")
        if not self.build_area.contains(self.build_origin):
            raise ValueError("build origin lies outside the build area")
        surface = self.traversal_surface
        if surface.minimum.y != surface.maximum.y:
            raise ValueError("traversal surface must be one block high")
        standing_y = surface.minimum.y + 1

        def supported(position: BlockPosition, *, y: int) -> bool:
            return (
                surface.minimum.x <= position.x <= surface.maximum.x
                and surface.minimum.z <= position.z <= surface.maximum.z
                and position.y == y
            )

        standing_positions = (
            self.bot_spawn,
            self.build_origin,
            *(zone.spawn for zone in self.monster_zones),
        )
        if not all(supported(position, y=standing_y) for position in standing_positions):
            raise ValueError("showcase positions must stand on the traversal surface")
        if not all(
            supported(resource.position, y=surface.minimum.y) for resource in self.hidden_resources
        ):
            raise ValueError("hidden resources must replace the traversal surface")
        if len({resource.item_id for resource in self.hidden_resources}) != 1:
            raise ValueError("hidden resource instances must use the same item kind")
        positions = tuple(resource.position for resource in self.hidden_resources)
        if any(
            (left.x - right.x) ** 2 + (left.z - right.z) ** 2 < 4**2
            for index, left in enumerate(positions)
            for right in positions[index + 1 :]
        ):
            raise ValueError("hidden resource instances must be at least four blocks apart")
        if set(self.clean_stores) != {"mission", "discovery", "skill"}:
            raise ValueError("showcase requires isolated mission/discovery/skill stores")
        return self

    @property
    def canonical_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class SetGameruleOperation(_FrozenModel):
    kind: Literal["set_gamerule"] = "set_gamerule"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    rule: GameRuleName
    value: bool


class SetWorldTimeOperation(_FrozenModel):
    kind: Literal["set_world_time"] = "set_world_time"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    time: Literal["midnight"]


class ForceLoadRegionOperation(_FrozenModel):
    kind: Literal["force_load_region"] = "force_load_region"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    region: BoundedRegion

    @model_validator(mode="after")
    def _bounded_chunk_count(self) -> Self:
        chunks_x = self.region.maximum.x // 16 - self.region.minimum.x // 16 + 1
        chunks_z = self.region.maximum.z // 16 - self.region.minimum.z // 16 + 1
        if chunks_x * chunks_z > 256:
            raise ValueError("force-load region exceeds the 256 chunk command limit")
        return self


class ClearInventoryOperation(_FrozenModel):
    kind: Literal["clear_inventory"] = "clear_inventory"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    player: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")


class GiveItemOperation(_FrozenModel):
    kind: Literal["give_item"] = "give_item"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    player: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    item_id: str = Field(pattern=_NAMESPACED_ID)
    count: int = Field(gt=0, le=256)


class ClearRegionOperation(_FrozenModel):
    kind: Literal["clear_region"] = "clear_region"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    region: BoundedRegion


class FillRegionOperation(_FrozenModel):
    kind: Literal["fill_region"] = "fill_region"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    region: BoundedRegion
    block_id: str = Field(pattern=_NAMESPACED_ID)


class SummonEntityOperation(_FrozenModel):
    kind: Literal["summon_entity"] = "summon_entity"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    entity_type: MonsterEntityType
    position: BlockPosition
    stationary: Literal[True] = True


class SetBlockOperation(_FrozenModel):
    kind: Literal["set_block"] = "set_block"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    block_id: str = Field(pattern=_NAMESPACED_ID)
    position: BlockPosition


class TeleportPlayerOperation(_FrozenModel):
    kind: Literal["teleport_player"] = "teleport_player"
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    player: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    position: BlockPosition


SetupOperation = Annotated[
    SetGameruleOperation
    | SetWorldTimeOperation
    | ForceLoadRegionOperation
    | ClearInventoryOperation
    | GiveItemOperation
    | ClearRegionOperation
    | FillRegionOperation
    | SummonEntityOperation
    | SetBlockOperation
    | TeleportPlayerOperation,
    Field(discriminator="kind"),
]


class SetupExecutionResult(_FrozenModel):
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    outcome: Literal["success", "failure"]
    response_code: str = Field(pattern=r"^[A-Z0-9_]{1,64}$")


class ScenarioOperationReceipt(_FrozenModel):
    operation_id: str
    operation_kind: str
    command_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    applied_at_ms: int = Field(ge=0)
    outcome: Literal["success", "failure"]
    response_code: str
    gameplay_evidence_eligible: Literal[False] = False


class ScenarioReceipt(_FrozenModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=_SAFE_ID)
    scenario_id: str
    scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
    clean_store_namespace: str = Field(pattern=_SAFE_ID)
    world_ref: str = Field(min_length=1, max_length=256)
    store_refs: tuple[str, ...] = Field(min_length=3, max_length=3)
    operations: tuple[ScenarioOperationReceipt, ...]
    gameplay_evidence_eligible: Literal[False] = False

    @model_validator(mode="after")
    def _refs_are_run_relative(self) -> Self:
        refs = (self.world_ref, *self.store_refs)
        if any(
            PurePosixPath(ref).is_absolute() or ".." in PurePosixPath(ref).parts for ref in refs
        ):
            raise ValueError("scenario receipt refs must be run-relative")
        return self

    @property
    def canonical_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class MissionStartBoundary(_FrozenModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=_SAFE_ID)
    scenario_id: str
    scenario_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    started_at_ms: int = Field(ge=0)


class SetupExecutor(Protocol):
    async def execute(self, operation: SetupOperation) -> SetupExecutionResult: ...


class ScenarioEnvironment(Protocol):
    async def prepare_disposable_world(self, scenario: ScenarioSpec, run_id: str) -> str: ...

    async def create_clean_stores(
        self, run_id: str, store_names: tuple[str, ...]
    ) -> tuple[str, ...]: ...


class PostStartMutationError(RuntimeError):
    """Raised before any administrator mutation after mission admission."""


class FilesystemScenarioEnvironment:
    """Create an isolated seeded world directory and empty per-run stores."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _run_root(self, run_id: str) -> Path:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id) is None:
            raise ValueError("invalid showcase run ID")
        return self._root / run_id

    async def prepare_disposable_world(self, scenario: ScenarioSpec, run_id: str) -> str:
        run_root = self._run_root(run_id)
        run_root.mkdir(parents=True, exist_ok=False)
        world_root = run_root / "world"
        world_root.mkdir()
        relative = Path("world") / "server.properties"
        (run_root / relative).write_text(
            "\n".join(
                (
                    f"level-name={scenario.world_name}",
                    f"level-seed={scenario.world_seed}",
                    "online-mode=false",
                    "enable-rcon=true",
                    "spawn-protection=0",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        return relative.as_posix()

    async def create_clean_stores(
        self, run_id: str, store_names: tuple[str, ...]
    ) -> tuple[str, ...]:
        run_root = self._run_root(run_id)
        if not run_root.is_dir():
            raise RuntimeError("disposable world must be created before stores")
        stores_root = run_root / "stores"
        stores_root.mkdir(exist_ok=False)
        refs: list[str] = []
        for name in store_names:
            if name not in {"mission", "discovery", "skill"}:
                raise ValueError("store is outside the closed showcase catalog")
            relative = Path("stores") / f"{name}.sqlite3"
            (run_root / relative).touch(exist_ok=False)
            refs.append(relative.as_posix())
        return tuple(refs)


def default_showcase_scenario() -> ScenarioSpec:
    def position(x: int, y: int, z: int) -> BlockPosition:
        return BlockPosition(x=x, y=y, z=z)

    def zone(zone_id: str, entity_type: MonsterEntityType, x: int, z: int) -> MonsterZone:
        return MonsterZone(
            zone_id=zone_id,
            entity_type=entity_type,
            spawn=position(x, 65, z),
            bounds=BoundedRegion(
                minimum=position(x - 3, 64, z - 3),
                maximum=position(x + 3, 70, z + 3),
            ),
        )

    return ScenarioSpec(
        scenario_id="adaptive-mission-showcase-v2",
        world_name="animetta-adaptive-showcase",
        world_seed=8_675_309,
        bot_username="AnimettaBot",
        viewer_username="LUN077",
        bot_spawn=position(0, 65, 0),
        traversal_surface=BoundedRegion(
            minimum=position(-20, 64, -4),
            maximum=position(24, 64, 24),
        ),
        monster_zones=(
            zone("zombie-zone", "minecraft:zombie", 16, 0),
            zone("skeleton-zone", "minecraft:skeleton", 0, 16),
            zone("spider-zone", "minecraft:spider", -16, 0),
        ),
        build_area=BoundedRegion(
            minimum=position(3, 64, 3),
            maximum=position(12, 73, 12),
        ),
        build_origin=position(4, 65, 4),
        loadout=(
            LoadoutItem(item_id="minecraft:stone_sword", count=1),
            LoadoutItem(item_id="minecraft:stone_pickaxe", count=1),
            LoadoutItem(item_id="minecraft:oak_planks", count=96),
            LoadoutItem(item_id="minecraft:oak_door", count=1),
            LoadoutItem(item_id="minecraft:white_bed", count=1),
            LoadoutItem(item_id="minecraft:cobblestone", count=32),
            LoadoutItem(item_id="minecraft:torch", count=16),
            LoadoutItem(item_id="minecraft:bread", count=16),
        ),
        hidden_resources=(
            HiddenResource(
                position=position(20, 64, 20),
                exploration_radius=40,
            ),
            HiddenResource(
                position=position(16, 64, 20),
                exploration_radius=40,
            ),
            HiddenResource(
                position=position(20, 64, 16),
                exploration_radius=40,
            ),
        ),
    )


def compile_setup_operations(spec: ScenarioSpec) -> tuple[SetupOperation, ...]:
    rules: tuple[tuple[str, GameRuleName, bool], ...] = (
        ("daylight", "doDaylightCycle", spec.game_rules.do_daylight_cycle),
        ("weather", "doWeatherCycle", spec.game_rules.do_weather_cycle),
        ("mob-spawning", "doMobSpawning", spec.game_rules.do_mob_spawning),
        ("inventory", "keepInventory", spec.game_rules.keep_inventory),
    )
    operations: list[SetupOperation] = [
        SetGameruleOperation(operation_id=f"gamerule-{suffix}", rule=rule, value=value)
        for suffix, rule, value in rules
    ]
    operations.append(SetWorldTimeOperation(operation_id="set-fixed-time", time=spec.fixed_time))
    operations.extend(
        (
            ForceLoadRegionOperation(
                operation_id="force-load-action-region",
                region=spec.traversal_surface,
            ),
            TeleportPlayerOperation(
                operation_id="load-action-chunks",
                player=spec.bot_username,
                position=spec.bot_spawn,
            ),
            ClearInventoryOperation(operation_id="clear-bot-inventory", player=spec.bot_username),
            ClearRegionOperation(
                operation_id="clear-arena-headroom",
                region=BoundedRegion(
                    minimum=spec.traversal_surface.minimum.model_copy(
                        update={"y": spec.traversal_surface.minimum.y + 1}
                    ),
                    maximum=spec.traversal_surface.maximum.model_copy(
                        update={"y": spec.traversal_surface.maximum.y + 7}
                    ),
                ),
            ),
            FillRegionOperation(
                operation_id="fill-arena-surface",
                region=spec.traversal_surface,
                block_id="minecraft:stone",
            ),
            ClearRegionOperation(
                operation_id="clear-build-area",
                region=BoundedRegion(
                    minimum=spec.build_area.minimum.model_copy(update={"y": spec.build_origin.y}),
                    maximum=spec.build_area.maximum,
                ),
            ),
        )
    )
    operations.extend(
        GiveItemOperation(
            operation_id=f"loadout-{index:02d}",
            player=spec.bot_username,
            item_id=item.item_id,
            count=item.count,
        )
        for index, item in enumerate(spec.loadout, start=1)
    )
    operations.extend(
        SummonEntityOperation(
            operation_id=f"spawn-{zone.zone_id}",
            entity_type=zone.entity_type,
            position=zone.spawn,
        )
        for zone in spec.monster_zones
    )
    operations.extend(
        SetBlockOperation(
            operation_id=f"place-hidden-copper-{index:02d}",
            block_id=resource.item_id,
            position=resource.position,
        )
        for index, resource in enumerate(spec.hidden_resources, start=1)
    )
    operations.append(
        TeleportPlayerOperation(
            operation_id="position-action-bot",
            player=spec.bot_username,
            position=spec.bot_spawn,
        )
    )
    return tuple(operations)


def _position_args(position: BlockPosition) -> str:
    return f"{position.x} {position.y} {position.z}"


def render_rcon_command(operation: SetupOperation) -> str:
    match operation:
        case SetGameruleOperation():
            value = "true" if operation.value else "false"
            return f"gamerule {operation.rule} {value}"
        case SetWorldTimeOperation():
            return f"time set {operation.time}"
        case ForceLoadRegionOperation():
            return (
                "forceload add "
                f"{operation.region.minimum.x} {operation.region.minimum.z} "
                f"{operation.region.maximum.x} {operation.region.maximum.z}"
            )
        case ClearInventoryOperation():
            return f"clear {operation.player}"
        case GiveItemOperation():
            return f"give {operation.player} {operation.item_id} {operation.count}"
        case ClearRegionOperation():
            return (
                f"fill {_position_args(operation.region.minimum)} "
                f"{_position_args(operation.region.maximum)} minecraft:air replace"
            )
        case FillRegionOperation():
            return (
                f"fill {_position_args(operation.region.minimum)} "
                f"{_position_args(operation.region.maximum)} {operation.block_id} replace"
            )
        case SummonEntityOperation():
            return (
                f"summon {operation.entity_type} {_position_args(operation.position)} "
                "{NoAI:1b,PersistenceRequired:1b}"
            )
        case SetBlockOperation():
            return f"setblock {_position_args(operation.position)} {operation.block_id} replace"
        case TeleportPlayerOperation():
            return f"tp {operation.player} {_position_args(operation.position)}"
    raise TypeError("RCON_OPERATION_NOT_IN_CLOSED_CATALOG")


class ScenarioPreparer:
    def __init__(
        self,
        *,
        executor: SetupExecutor,
        environment: ScenarioEnvironment,
        now_ms: Callable[[], int],
    ) -> None:
        self._executor = executor
        self._environment = environment
        self._now_ms = now_ms
        self._state: Literal["idle", "preparing", "prepared", "mission_started", "invalidated"] = (
            "idle"
        )
        self._receipt: ScenarioReceipt | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def run_valid(self) -> bool:
        return self._state != "invalidated"

    async def execute_setup_operation(self, operation: SetupOperation) -> SetupExecutionResult:
        if self._state in {"mission_started", "invalidated"}:
            self._state = "invalidated"
            raise PostStartMutationError("POST_START_MUTATION_FORBIDDEN")
        if self._state != "preparing":
            raise RuntimeError("SCENARIO_SETUP_WINDOW_CLOSED")
        return await self._executor.execute(operation)

    async def prepare(self, spec: ScenarioSpec, *, run_id: str) -> ScenarioReceipt:
        if self._state != "idle":
            raise RuntimeError("SCENARIO_ALREADY_PREPARED")
        started_at_ms = self._now_ms()
        self._state = "preparing"
        try:
            world_ref = await self._environment.prepare_disposable_world(spec, run_id)
            store_refs = await self._environment.create_clean_stores(run_id, spec.clean_stores)
        except Exception:
            self._state = "invalidated"
            raise
        receipts: list[ScenarioOperationReceipt] = []
        for operation in compile_setup_operations(spec):
            result = await self.execute_setup_operation(operation)
            command = render_rcon_command(operation)
            receipts.append(
                ScenarioOperationReceipt(
                    operation_id=operation.operation_id,
                    operation_kind=operation.kind,
                    command_hash=canonical_json_hash({"rcon": command}),
                    applied_at_ms=self._now_ms(),
                    outcome=result.outcome,
                    response_code=result.response_code,
                )
            )
            if result.outcome != "success":
                self._state = "invalidated"
                raise RuntimeError(f"SCENARIO_SETUP_FAILED:{result.response_code}")
        self._state = "prepared"
        self._receipt = ScenarioReceipt(
            run_id=run_id,
            scenario_id=spec.scenario_id,
            scenario_hash=spec.canonical_hash,
            started_at_ms=started_at_ms,
            finished_at_ms=self._now_ms(),
            clean_store_namespace=run_id,
            world_ref=world_ref,
            store_refs=store_refs,
            operations=tuple(receipts),
        )
        return self._receipt

    def start_mission(self, receipt: ScenarioReceipt, *, mission_id: str) -> MissionStartBoundary:
        if self._state != "prepared" or receipt != self._receipt:
            raise RuntimeError("SCENARIO_RECEIPT_MISMATCH")
        self._state = "mission_started"
        return MissionStartBoundary(
            run_id=receipt.run_id,
            scenario_id=receipt.scenario_id,
            scenario_receipt_hash=receipt.canonical_hash,
            mission_id=mission_id,
            started_at_ms=self._now_ms(),
        )
