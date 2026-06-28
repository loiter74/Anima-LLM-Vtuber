"""Survival iron runner — the core state machine for wood-to-iron-gear progression.

Python decides the phase; Node.js executes atomic actions; LLM is auxiliary only.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from .inventory import (
    PHASE_COMPLETION,
    all_goals_satisfied,
    normalize_inventory,
    resolve_block_type,
)
from .models import (
    IRON_SURVIVAL_GOALS,
    FailureCategory,
    PhaseResult,
    RunReport,
    SurvivalPhase,
)
from .recovery import (
    RecoveryAction,
    check_safety,
    get_phase_retry_budget,
    map_collect_failure,
    map_craft_failure,
    map_smelt_failure,
)

# Maximum time for the entire run (45 minutes)
GLOBAL_TIMEOUT_SECONDS = 45 * 60


class SurvivalIronRunner:
    """Drives the bot from empty inventory to iron gear through explicit phases."""

    def __init__(self, bridge: Any, *, max_global_timeout: float = GLOBAL_TIMEOUT_SECONDS):
        self._bridge = bridge
        self._max_global_timeout = max_global_timeout
        self._start_time = 0.0
        self._interrupted = False

    async def run(self) -> RunReport:
        """Execute the full iron survival phase loop."""
        report = RunReport()
        self._start_time = time.time()
        logger.info("[SurvivalRunner] Starting iron survival run")

        for phase in SurvivalPhase:
            if phase == SurvivalPhase.DONE:
                break
            if self._interrupted:
                logger.warning("[SurvivalRunner] Run interrupted")
                break
            if self._global_timeout_exceeded():
                logger.warning("[SurvivalRunner] Global timeout exceeded")
                break

            report.current_phase = phase
            phase_result = await self._run_phase(phase, report)
            report.phase_results.append(phase_result)

            if not phase_result.success:
                logger.error(
                    f"[SurvivalRunner] Phase {phase.value} failed: "
                    f"{phase_result.failure_category} \u2014 {phase_result.failure_message}"
                )
                break
            logger.info(f"[SurvivalRunner] Phase {phase.value} completed")

        status = await self._send_command("status")
        if status and isinstance(status, dict):
            result = status.get("result", status)
            if isinstance(result, dict):
                raw_inv = result.get("inventory", {})
                report.final_inventory = normalize_inventory(raw_inv)
                report.deaths = self._count_deaths(result)

        report.end_time = time.time()
        report.completed = all_goals_satisfied(report.final_inventory, IRON_SURVIVAL_GOALS)
        logger.info(
            f"[SurvivalRunner] Run finished: completed={report.completed}, "
            f"elapsed={report.elapsed_seconds:.0f}s, deaths={report.deaths}"
        )
        return report

    def interrupt(self) -> None:
        self._interrupted = True

    async def _run_phase(self, phase: SurvivalPhase, report: RunReport) -> PhaseResult:
        result = PhaseResult(phase=phase, success=True)
        phase_start = time.time()
        retry_budget = get_phase_retry_budget(phase)

        if phase in (SurvivalPhase.COBBLESTONE, SurvivalPhase.IRON_ORE, SurvivalPhase.FUEL):
            status = await self._send_command("status")
            if status and isinstance(status, dict):
                status_data = status.get("result", status)
                if isinstance(status_data, dict):
                    report.status_snapshots.append(status_data)
                    safety = check_safety(status_data)
                    if not safety.safe and safety.should_pause:
                        result.mark_failure(FailureCategory.SAFETY_PAUSE, safety.reason)
                        result.elapsed_ms = (time.time() - phase_start) * 1000
                        return result

        actions = self._get_phase_actions(phase)
        for action_def in actions:
            # Check if phase goal is already met
            await self._refresh_inventory(report)
            if self._phase_goal_met(phase, report):
                break

            success = False
            last_error = ""
            last_error_raw: str | dict = ""

            for attempt in range(retry_budget + 1):
                if self._global_timeout_exceeded() or self._interrupted:
                    result.mark_failure(FailureCategory.TIMEOUT, "Global timeout or interrupt")
                    result.elapsed_ms = (time.time() - phase_start) * 1000
                    return result

                action_result = await self._send_command(
                    action_def.action,
                    action_def.params,
                    timeout=action_def.timeout,
                )

                if action_result is None:
                    last_error = "Bridge not responding"
                    last_error_raw = last_error
                    result.record_action(action_def.action, action_def.params, False, last_error)
                    continue

                if isinstance(action_result, dict) and action_result.get("status") == "success":
                    success = True
                    result.record_action(
                        action_def.action,
                        action_def.params,
                        True,
                        str(action_result.get("result", "")),
                    )
                    break
                else:
                    error_msg = ""
                    raw: str | dict = ""
                    if isinstance(action_result, dict):
                        raw_result = action_result.get("result")
                        if isinstance(raw_result, dict):
                            raw = raw_result
                            error_msg = raw_result.get("message", str(raw_result))
                        elif isinstance(raw_result, str):
                            raw = raw_result
                            error_msg = raw_result
                        else:
                            raw = str(raw_result) if raw_result is not None else ""
                            error_msg = raw
                    elif isinstance(action_result, str):
                        error_msg = action_result
                        raw = action_result
                    last_error = error_msg
                    last_error_raw = raw
                    result.record_action(action_def.action, action_def.params, False, error_msg)

            if not success:
                recovery = self._build_recovery(phase, action_def, last_error_raw)
                if recovery.should_abort:
                    result.mark_failure(FailureCategory.PHASE_IMPOSSIBLE, recovery.abort_reason)
                    result.elapsed_ms = (time.time() - phase_start) * 1000
                    return result

                for rec_action in recovery.actions:
                    rec_result = await self._send_command(
                        rec_action.action, rec_action.params, timeout=rec_action.timeout
                    )
                    is_success = (
                        isinstance(rec_result, dict) and rec_result.get("status") == "success"
                    )
                    result.record_action(
                        rec_action.action,
                        rec_action.params,
                        is_success,
                        str(rec_result.get("result", "")) if isinstance(rec_result, dict) else "",
                    )

                await self._refresh_inventory(report)

                if not self._phase_goal_met(phase, report):
                    result.mark_failure(
                        FailureCategory.ACTION_FAILED,
                        f"Phase {phase.value} failed after recovery: {last_error}",
                    )
                    result.elapsed_ms = (time.time() - phase_start) * 1000
                    return result

        result.elapsed_ms = (time.time() - phase_start) * 1000
        return result

    def _get_phase_actions(self, phase: SurvivalPhase):
        if phase == SurvivalPhase.WOOD:
            return [
                RecoveryAction(
                    "collect", {"block_type": "oak_log", "count": 5}, "Collect 5 logs", 120.0
                )
            ]
        if phase == SurvivalPhase.CRAFTING_TABLE:
            # Only craft planks if we don't have enough; always craft table
            return [
                RecoveryAction("craft", {"recipe": "oak_planks", "count": 4}, "Craft planks"),
                RecoveryAction("craft", {"recipe": "crafting_table", "count": 1}, "Craft table"),
            ]
        if phase == SurvivalPhase.WOODEN_PICKAXE:
            return [
                RecoveryAction("craft", {"recipe": "stick", "count": 4}, "Craft sticks"),
                RecoveryAction(
                    "craft", {"recipe": "wooden_pickaxe", "count": 1}, "Craft wooden pickaxe"
                ),
            ]
        if phase == SurvivalPhase.COBBLESTONE:
            return [
                RecoveryAction(
                    "collect",
                    {"block_type": "stone", "count": 12},
                    "Mine 12 stone for cobblestone",
                    120.0,
                )
            ]
        if phase == SurvivalPhase.STONE_KIT:
            return [
                RecoveryAction(
                    "craft", {"recipe": "stone_pickaxe", "count": 1}, "Craft stone pickaxe"
                ),
                RecoveryAction("craft", {"recipe": "stone_sword", "count": 1}, "Craft stone sword"),
                RecoveryAction("craft", {"recipe": "furnace", "count": 1}, "Craft furnace"),
            ]
        if phase == SurvivalPhase.FUEL:
            return [
                RecoveryAction(
                    "collect", {"block_type": "coal_ore", "count": 3}, "Mine 3 coal ore", 120.0
                )
            ]
        if phase == SurvivalPhase.IRON_ORE:
            return [
                RecoveryAction(
                    "collect", {"block_type": "iron_ore", "count": 3}, "Mine 3 iron ore", 180.0
                )
            ]
        if phase == SurvivalPhase.SMELT_IRON:
            return [
                RecoveryAction(
                    "smelt", {"item": "raw_iron", "fuel": "coal", "count": 3}, "Smelt 3 iron", 120.0
                )
            ]
        if phase == SurvivalPhase.IRON_GEAR:
            return [
                RecoveryAction(
                    "craft", {"recipe": "iron_pickaxe", "count": 1}, "Craft iron pickaxe"
                ),
                RecoveryAction("craft", {"recipe": "iron_sword", "count": 1}, "Craft iron sword"),
                RecoveryAction(
                    "craft", {"recipe": "iron_chestplate", "count": 1}, "Craft iron chestplate"
                ),
            ]
        return []

    def _phase_goal_met(self, phase: SurvivalPhase, report: RunReport) -> bool:
        check = PHASE_COMPLETION.get(phase.value)
        if not check:
            return True
        inv = report.final_inventory or {}
        return all(inv.get(item, 0) >= count for item, count in check.items())

    def _build_recovery(self, phase, action, error):
        if action.action in ("collect", "mine"):
            plan = map_collect_failure(
                action.params.get("block_type", ""),
                error,
                phase,
                requested_count=action.params.get("count", 1),
            )
            for rec_action in plan.actions:
                if rec_action.action in ("collect", "mine"):
                    self._resolve_collect_block_type(rec_action)
            return plan
        if action.action == "craft":
            return map_craft_failure(action.params.get("recipe", ""), error)
        if action.action == "smelt":
            return map_smelt_failure(
                action.params.get("item", ""), action.params.get("fuel", ""), error
            )
        from .recovery import RecoveryPlan

        return RecoveryPlan()

    @staticmethod
    def _resolve_collect_block_type(action):
        item = action.params.get("block_type", "")
        block = resolve_block_type(item)
        if block is not None:
            action.params["block_type"] = block

    async def _refresh_inventory(self, report):
        status = await self._send_command("status")
        if status and isinstance(status, dict):
            result = status.get("result", status)
            if isinstance(result, dict):
                raw_inv = result.get("inventory", {})
                report.final_inventory = normalize_inventory(raw_inv)
        return report.final_inventory

    async def _send_command(self, action, params=None, timeout=60.0):
        try:
            if not self._bridge or not self._bridge.is_running:
                return None
            return await self._bridge.send_command(action, params, timeout=timeout)
        except Exception as e:
            logger.error(f"[SurvivalRunner] Bridge command '{action}' exception: {e}")
            return None

    def _global_timeout_exceeded(self):
        return (time.time() - self._start_time) > self._max_global_timeout

    @staticmethod
    def _count_deaths(status_data):
        return status_data.get("deaths", 0)
