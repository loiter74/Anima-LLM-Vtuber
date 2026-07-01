"""
Autonomous Behavior Loop — drives AI decision-making for Minecraft Bot

Architecture:
    AutonomousLoop
      ├── RulesEngine (rules.md → priorities, building target, chat config)
      ├── WorldState (mc_status() → parsed environment snapshot)
      ├── Loop tick: evaluate → decide → execute → cooldown
      ├── Collect-build pipeline (material gaps → gather → build)
      └── Proactive chat (trigger-based messaging to players)

Lifecycle:
    1. start() → begin loop
    2. pause() → LLM instruction arrives, suspend autonomous decisions
    3. resume() → LLM instruction complete, resume
    4. stop() → cancel loop, cleanup
"""

import asyncio
import contextlib
import random
import time
from typing import TYPE_CHECKING

from loguru import logger

from ..other.trace_recorder import TraceRecorder
from ..other.world_state import WorldState
from ..skill.extractor import SkillExtractor
from ..skill.validator import SkillValidator
from .rules_engine import RulesEngine

if TYPE_CHECKING:
    from ..core.bridge import MinecraftBridge
    from ..skill.library import SkillLibrary
    from .trace_recorder import TaskTrace


# ── Cooldown tracker ──


class CooldownTracker:
    """Per-action cooldown to prevent spam"""

    def __init__(self, default_cooldown: float = 30.0):
        self._cooldowns: dict[str, float] = {}  # action -> last_executed_time
        self._default = default_cooldown

    def can_execute(self, action: str) -> bool:
        """Check if cooldown has expired"""
        last = self._cooldowns.get(action, 0)
        return (time.time() - last) >= self._default

    def mark_executed(self, action: str):
        self._cooldowns[action] = time.time()

    def reset(self, action: str):
        self._cooldowns.pop(action, None)


# ── Autonomous Loop ──


