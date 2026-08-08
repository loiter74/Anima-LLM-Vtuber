from __future__ import annotations

from animetta.tools.minecraft.mission.events import (
    MinecraftProjectionEvent,
    ProjectionEventPublisher,
)
from animetta.tools.minecraft.mission.models import StageIO, WalkthroughManifest


async def test_projection_events_cover_each_mission_showcase_domain_and_deduplicate() -> None:
    delivered: list[dict[str, object]] = []

    async def emit(payload: dict[str, object]) -> None:
        delivered.append(payload)

    publisher = ProjectionEventPublisher(emit=emit)
    kinds = (
        "mission",
        "objective",
        "proposal",
        "discovery",
        "skill_validation",
        "advancement",
        "stage",
    )
    for index, kind in enumerate(kinds):
        event = MinecraftProjectionEvent(
            event=f"minecraft.{kind}.projection",
            event_id=f"mission-1:{kind}:3",
            projection_kind=kind,
            projection_version=3,
            occurred_at_ms=1_000 + index,
            mission_id="mission-1",
            entity_id=f"{kind}-1",
            payload={"status": "committed"},
        )
        assert await publisher.publish(event) is True
        assert await publisher.publish(event) is False

    assert [item["projection_kind"] for item in delivered] == list(kinds)
    assert len({item["event_id"] for item in delivered}) == len(kinds)


async def test_walkthrough_publisher_emits_stageio_v2_without_a_second_stage_model() -> None:
    delivered: list[dict[str, object]] = []

    async def emit(payload: dict[str, object]) -> None:
        delivered.append(payload)

    stages = tuple(
        StageIO(
            run_id="run-1",
            mission_id="mission-1",
            stage_id=stage_id,
            ordinal=ordinal,
            gameplay_evidence_eligible=ordinal != 1,
            lifecycle="pending",
        )
        for ordinal, stage_id in enumerate(("scenario-setup", "capture-readiness"), start=1)
    )
    walkthrough = WalkthroughManifest(
        run_id="run-1",
        mission_id="mission-1",
        projection_hash="a" * 64,
        stages=stages,
        bundle_valid=False,
        acceptance_passed=False,
    )
    publisher = ProjectionEventPublisher(emit=emit)

    published = await publisher.publish_walkthrough(
        walkthrough,
        projection_version=7,
        occurred_at_ms=1_234,
    )

    assert published == 2
    assert [item["entity_id"] for item in delivered] == [
        "run-1:scenario-setup",
        "run-1:capture-readiness",
    ]
    assert all(item["projection_kind"] == "stage" for item in delivered)
    assert all(item["payload"]["schema_version"] == "2" for item in delivered)  # type: ignore[index]
