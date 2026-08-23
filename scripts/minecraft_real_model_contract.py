"""Capture a fresh real-model natural-language to MissionSpec contract result."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from animetta.acceptance.minecraft_showcase import _normalize_model_execute_args
from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig
from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    starter_shelter_blueprint,
)
from animetta.tools.minecraft.core.tools import (
    MinecraftExecuteRequest,
    MinecraftOperateToolInput,
    get_minecraft_tools,
)
from animetta.tools.minecraft.mission.models import (
    NovelFactsAcquiredAtLeast,
    TrustedSkillsCreatedAtLeast,
    VanillaAdvancementsAddedAtLeast,
)
from animetta.tools.minecraft.showcase.runner import SHOWCASE_USER_TEXT
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import (
    BuildGoal,
    CombatGoal,
    EntityDefeated,
    StructureMatchesBlueprint,
)

USER_TEXT = SHOWCASE_USER_TEXT


def _starter_shelter_static_cost() -> BudgetUsage:
    return (
        BlueprintCompiler()
        .compile(
            starter_shelter_blueprint(),
            BlueprintBinding(origin=(0, 0, 0), materials={}),
        )
        .static_cost
    )


def _starter_shelter_budget_admissible(mission: Any) -> bool:
    static_cost = _starter_shelter_static_cost()
    return any(
        any(
            getattr(predicate, "blueprint_id", None) == "starter-shelter-v1"
            for predicate in objective.goal.success_predicates
        )
        and objective.budget.max_actions >= static_cost.max_actions
        and objective.budget.max_blocks_changed >= static_cost.max_blocks_changed
        for objective in mission.objectives
    )


def _semantic_assertions(validated: MinecraftExecuteRequest) -> dict[str, bool]:
    request = validated.request
    if request.kind != "mission":
        return {"mission_branch": False}
    mission = request.mission
    defeated_entities = {
        predicate.entity
        for objective in mission.objectives
        if isinstance(objective.goal, CombatGoal)
        for predicate in objective.goal.success_predicates
        if isinstance(predicate, EntityDefeated)
    }
    builds = [
        objective.goal for objective in mission.objectives if isinstance(objective.goal, BuildGoal)
    ]
    combats = [
        objective for objective in mission.objectives if isinstance(objective.goal, CombatGoal)
    ]
    completion = mission.completion_predicates
    serialized_mission = json.dumps(mission.model_dump(mode="json"), ensure_ascii=False).lower()
    production_limits = {
        "max_actions": 128,
        "max_strategy_attempts": 8,
        "max_travel_distance": 512,
        "max_blocks_changed": 128,
        "max_damage_taken": 8,
    }
    return {
        "mission_branch": True,
        "three_monsters": {
            "minecraft:zombie",
            "minecraft:skeleton",
            "minecraft:spider",
        }.issubset(defeated_entities),
        "combat_navigation_budget": (
            len(combats) >= 3
            and all(
                objective.budget.max_actions >= 2 and objective.budget.max_strategy_attempts >= 2
                for objective in combats
            )
        ),
        "starter_shelter_exact": any(
            any(
                isinstance(predicate, StructureMatchesBlueprint)
                and predicate.blueprint_id == "starter-shelter-v1"
                for predicate in build.success_predicates
            )
            for build in builds
        ),
        "shelter_budget_admissible": _starter_shelter_budget_admissible(mission),
        "bounded_autonomy": (
            mission.autonomy.mode == "bounded"
            and {"discovery", "skill"}.issubset(mission.autonomy.allowed_domains)
        ),
        "skill_learning_authorized": mission.execution.allow_skill_learning,
        "novel_item_required": any(
            isinstance(predicate, NovelFactsAcquiredAtLeast) and predicate.count >= 1
            for predicate in completion
        ),
        "trusted_skill_required": any(
            isinstance(predicate, TrustedSkillsCreatedAtLeast) and predicate.count >= 1
            for predicate in completion
        ),
        "two_vanilla_advancements_required": any(
            isinstance(predicate, VanillaAdvancementsAddedAtLeast) and predicate.count >= 2
            for predicate in completion
        ),
        "exactly_one_mc_operate_execute": True,
        "hidden_target_not_revealed": "copper" not in serialized_mission,
        "production_budget_admissible": all(
            getattr(mission.budget, field) <= limit for field, limit in production_limits.items()
        ),
    }


def _validate_response(response: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    calls = [
        call for call in response.get("tool_calls") or [] if call.get("name") == "mc_operate_bot"
    ]
    if len(calls) != 1:
        return (
            {"valid": False, "semantic_assertions": {}},
            "expected one mc_operate_bot execute call",
        )
    try:
        operate = MinecraftOperateToolInput.model_validate(
            _normalize_model_execute_args(calls[0].get("args", {}))
        )
        if operate.operation != "execute" or operate.execute is None:
            raise ValueError("expected execute operation")
        validated = operate.execute
    except ValidationError as exc:
        return {"valid": False, "semantic_assertions": {}}, str(exc)
    assertions = _semantic_assertions(validated)
    valid = all(assertions.values())
    return {
        "valid": valid,
        "schema_valid": True,
        "semantic_assertions": assertions,
        "validated_request_hash": validated.request.mission.canonical_hash
        if validated.request.kind == "mission"
        else None,
    }, None if valid else "mission was schema-valid but missed required semantics"


async def _collect_independent_calls(
    *,
    invoke: Callable[[str, list[Any]], Awaitable[dict[str, Any]]],
    validate: Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]] = _validate_response,
    independent_calls: int = 3,
) -> list[dict[str, Any]]:
    if independent_calls < 1:
        raise ValueError("independent_calls must be positive")
    calls: list[dict[str, Any]] = []
    for independent_call in range(1, independent_calls + 1):
        attempts: list[dict[str, Any]] = []
        history: list[Any] = []
        validation: dict[str, Any] = {"valid": False}
        error: str | None = None
        for attempt in range(1, 3):
            user_text = (
                USER_TEXT
                if attempt == 1
                else (
                    "修复上一条 mc_operate_bot execute 调用。请重新输出完整 mission，"
                    "严格满足工具 schema 和用户要求；"
                    f"校验错误：{error}"
                )
            )
            preflight_tool_calls: list[dict[str, Any]] = []
            for _ in range(2):
                response = await invoke(user_text, history)
                if not _is_connection_status_call(response):
                    break
                preflight_tool_calls.extend(response.get("tool_calls") or [])
                _extend_tool_history(
                    history,
                    user_text=user_text,
                    response=response,
                    tool_result=lambda _call: {
                        "state": "ready",
                        "server": {"state": "available"},
                        "bot": {"state": "ready"},
                        "viewer": {"state": "attached", "confirmed": True},
                    },
                )
                user_text = (
                    "连接状态已确认 ready。现在直接调用 mc_operate_bot execute，"
                    "提交满足原始用户要求的完整 typed mission。"
                )
            validation, error = validate(response)
            attempts.append(
                {
                    "attempt": attempt,
                    "user_text": user_text,
                    "visible_response": response.get("content", ""),
                    "preflight_tool_calls": preflight_tool_calls,
                    "tool_calls": response.get("tool_calls") or [],
                    "finish_reason": response.get("finish_reason"),
                    "validation": validation,
                    "error": error,
                }
            )
            if validation.get("valid"):
                break
            _extend_tool_history(
                history,
                user_text=user_text,
                response=response,
                tool_result=lambda _call: {
                    "ok": False,
                    "error": error,
                    "repair_remaining": attempt < 2,
                    "gameplay_submitted": False,
                },
            )
        calls.append(
            {
                "independent_call": independent_call,
                "attempts": attempts,
                "final_validation": validation,
                "error": error,
            }
        )
    return calls


def _is_connection_status_call(response: dict[str, Any]) -> bool:
    calls = response.get("tool_calls") or []
    return (
        len(calls) == 1
        and calls[0].get("name") == "mc_connection"
        and calls[0].get("args", {}).get("operation") == "status"
    )


def _extend_tool_history(
    history: list[Any],
    *,
    user_text: str,
    response: dict[str, Any],
    tool_result: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    history_calls = [
        {
            "name": str(call.get("name", "")),
            "args": call.get("args") if isinstance(call.get("args"), dict) else {},
            "id": str(call.get("id", "")),
            "type": "tool_call",
        }
        for call in response.get("tool_calls") or []
    ]
    history.extend(
        [
            HumanMessage(content=user_text),
            AIMessage(
                content=str(response.get("content", "")),
                tool_calls=history_calls,
            ),
            *(
                ToolMessage(
                    content=json.dumps(tool_result(call), ensure_ascii=False),
                    tool_call_id=call["id"],
                )
                for call in history_calls
            ),
        ]
    )


async def run(output_root: Path, *, independent_calls: int = 3) -> Path:
    load_dotenv(Path(".env"), override=False)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is unavailable")
    tools = get_minecraft_tools()
    state = create_initial_state(
        "real-model-minecraft-contract",
        user_text=USER_TEXT,
        system_prompt="You are Anima. Acknowledge the request briefly and use tools precisely.",
    )
    config = {"configurable": {"tools_map": {item.name: item for item in tools}}}
    compiled = await compile_prompt(state, config)
    llm = OpenAILLM.from_config(
        DeepSeekLLMConfig(
            api_key=api_key,
            model="deepseek-v4-flash",
            thinking="disabled",
            temperature=0.2,
            top_p=0.9,
            max_tokens=16_000,
        )
    )

    started_at_ms = int(time.time() * 1_000)

    async def invoke(user_text: str, history: list[Any]) -> dict[str, Any]:
        return await llm.chat_with_tools(
            user_text,
            tools=tools,
            langchain_history=history,
            system_prompt=compiled.system_prompt,
        )

    calls = await _collect_independent_calls(
        invoke=invoke,
        independent_calls=independent_calls,
    )
    success_count = sum(bool(call["final_validation"].get("valid")) for call in calls)

    finished_at_ms = int(time.time() * 1_000)
    run_id = f"real-model-contract-{started_at_ms}"
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "dialogue-contract.json"
    payload = {
        "schema_version": "1",
        "run_id": run_id,
        "started_at_ms": started_at_ms,
        "finished_at_ms": finished_at_ms,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "tool_names": [item.name for item in tools],
        "exact_user_text": USER_TEXT,
        "required_independent_calls": independent_calls,
        "successful_independent_calls": success_count,
        "calls": calls,
        "final_validation": {
            "valid": success_count == independent_calls,
            "success_count": success_count,
            "required_count": independent_calls,
        },
        "gameplay_executed": False,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if success_count != independent_calls:
        raise RuntimeError(f"real model contract failed; evidence: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/real-model-contract"),
    )
    parser.add_argument("--independent-calls", type=int, default=3)
    args = parser.parse_args()
    output = asyncio.run(run(args.output_root, independent_calls=args.independent_calls))
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
