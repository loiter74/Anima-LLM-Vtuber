"""
World State - Encapsulates Minecraft bot state and provides analysis tools

Takes mc_status() output and enriches it with:
- Threat assessment (hostile entities nearby)
- Time/weather categorization
- Material gap analysis (inventory vs building targets)
- Entity classification (hostile/neutral/player/passive)
"""

import math
from dataclasses import dataclass, field


@dataclass
class Entity:
    name: str
    type: str  # "hostile" | "neutral" | "player" | "passive" | "unknown"
    distance: float = 99.0  # blocks away (estimated or from status)
    count: int = 1

    @property
    def is_threat(self) -> bool:
        return self.type == "hostile"


@dataclass
class WorldState:
    """Snapshotted bot state from mc_status()"""

    # Position
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    # Vital stats
    health: float = 20.0
    food: float = 20.0

    # Environment
    dimension: str = "overworld"
    time: str = "day"  # "day" | "sunset" | "night" | "sunrise"
    weather: str = "clear"  # "clear" | "rain" | "thunder"
    biome: str = "unknown"

    # Gameplay
    game_mode: str = "survival"

    # Movement / fall safety
    fall_distance: float = 0.0
    on_ground: bool = True
    velocity_y: float = 0.0

    # Inventory (block_type -> count)
    inventory: dict = field(default_factory=dict)

    # Entities
    entities: list[Entity] = field(default_factory=list)

    # Goal state
    current_goal: str | None = None

    @classmethod
    def from_status(cls, status_result: dict) -> "WorldState":
        """Parse mc_status() result dict into WorldState"""
        payload = status_result.get("result", {})
        if not isinstance(payload, dict):
            return cls()

        # Position
        pos = payload.get("position", {})
        x = pos.get("x", 0.0)
        y = pos.get("y", 0.0)
        z = pos.get("z", 0.0)

        # Environment
        time = payload.get("time", "day")
        weather = payload.get("weather", "clear")
        biome = payload.get("biome", "unknown")
        dimension = payload.get("dimension", "overworld")
        game_mode = payload.get("game_mode", "survival")

        # Movement / fall safety
        fall_distance = float(payload.get("fall_distance", 0.0) or 0.0)
        on_ground = bool(payload.get("on_ground", True))
        velocity = payload.get("velocity", {})
        velocity_y = 0.0
        if isinstance(velocity, dict):
            velocity_y = float(velocity.get("y", 0.0) or 0.0)

        # Vital stats
        health = payload.get("health", 20.0)
        food = payload.get("food", 20.0)

        # Inventory
        inventory = payload.get("inventory", {})
        if not isinstance(inventory, dict):
            inventory = {}

        # Entities
        entities = []
        nearby = payload.get("nearby_entities", {})
        if isinstance(nearby, dict):
            for entity_type in ("hostile", "neutral", "player", "passive"):
                # Can be int (count) or str (name)
                val = nearby.get(entity_type, 0)
                count = 1
                name = "unknown"
                if isinstance(val, dict):
                    # Extended format: {"count": 3, "distance": 5}
                    count = val.get("count", 1)
                    dist = val.get("distance", 10.0)
                    name = val.get("name", "unknown")
                elif isinstance(val, (int, float)):
                    count = int(val)
                    dist = 50.0  # default far distance for count-only (conservative)
                else:
                    continue
                if count > 0:
                    entities.append(
                        Entity(
                            name=name,
                            type=entity_type,
                            count=count,
                            distance=dist if entity_type == "hostile" else 20.0,
                        )
                    )

        return cls(
            x=x,
            y=y,
            z=z,
            health=health,
            food=food,
            dimension=dimension,
            time=time,
            weather=weather,
            biome=biome,
            game_mode=game_mode,
            fall_distance=fall_distance,
            on_ground=on_ground,
            velocity_y=velocity_y,
            inventory=inventory,
            entities=entities,
            current_goal=payload.get("current_goal"),
        )

    # ── Analysis Methods ──

    @property
    def is_night(self) -> bool:
        return self.time in ("night",)

    @property
    def is_day(self) -> bool:
        return self.time in ("day", "sunrise")

    @property
    def is_raining(self) -> bool:
        return self.weather in ("rain", "thunder")

    @property
    def is_injured(self) -> bool:
        return self.health < 10

    @property
    def is_hungry(self) -> bool:
        return self.food < 6

    @property
    def has_water_bucket(self) -> bool:
        return self.inventory.get("water_bucket", 0) > 0

    @property
    def hostile_count(self) -> int:
        return sum(e.count for e in self.entities if e.is_threat)

    @property
    def player_count(self) -> int:
        return sum(e.count for e in self.entities if e.type == "player")

    @property
    def nearest_threat_distance(self) -> float:
        min_d = 99.0
        for e in self.entities:
            if e.is_threat and e.distance < min_d:
                min_d = e.distance
        return min_d

    def get_threat_level(self) -> int:
        """
        Threat level: 0 (safe) to 3 (critical)
        0: No hostiles nearby
        1: 1-2 hostiles, far (>15 blocks)
        2: 3+ hostiles OR close (<15 blocks)
        3: Health < 6 AND hostiles nearby
        """
        hc = self.hostile_count
        if hc == 0:
            return 0
        if self.health <= 6:
            return 3
        if hc >= 3 or self.nearest_threat_distance < 15:
            return 2
        return 1

    def get_fall_risk_level(self) -> int:
        """
        Fall risk level: 0 (safe) to 3 (urgent).

        Mineflayer versions differ on whether fall distance or vertical velocity
        is the more reliable signal, so use both.
        """
        if self.on_ground:
            return 0
        if self.fall_distance >= 12 or self.velocity_y <= -1.1:
            return 3
        if self.fall_distance >= 6 or self.velocity_y <= -0.7:
            return 2
        if self.fall_distance >= 3 or self.velocity_y <= -0.35:
            return 1
        return 0

    def get_player_nearby(self) -> bool:
        """Check if any player is nearby"""
        return self.player_count > 0

    # ── Material gap analysis ──

    def get_material_gaps(self, required: dict[str, int]) -> dict[str, int]:
        """
        Calculate missing materials: required - inventory.
        Returns dict of material -> missing count (positive = missing, 0 or negative = enough).
        """
        gaps: dict[str, int] = {}
        for material, needed in required.items():
            have = self.inventory.get(material, 0)
            gap = max(0, needed - have)
            if gap > 0:
                gaps[material] = gap
        return gaps

    def has_material(self, material: str, amount: int = 1) -> bool:
        return self.inventory.get(material, 0) >= amount

    def distance_to(self, x: float, y: float, z: float) -> float:
        return math.sqrt((self.x - x) ** 2 + (self.y - y) ** 2 + (self.z - z) ** 2)
