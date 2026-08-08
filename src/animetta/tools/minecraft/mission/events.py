"""Bounded at-least-once projection events for Minecraft mission domains."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import WalkthroughManifest
from .projection import MissionProjection


class MinecraftProjectionEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    event: str = Field(pattern=r"^minecraft\.[a-z_]+\.projection$")
    event_id: str = Field(min_length=1, max_length=512)
    projection_kind: Literal[
        "mission",
        "objective",
        "proposal",
        "discovery",
        "skill_validation",
        "advancement",
        "stage",
    ]
    projection_version: int = Field(ge=0)
    occurred_at_ms: int = Field(ge=0)
    mission_id: str | None = Field(default=None, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    payload: dict[str, Any]


class ProjectionEventPublisher:
    """Best-effort publisher; durable status remains the rehydration authority."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        maximum_delivered_ids: int = 10_000,
    ) -> None:
        self._emit = emit
        self._maximum_delivered_ids = maximum_delivered_ids
        self._delivered: dict[str, None] = {}

    async def publish(self, event: MinecraftProjectionEvent) -> bool:
        if event.event_id in self._delivered:
            return False
        await self._emit(event.model_dump(mode="json"))
        self._delivered[event.event_id] = None
        while len(self._delivered) > self._maximum_delivered_ids:
            self._delivered.pop(next(iter(self._delivered)))
        return True

    async def publish_domain(
        self,
        *,
        kind: Literal[
            "mission",
            "objective",
            "proposal",
            "discovery",
            "skill_validation",
            "advancement",
            "stage",
        ],
        entity_id: str,
        projection_version: int,
        occurred_at_ms: int,
        payload: dict[str, Any],
        mission_id: str | None = None,
    ) -> bool:
        return await self.publish(
            MinecraftProjectionEvent(
                event=f"minecraft.{kind}.projection",
                event_id=f"{mission_id or 'global'}:{entity_id}:{projection_version}",
                projection_kind=kind,
                projection_version=projection_version,
                occurred_at_ms=occurred_at_ms,
                mission_id=mission_id,
                entity_id=entity_id,
                payload=payload,
            )
        )

    async def publish_mission(self, projection: MissionProjection) -> int:
        published = int(
            await self.publish_domain(
                kind="mission",
                entity_id=projection.mission_id,
                projection_version=projection.projection_version,
                occurred_at_ms=projection.updated_at_ms,
                mission_id=projection.mission_id,
                payload=projection.model_dump(mode="json"),
            )
        )
        for objective in projection.objectives:
            published += int(
                await self.publish_domain(
                    kind="objective",
                    entity_id=objective.objective_id,
                    projection_version=projection.projection_version,
                    occurred_at_ms=projection.updated_at_ms,
                    mission_id=projection.mission_id,
                    payload=objective.model_dump(mode="json"),
                )
            )
        for proposal in projection.proposals:
            published += int(
                await self.publish_domain(
                    kind="proposal",
                    entity_id=proposal.proposal_id,
                    projection_version=projection.projection_version,
                    occurred_at_ms=projection.updated_at_ms,
                    mission_id=projection.mission_id,
                    payload=proposal.model_dump(mode="json"),
                )
            )
        return published

    async def publish_walkthrough(
        self,
        walkthrough: WalkthroughManifest,
        *,
        projection_version: int,
        occurred_at_ms: int,
    ) -> int:
        """Publish the StageProjector result without inventing mutable UI state."""

        published = 0
        for stage in walkthrough.stages:
            published += int(
                await self.publish_domain(
                    kind="stage",
                    entity_id=f"{walkthrough.run_id}:{stage.stage_id}",
                    projection_version=projection_version,
                    occurred_at_ms=occurred_at_ms,
                    mission_id=walkthrough.mission_id,
                    payload=stage.model_dump(mode="json"),
                )
            )
        return published