class AutonomousLoop:
    """Perception → Evaluation → Decision → Execution loop"""

    # Decision outcomes
    ACTION_SURVIVE = "survive"
    ACTION_GATHER = "gather"
    ACTION_BUILD = "build"
    ACTION_CHAT = "chat"
    ACTION_EXPLORE = "explore"
    ACTION_IDLE = "idle"
    ACTION_EXECUTE_SKILL = "execute_skill"

    def __init__(
        self,
        bridge: "MinecraftBridge",
        rules: RulesEngine | None = None,
        skill_library: "SkillLibrary | None" = None,
        planner=None,
        config=None,
        trace_recorder: TraceRecorder | None = None,
        skill_extractor: SkillExtractor | None = None,
        skill_validator: SkillValidator | None = None,
        cleanup_chance: float = 0.05,
        training_tracker=None,
    ):
        self._bridge = bridge
        self._rules = rules or RulesEngine()
        self._running = False
        self._paused = False
        self._loop_task: asyncio.Task | None = None
        self._cooldown = CooldownTracker(default_cooldown=30.0)

        # Voyager-style components
        self._skill_library = skill_library
        self._planner = planner
        self._config = config or {}
        self._llm_available = planner is not None

        # Trace & skill-learning components
        self._trace_recorder = trace_recorder
        self._skill_extractor = skill_extractor
        self._skill_validator = skill_validator

        # Auto-cleanup probability (per tick)
        self._cleanup_chance = cleanup_chance

        # Collect-build state
        self._build_site: dict | None = None  # {"x", "y", "z"}
        self._current_step: int = 0
        self._gathering_for: str | None = None
        self._chat_cooldown_until: float = 0.0

        # Safety: base position (set on first night return or manual trigger)
        self._base_pos: dict | None = None

        # T10: Voyager 阶段（learn/live/fallback）+ 训练充分判据
        self._voyager_mode = "fallback"
        self._training_tracker = training_tracker

        logger.info(
            "[AutonomousLoop] Initialized with rules for '{}'", self._rules.rules.character_name
        )

    # ── Lifecycle ──

    async def start(self):
        """Start the autonomous decision loop"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("[AutonomousLoop] Started (interval=5-10s)")

    async def stop(self):
        """Stop the autonomous loop"""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        logger.info("[AutonomousLoop] Stopped")

    def pause(self):
        """Pause autonomous decisions (e.g., during LLM instruction)"""
        self._paused = True
        logger.debug("[AutonomousLoop] Paused for LLM instruction")

    def resume(self):
        """Resume autonomous decisions after LLM instruction"""
        self._paused = False
        logger.debug("[AutonomousLoop] Resumed")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Voyager 阶段切换（mc-bot-voyager-learning T10）──

    def set_voyager_mode(self, mode: str) -> None:
        """设置 Voyager 阶段：learn / live / fallback。"""
        self._voyager_mode = mode
        logger.info(f"[AutonomousLoop] voyager mode = {mode}")

    @property
    def voyager_mode(self) -> str:
        return self._voyager_mode

    def _check_training_sufficient(self) -> None:
        """训练充分判据达标 → learn 自动提升为 live（T10）。

        三选一（技术树覆盖 / 近期成功率 / 物品发现数）。仅 learn 模式触发；
        live 期不生成代码，须回落 Survival Runner（见 live_agent）。
        """
        if self._voyager_mode != "learn" or self._training_tracker is None:
            return
        ok, reason = self._training_tracker.sufficiency()
        if ok:
            logger.success(
                f"[AutonomousLoop] 训练充分 ({reason}) → learn→live 自动提升"
            )
            self._voyager_mode = "live"

    async def _threat_check(self) -> bool:
        """Quick threat check — if hostile nearby, attack and return True"""
        try:
            status = await self._bridge.send_command("status", timeout=5.0)
            state = WorldState.from_status(status)
            if state.get_threat_level() >= 2 and state.nearest_threat_distance < 15:
                logger.info("[AutonomousLoop] Threat detected during action! Attacking.")
                await self._bridge.send_command(
                    "attack", {"target": "nearest_hostile"}, timeout=10.0
                )
                return True
        except Exception:
            pass
        return False

    # ── Main Loop ──

    async def _loop(self):
        """Main autonomous loop: tick every 3-8 seconds (faster)"""
        interval = random.uniform(3, 8)
        while self._running:
            await asyncio.sleep(interval)

            if self._paused:
                interval = random.uniform(3, 8)
                continue

            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AutonomousLoop] Tick error: {e}")
            interval = random.uniform(3, 8)

    async def _tick(self):
        """One evaluation-execution cycle"""
        # 1. Get world state
        status = await self._bridge.send_command("status", timeout=10.0)
        state = WorldState.from_status(status)

        # 2. Evaluate and decide (threat detection is in _evaluate)
        action, params = await self._evaluate(state)

        if action == self.ACTION_IDLE:
            return

        # 3. Execute
        await self._execute(action, params, state)

        # 4. Mark cooldown
        self._cooldown.mark_executed(action)

        # 5. Auto-cleanup low-quality skills (probabilistic)
        if self._skill_library and random.random() < self._cleanup_chance:
            asyncio.create_task(self._skill_library.cleanup())

        # 6. T10: 训练充分判据 → learn→live 自动提升（best-effort，不影响主循环）
        if self._training_tracker is not None:
            self._training_tracker.update_discovered(getattr(state, "inventory", {}) or {})
            self._check_training_sufficient()

    # ── Evaluation & Decision ──

    async def _evaluate(self, state: WorldState) -> tuple[str, dict | None]:
        """Priority-based decision engine with LLM fallback"""

        # === SURVIVAL (always #1) ===
        fall_risk_fn = getattr(state, "get_fall_risk_level", None)
        fall_risk = fall_risk_fn() if callable(fall_risk_fn) else 0
        if not isinstance(fall_risk, (int, float)):
            fall_risk = 0
        has_water_bucket = bool(getattr(state, "has_water_bucket", False))
        if fall_risk >= 2 and has_water_bucket:
            return (
                self.ACTION_SURVIVE,
                {
                    "reason": "fall_risk",
                    "method": "water_bucket_clutch",
                    "fall_risk": fall_risk,
                },
            )

        # Threat check
        threat_level = state.get_threat_level()
        if threat_level >= 2 and state.nearest_threat_distance < 15:
            return (self.ACTION_SURVIVE, {"reason": "threat_nearby", "threat_level": threat_level})

        # Health check
        if state.health < self._rules.auto_heal_threshold:
            return (self.ACTION_SURVIVE, {"reason": "low_health", "health": state.health})

        # Night safety
        if state.is_night and self._rules.return_to_base_at_night and self._base_pos:
            dist = state.distance_to(self._base_pos["x"], self._base_pos["y"], self._base_pos["z"])
            if dist > 5:
                return (self.ACTION_SURVIVE, {"reason": "night_return", "base": self._base_pos})

        # === SKILL LIBRARY MATCHING ===
        if self._skill_library:
            matching = await self._skill_library.match_skills(
                {
                    "health": state.health,
                    "food": state.food,
                    "is_day": state.is_day,
                    "is_night": state.is_night,
                    "is_raining": state.is_raining,
                    "inventory": state.inventory,
                    "threat_level": state.get_threat_level(),
                    "fall_risk": state.get_fall_risk_level(),
                }
            )
            if matching:
                return (self.ACTION_EXECUTE_SKILL, {"skill_id": matching[0].id})

        # === MAINTENANCE (building progress) ===
        if self._rules.rules.building and self._current_step < len(
            self._rules.rules.building.build_plan
        ):
            building = self._rules.rules.building
            required = building.required_materials

            # Check if we have all materials
            gaps = state.get_material_gaps(required)
            if gaps:
                # Need to gather first
                if not self._cooldown.can_execute("gather"):
                    pass  # cooldown active, skip
                else:
                    target_material = list(gaps.keys())[0]
                    return (
                        self.ACTION_GATHER,
                        {"material": target_material, "count": gaps[target_material]},
                    )
            else:
                # Have materials, time to build
                if not self._cooldown.can_execute("build"):
                    pass
                else:
                    step = building.build_plan[self._current_step]
                    if not self._build_site:
                        # Select build site at current position
                        self._build_site = {"x": state.x, "y": state.y - 1, "z": state.z}
                        logger.info(f"[AutonomousLoop] Build site selected at {self._build_site}")
                    return (
                        self.ACTION_BUILD,
                        {
                            "step": self._current_step,
                            "block": step.block,
                            "action": step.action,
                            "description": step.description,
                            "site": self._build_site,
                        },
                    )

        # === SOCIAL (chat) ===
        if self._cooldown.can_execute("chat"):
            trigger = self._get_chat_trigger(state)
            if trigger:
                return (self.ACTION_CHAT, {"trigger": trigger})

        # === EXPLORATION (default fallback) ===
        if self._cooldown.can_execute("explore"):
            # Simple random walk
            dx = random.randint(-10, 10)
            dz = random.randint(-10, 10)
            return (self.ACTION_EXPLORE, {"x": state.x + dx, "z": state.z + dz})

        return (self.ACTION_IDLE, None)

    # ── Execution ──

    async def _execute(self, action: str, params: dict | None, state: WorldState):
        """Execute the decided action with timeout and optional trace recording."""
        if params is None:
            return
        timeout = 30.0

        # ── Trace: start recording ──
        recorder = self._trace_recorder
        state_before: dict = {}
        action_start: float = 0.0
        if recorder:
            state_before = self._world_state_to_dict(state)
            recorder.start_trace(f"{action}: {params}")
            action_start = time.monotonic()

        success = False
        try:
            if action == self.ACTION_SURVIVE:
                await self._execute_survive(params, state)
            elif action == self.ACTION_GATHER:
                await self._execute_gather(params, state)
            elif action == self.ACTION_BUILD:
                await self._execute_build(params, state, timeout)
            elif action == self.ACTION_CHAT:
                await self._execute_chat(params)
            elif action == self.ACTION_EXPLORE:
                await self._execute_explore(params, timeout)
            elif action == self.ACTION_EXECUTE_SKILL:
                await self._execute_skill(params, state)
            success = True

        except TimeoutError:
            logger.warning(f"[AutonomousLoop] Action '{action}' timed out")
            self._cooldown.reset(action)
        except Exception as e:
            logger.error(f"[AutonomousLoop] Action '{action}' failed: {e}")

        # ── Trace: record action and end trace ──
        if recorder:
            duration = time.monotonic() - action_start
            try:
                status = await self._bridge.send_command("status", timeout=5.0)
                state_after = self._world_state_to_dict(WorldState.from_status(status))
            except Exception:
                state_after = state_before

            recorder.record_action(
                action=action,
                params=params,
                result="success" if success else "error",
                state_before=state_before,
                state_after=state_after,
                duration=duration,
                error=None if success else "action failed",
            )
            trace = recorder.end_trace("success" if success else "failed")
            asyncio.create_task(recorder.save_trace(trace))

            # Trigger skill extraction on success
            if success and self._skill_extractor:
                asyncio.create_task(self._trigger_skill_extraction(trace, state))

    # ── Survival Actions ──

    async def _execute_survive(self, params: dict, state: WorldState):
        reason = params.get("reason", "unknown")
        if reason == "threat_nearby":
            # Try to attack nearest hostile
            await self._bridge.send_command("attack", {"target": "nearest_hostile"}, timeout=15.0)
        elif reason == "fall_risk":
            method = params.get("method", "water_bucket_clutch")
            await self._bridge.send_command(method, {}, timeout=3.0)
        elif reason == "low_health":
            # Regenerate naturally or eat
            logger.info(f"[AutonomousLoop] Low health ({state.health}), auto-healing...")
        elif reason == "night_return":
            base = params.get("base", {})
            if base:
                await self._bridge.send_command(
                    "goto",
                    {
                        "x": int(base.get("x", 0)),
                        "y": int(base.get("y", 65)),
                        "z": int(base.get("z", 0)),
                    },
                    timeout=60.0,
                )
                # Save current position as base for future reference
                if not self._base_pos:
                    self._base_pos = {"x": state.x, "y": state.y, "z": state.z}

    # ── Collect-Build Pipeline ──

    async def _execute_gather(self, params: dict, state: WorldState):
        material = params.get("material", "oak_log")
        count = params.get("count", 8)
        logger.info(f"[AutonomousLoop] Gathering: {material} x{count}")

        # Check threat before long action
        await self._threat_check()

        result = await self._bridge.send_command(
            "collect",
            {
                "block_type": material,
                "count": min(count, 16),
            },
            timeout=60.0,
        )

        # Update state after gathering
        if result.get("status") == "success":
            self._gathering_for = None
            # Optionally trigger chat
            if random.random() < 0.3:
                chat_msg = self._rules.get_chat_message(
                    "found_ore" if "ore" in material else "gathering_start"
                )
                if chat_msg:
                    await self._bridge.send_command("chat", {"message": chat_msg}, timeout=5.0)

    async def _execute_build(self, params: dict, state: WorldState, timeout: float):
        step_idx = params.get("step", 0)
        block = params.get("block", "cobblestone")
        site = params.get("site", {})
        desc = params.get("description", "")

        logger.info(f"[AutonomousLoop] Building step {step_idx}: {desc}")
        bx = int(site.get("x", state.x))
        by = int(site.get("y", 65))
        bz = int(site.get("z", state.z))

        # Actually place the block
        await self._bridge.send_command(
            "place",
            {
                "block_type": block,
                "x": bx,
                "y": by + 1,
                "z": bz,
            },
            timeout=timeout,
        )

        # Advance build step
        self._current_step = step_idx + 1

        # Trigger chat
        if self._rules.rules.building and self._current_step >= len(
            self._rules.rules.building.build_plan
        ):
            chat_msg = self._rules.get_chat_message("building_complete")
            if chat_msg:
                await self._bridge.send_command("chat", {"message": chat_msg}, timeout=5.0)
        else:
            if random.random() < 0.3:
                chat_msg = self._rules.get_chat_message("building_progress")
                if chat_msg:
                    await self._bridge.send_command("chat", {"message": chat_msg}, timeout=5.0)

    # ── Proactive Chat ──

    def _get_chat_trigger(self, state: WorldState) -> str | None:
        """Determine if and why we should chat"""
        now = time.time()
        if now < self._chat_cooldown_until:
            return None

        if random.random() > self._rules.proactive_chat_chance:
            return None

        # Check triggers in priority order
        if state.player_count > 0:
            return "player_nearby"
        if state.is_night:
            return "night_time"
        if state.is_raining:
            return "rain_start"

        return None

    async def _execute_chat(self, params: dict):
        trigger = params.get("trigger", "player_nearby")
        msg = self._rules.get_chat_message(trigger)
        if msg:
            await self._bridge.send_command("chat", {"message": msg}, timeout=5.0)
            self._chat_cooldown_until = time.time() + self._rules.chat_cooldown

    # ── Exploration ──

    async def _execute_explore(self, params: dict, timeout: float):
        tx = int(params.get("x", 0))
        tz = int(params.get("z", 0))
        await self._threat_check()
        logger.debug(f"[AutonomousLoop] Exploring to ({tx}, ~, {tz})")
        await self._bridge.send_command("goto", {"x": tx, "y": 65, "z": tz}, timeout=timeout)

    # ── Skill Execution ──

    async def _execute_skill(self, params: dict, state: WorldState):
        """Execute a skill from the SkillLibrary with success/failure tracking."""
        skill_id = params.get("skill_id")
        if not (self._skill_library and skill_id):
            return

        context = {
            "health": state.health,
            "food": state.food,
            "is_day": state.is_day,
            "is_night": state.is_night,
            "inventory": state.inventory,
        }
        fall_risk = state.get_fall_risk_level()
        if fall_risk > 0:
            context["fall_risk"] = fall_risk
        result = await self._skill_library.execute_skill_by_id(skill_id, self._bridge, context)

        # Track success/failure in the library
        if result.success:
            await self._skill_library.update_success(skill_id)
            logger.info(f"[AutonomousLoop] Skill {skill_id} succeeded ({result.duration:.1f}s)")
        else:
            await self._skill_library.update_failure(skill_id)
            logger.warning(f"[AutonomousLoop] Skill {skill_id} failed: {result.reason}")

    # ── Helpers ──

    @staticmethod
    def _world_state_to_dict(state: WorldState) -> dict:
        """Convert a WorldState to a plain dict for trace recording."""
        return {
            "x": state.x,
            "y": state.y,
            "z": state.z,
            "health": state.health,
            "food": state.food,
            "is_day": state.is_day,
            "is_night": state.is_night,
            "is_raining": state.is_raining,
            "inventory": state.inventory,
            "player_count": state.player_count,
            "threat_level": state.get_threat_level(),
            "fall_risk": state.get_fall_risk_level(),
        }

    async def _trigger_skill_extraction(self, trace: "TaskTrace", state: WorldState) -> None:
        """Extract and store a new skill from a successful trace.

        Validates the extracted skill before adding it to the library.
        Runs as a background task to avoid blocking the main loop.
        """
        extractor = self._skill_extractor
        library = self._skill_library
        if not extractor or not library:
            return

        context = {
            "health": state.health,
            "food": state.food,
            "is_day": state.is_day,
            "is_night": state.is_night,
            "inventory": state.inventory,
        }

        try:
            skill = await extractor.extract(trace, context)
            if skill is None:
                return

            # Validate before saving
            if self._skill_validator:
                validation = self._skill_validator.validate(skill, context)
                if not validation.passed:
                    logger.warning(
                        f"[AutonomousLoop] Extracted skill '{skill.name}' failed validation: "
                        f"{validation.failures}"
                    )
                    return
                if validation.warnings:
                    logger.info(
                        f"[AutonomousLoop] Skill '{skill.name}' validation warnings: "
                        f"{validation.warnings}"
                    )

            added = await library.add_learned(skill)
            if added:
                logger.info(f"[AutonomousLoop] New skill learned: '{skill.name}' ({skill.id})")
            else:
                logger.debug(f"[AutonomousLoop] Skill '{skill.name}' rejected (duplicate)")

        except Exception as e:
            logger.error(f"[AutonomousLoop] Skill extraction failed: {type(e).__name__}: {e}")
