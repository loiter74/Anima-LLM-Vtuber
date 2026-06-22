"""
Minecraft AI Behavior Rules Engine

Parses rules.md YAML config and provides rule query/evaluation interface.
Implements Rule-based decision: priority-driven action selection with safety overrides.
"""
import os
import random
from dataclasses import dataclass, field

import yaml
from loguru import logger


@dataclass
class BuildPlanStep:
    action: str
    block: str
    description: str = ""
    area: str | None = None
    height: int | None = None


@dataclass
class BuildTarget:
    target: str
    blueprint: str
    required_materials: dict[str, int]
    build_plan: list[BuildPlanStep]
    build_site: dict | None = None  # {"x": int, "y": int, "z": int}
    current_step: int = 0


@dataclass
class ChatTopic:
    trigger: str
    messages: list[str]


@dataclass
class BehaviorRules:
    character_name: str = "AnimaBot"
    personality: str = ""
    priorities: list[str] = field(default_factory=lambda: [
        "survival", "maintenance", "building", "gathering", "social", "exploration"
    ])
    building: BuildTarget | None = None
    safety: dict = field(default_factory=lambda: {
        "return_to_base_at_night": True,
        "auto_heal_threshold": 10,
        "avoid_ravines": True,
        "max_build_height": 50,
    })
    chat: dict = field(default_factory=lambda: {
        "proactive_chance": 0.25,
        "cooldown_seconds": 30,
        "topics": [],
    })
    base_position: dict | None = None  # {"x": int, "y": int, "z": int}


class RulesEngine:
    """Loads, validates and queries behavior rules from rules.md"""

    # Safety hardcodes that override rules.md
    SAFETY_HARDCODED = {
        "no_griefing": True,
        "max_distance": 500,
        "min_health_to_fight": 6,
    }

    def __init__(self, rules_path: str | None = None, safety_config: dict | None = None):
        self._rules_path = rules_path or os.path.join(os.path.dirname(__file__), "rules.md")
        self._safety_config = safety_config or {}
        self.rules: BehaviorRules = BehaviorRules()
        self._load()

    def _load(self) -> None:
        """Load and parse rules.md"""
        try:
            with open(self._rules_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)

            if not raw or not isinstance(raw, dict):
                logger.warning("[RulesEngine] Empty or invalid rules.md, using defaults")
                return

            # Parse character
            self.rules.character_name = raw.get("character_name", self.rules.character_name)
            self.rules.personality = raw.get("personality", self.rules.personality)

            # Parse priorities
            raw_priorities = raw.get("priorities", [])
            if isinstance(raw_priorities, list) and len(raw_priorities) > 0:
                self.rules.priorities = raw_priorities

            # Parse building
            building_raw = raw.get("building", {})
            if building_raw:
                build_plan = []
                for step in building_raw.get("build_plan", []):
                    build_plan.append(BuildPlanStep(
                        action=step.get("action", ""),
                        block=step.get("block", ""),
                        description=step.get("description", ""),
                        area=step.get("area"),
                        height=step.get("height"),
                    ))
                self.rules.building = BuildTarget(
                    target=building_raw.get("target", ""),
                    blueprint=building_raw.get("blueprint", ""),
                    required_materials=building_raw.get("required_materials", {}),
                    build_plan=build_plan,
                )

            # Parse safety (with hardcoded overrides)
            safety_raw = raw.get("safety", {})
            if safety_raw:
                self.rules.safety.update(safety_raw)
            # Apply safety hardcodes from config/tools.yaml
            for key in ("max_distance", "no_griefing"):
                if key in self._safety_config:
                    config_val = self._safety_config[key]
                    rules_val = self.rules.safety.get(key)
                    if rules_val is not None and config_val < rules_val if isinstance(config_val, int) else True:
                        logger.info(
                            f"[RulesEngine] Safety override: {key}={rules_val} -> {config_val} (from config/tools.yaml)"
                        )
                        self.rules.safety[key] = config_val

            # Parse chat
            chat_raw = raw.get("chat", {})
            if chat_raw:
                self.rules.chat["proactive_chance"] = chat_raw.get(
                    "proactive_chance", self.rules.chat["proactive_chance"]
                )
                self.rules.chat["cooldown_seconds"] = chat_raw.get(
                    "cooldown_seconds", self.rules.chat["cooldown_seconds"]
                )
                topics = []
                for t in chat_raw.get("topics", []):
                    topics.append(ChatTopic(
                        trigger=t.get("trigger", ""),
                        messages=t.get("messages", []),
                    ))
                self.rules.chat["topics"] = topics

            self._validate()
            logger.info(f"[RulesEngine] Loaded rules for '{self.rules.character_name}' "
                       f"({len(self.rules.priorities)} priorities, "
                       f"{len(self.rules.chat.get('topics', []))} chat topics)")

        except yaml.YAMLError as e:
            logger.error(f"[RulesEngine] Failed to parse rules.md: {e}")
        except Exception as e:
            logger.error(f"[RulesEngine] Failed to load rules.md: {e}")

    def _validate(self) -> None:
        """Validate rules for completeness and consistency"""
        warnings = []

        if not self.rules.priorities:
            warnings.append("No priorities defined")

        if self.rules.building:
            bp = self.rules.building
            if not bp.target:
                warnings.append("Building target is empty")
            if not bp.required_materials:
                warnings.append("No required materials for building")
            if not bp.build_plan:
                warnings.append("No build plan steps defined")

        if self.rules.safety.get("auto_heal_threshold", 10) > 20:
            warnings.append("auto_heal_threshold > 20 (max health), will never trigger")

        for warning in warnings:
            logger.warning(f"[RulesEngine] Validation: {warning}")

    def get_priority(self, category: str) -> int:
        """Get the priority index for a behavior category (lower = higher priority)"""
        try:
            return self.rules.priorities.index(category)
        except ValueError:
            return len(self.rules.priorities)  # Unknown → lowest priority

    def get_chat_message(self, trigger: str) -> str | None:
        """Get a random chat message for the given trigger"""
        topics: list[ChatTopic] = self.rules.chat.get("topics", [])
        for topic in topics:
            if topic.trigger == trigger and topic.messages:
                return random.choice(topic.messages)
        return None

    @property
    def proactive_chat_chance(self) -> float:
        return float(self.rules.chat.get("proactive_chance", 0.25))

    @property
    def chat_cooldown(self) -> float:
        return float(self.rules.chat.get("cooldown_seconds", 30))

    @property
    def auto_heal_threshold(self) -> int:
        return int(self.rules.safety.get("auto_heal_threshold", 10))

    @property
    def return_to_base_at_night(self) -> bool:
        return bool(self.rules.safety.get("return_to_base_at_night", True))

    def is_category_allowed(self, category: str) -> bool:
        """Check if a behavior category is in the priority list"""
        return category in self.rules.priorities
