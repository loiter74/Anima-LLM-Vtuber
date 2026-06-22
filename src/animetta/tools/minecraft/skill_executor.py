"""Skill execution engine for Minecraft skills."""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from .skill_conditions import check_preconditions
from .skill_models import Skill, SkillResult

if TYPE_CHECKING:
    from .bridge import MinecraftBridge

_CRITICAL_HEALTH: float = 4.0
_MIN_DURATION_SECONDS = 1e-9


def _elapsed_since(start: float) -> float:
    return max(time.monotonic() - start, _MIN_DURATION_SECONDS)


async def _handle_threat(
    bridge: MinecraftBridge,
    ctx: dict[str, Any],
) -> tuple[bool, str | None]:
    """Attempt to neutralise the current threat."""
    logger.warning("[SkillLibrary] Threat detected — pausing skill to engage hostile")

    try:
        resp = await bridge.send_command(
            "attack", {"target": "nearest_hostile"}, timeout=15.0
        )
    except (TimeoutError, Exception) as exc:
        reason = f"Threat handling failed: {type(exc).__name__}: {exc}"
        logger.error(f"[SkillLibrary] {reason}")
        return False, reason

    if resp.get("status") != "success":
        reason = f"Attack command returned error: {resp.get('result', 'unknown')}"
        logger.error(f"[SkillLibrary] {reason}")
        return False, reason

    try:
        status_resp = await bridge.send_command("status", {}, timeout=10.0)
        if status_resp.get("status") == "success":
            result = status_resp.get("result", {})
            if isinstance(result, dict):
                new_health = result.get("health", ctx.get("health", 20.0))
                ctx["health"] = new_health
                if new_health < _CRITICAL_HEALTH:
                    reason = (
                        f"Health too low after combat ({new_health:.1f} < "
                        f"{_CRITICAL_HEALTH:.1f}) — aborting skill"
                    )
                    logger.error(f"[SkillLibrary] {reason}")
                    return False, reason
    except Exception:
        logger.debug("[SkillLibrary] Could not refresh health after combat")

    logger.info("[SkillLibrary] Threat handled — resuming skill")
    return True, None


async def execute_skill(
    skill: Skill,
    bridge: MinecraftBridge,
    context: dict[str, Any] | None = None,
    *,
    threat_check_interval: int = 3,
) -> SkillResult:
    """Execute all steps of a skill via the Minecraft bridge."""
    ctx: dict[str, Any] = dict(context) if context else {}
    start = time.monotonic()

    if not check_preconditions(skill.preconditions, ctx):
        duration = _elapsed_since(start)
        await _update_stats(skill, success=False, duration=duration)
        return SkillResult(
            success=False,
            skill_id=skill.id,
            failed_at=-1,
            reason="Skill-level preconditions not met",
            duration=duration,
        )

    for idx, step in enumerate(skill.steps):
        if threat_check_interval > 0 and idx % threat_check_interval == 0:
            threat_level = ctx.get("threat_level", 0)
            if threat_level >= 2:
                ok, reason = await _handle_threat(bridge, ctx)
                if not ok:
                    duration = _elapsed_since(start)
                    await _update_stats(skill, success=False, duration=duration)
                    return SkillResult(
                        success=False,
                        skill_id=skill.id,
                        failed_at=idx,
                        reason=reason,
                        duration=duration,
                    )

        if not check_preconditions(step.preconditions, ctx):
            duration = _elapsed_since(start)
            await _update_stats(skill, success=False, duration=duration)
            return SkillResult(
                success=False,
                skill_id=skill.id,
                failed_at=idx,
                reason=f"Step {idx} ({step.name}) preconditions not met",
                duration=duration,
            )

        attempts = 1 + step.retry
        last_error: str | None = None

        for attempt in range(attempts):
            try:
                resp = await bridge.send_command(
                    step.name, step.params, timeout=step.timeout
                )
            except TimeoutError:
                last_error = f"Step {idx} ({step.name}) timed out after {step.timeout}s"
                logger.warning(
                    f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
                )
                continue
            except Exception as exc:
                last_error = f"Step {idx} ({step.name}) raised {type(exc).__name__}: {exc}"
                logger.warning(
                    f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
                )
                continue

            status = resp.get("status", "error")
            if status == "success":
                result_data = resp.get("result")
                if isinstance(result_data, dict):
                    ctx.update(result_data)
                elif result_data is not None:
                    ctx[f"step_{idx}_result"] = result_data
                last_error = None
                break

            last_error = (
                f"Step {idx} ({step.name}) returned error: {resp.get('result', 'unknown')}"
            )
            logger.warning(
                f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
            )

        if last_error is not None:
            duration = _elapsed_since(start)
            await _update_stats(skill, success=False, duration=duration)
            return SkillResult(
                success=False,
                skill_id=skill.id,
                failed_at=idx,
                reason=last_error,
                duration=duration,
            )

    duration = _elapsed_since(start)
    await _update_stats(skill, success=True, duration=duration)
    return SkillResult(
        success=True,
        skill_id=skill.id,
        duration=duration,
        context_updates=ctx,
    )


async def _update_stats(skill: Skill, *, success: bool, duration: float) -> None:
    """Update running statistics on a skill."""
    if success:
        skill.success_count += 1
    else:
        skill.fail_count += 1

    total = skill.success_count + skill.fail_count
    if total == 1:
        skill.avg_duration = duration
    else:
        skill.avg_duration = skill.avg_duration * 0.8 + duration * 0.2

    skill.last_used = datetime.now().isoformat()
