"""Trusted-only Voyager live session."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from animetta.tools.gamebot.contracts import ActionOutcome, SkillExecutionResult
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import Skill

from .contracts import VoyagerSessionContext
from .policy import VoyagerPolicy


class FallbackRunner(Protocol):
    async def run_goal(
        self, goal: str, *, reason: str, parent_task_id: str
    ) -> dict[str, Any]: ...


class FallbackSession:
    """Controller-owned safety session whose results cannot validate parent goals."""

    def __init__(
        self,
        *,
        context: VoyagerSessionContext,
        runner: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._context = context
        self._runner = runner

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def run_goal(
        self, goal: str, *, reason: str, parent_task_id: str
    ) -> dict[str, Any]:
        fallback_task_id = f"fallback-{uuid4().hex}"
        raw = await self._runner(goal, task_id=fallback_task_id)
        result = dict(raw) if isinstance(raw, dict) else {"result": raw}
        for forbidden_evidence_key in (
            "receipt_hashes",
            "unlock_record",
            "evidence_refs",
        ):
            result.pop(forbidden_evidence_key, None)
        result.update(
            {
                "outcome": "fallback",
                "fallback": True,
                "evidence_eligible": False,
                "reason": reason,
                "parent_task_id": parent_task_id,
                "fallback_task_id": fallback_task_id,
            }
        )
        return result


def _execution_error(execution: SkillExecutionResult) -> str | None:
    if not execution.receipts:
        return "EMPTY_RECEIPT_CHAIN"
    for receipt in execution.receipts:
        if receipt.outcome is not ActionOutcome.SUCCESS:
            return receipt.error.code if receipt.error else receipt.outcome.value
    return None


class LiveSession:
    def __init__(
        self,
        *,
        context: VoyagerSessionContext,
        library: SkillLibrary,
        policy: VoyagerPolicy,
        fallback: FallbackRunner,
        degrade_threshold: int = 3,
    ) -> None:
        if degrade_threshold < 1:
            raise ValueError("degrade_threshold must be positive")
        self._context = context
        self._library = library
        self._policy = policy
        self._fallback = fallback
        self._degrade_threshold = degrade_threshold

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def _select_skill(self, goal: str) -> Skill | None:
        trusted = await self._library.match_trusted_skills({}, limit=10)
        if not trusted:
            return None
        words = {word for word in goal.lower().split() if len(word) > 1}

        def relevance(skill: Skill) -> int:
            text = f"{skill.name} {skill.description}".lower()
            return sum(word in text for word in words)

        trusted.sort(
            key=lambda skill: (
                -relevance(skill),
                -skill.success_rate,
                skill.consecutive_failures,
            )
        )
        return trusted[0]

    async def run_goal(self, goal: str) -> dict[str, Any]:
        parent_task_id = f"live-{uuid4().hex}"
        skill = await self._select_skill(goal)
        if skill is None:
            return await self._run_fallback(
                goal, reason="no_trusted_skill", parent_task_id=parent_task_id
            )

        code = str((skill.body or {}).get("code", ""))
        policy_report = self._policy.validate_code(code, self._context.manifest)
        if not policy_report.allowed:
            codes = ",".join(violation.code for violation in policy_report.violations)
            return await self._run_fallback(
                goal,
                reason=f"policy_rejected:{codes}",
                parent_task_id=parent_task_id,
            )

        execution = await self._context.runtime.eval_skill(
            code,
            allowed_capabilities=sorted(policy_report.authorized_capabilities),
            session_id=self._context.session_id,
            task_id=parent_task_id,
            correlation_id=f"live-eval-{uuid4().hex}",
            timeout=180.0,
        )
        error = _execution_error(execution)
        receipt_hashes = [receipt.content_hash for receipt in execution.receipts]
        if error is None:
            await self._library.update_success(skill.id)
            return {
                "outcome": "success",
                "skill_id": skill.id,
                "task_id": parent_task_id,
                "evidence_eligible": True,
                "receipt_hashes": receipt_hashes,
            }

        await self._library.update_failure(skill.id)
        if skill.consecutive_failures >= self._degrade_threshold:
            await self._library.demote_skill(
                skill.id,
                reason=f"{skill.consecutive_failures} consecutive live failures",
                session_id=self._context.session_id,
            )
        fallback = await self._run_fallback(
            goal,
            reason=f"skill_failed:{error}",
            parent_task_id=parent_task_id,
        )
        fallback["skill_id"] = skill.id
        fallback["failed_receipt_hashes"] = receipt_hashes
        return fallback

    async def _run_fallback(
        self, goal: str, *, reason: str, parent_task_id: str
    ) -> dict[str, Any]:
        result = await self._fallback.run_goal(
            goal,
            reason=reason,
            parent_task_id=parent_task_id,
        )
        result["evidence_eligible"] = False
        result.setdefault("reason", reason)
        result.setdefault("outcome", "fallback")
        result.setdefault("fallback", True)
        return result
