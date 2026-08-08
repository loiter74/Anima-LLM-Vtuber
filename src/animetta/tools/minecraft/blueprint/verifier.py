"""Independent structure verification and conservative partial-build resume."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.v2 import RegionInspection, canonical_json_hash
from animetta.tools.minecraft.voyager.budget import BudgetUsage

from .models import (
    BlueprintResumePlan,
    BlueprintVerificationResult,
    CompiledBlueprint,
    resource_cost,
)


def _position(key: str) -> tuple[int, int, int]:
    values = tuple(int(value) for value in key.split(","))
    if len(values) != 3:
        raise ValueError(f"invalid block position: {key!r}")
    return values[0], values[1], values[2]


class BlueprintVerifier:
    def verify(
        self,
        compiled: CompiledBlueprint,
        inspection: RegionInspection,
    ) -> BlueprintVerificationResult:
        expected_bounds = compiled.bounds.model_dump(mode="json")
        actual_bounds = inspection.bounds.model_dump(mode="json")
        bounds_match = expected_bounds == actual_bounds
        matched: list[tuple[int, int, int]] = []
        missing: list[tuple[int, int, int]] = []
        conflicts: list[tuple[int, int, int]] = []
        unknown: list[tuple[int, int, int]] = []
        for key, expected in compiled.expected_blocks.items():
            position = _position(key)
            actual = inspection.blocks.get(key)
            if actual is None:
                unknown.append(position)
            elif actual == expected:
                matched.append(position)
            elif actual == "minecraft:air":
                missing.append(position)
            else:
                conflicts.append(position)
        for position in compiled.required_air:
            key = ",".join(str(value) for value in position)
            actual = inspection.blocks.get(key)
            if actual is None:
                unknown.append(position)
            elif actual == "minecraft:air":
                matched.append(position)
            else:
                conflicts.append(position)

        matched_set = set(matched)
        feature_results = {
            feature.feature_id: all(position in matched_set for position in feature.positions)
            for feature in compiled.features
        }
        features_satisfied = all(
            feature_results.get(feature_id, False) for feature_id in compiled.required_feature_ids
        )
        satisfied = bool(
            bounds_match and not missing and not conflicts and not unknown and features_satisfied
        )
        evidence_payload = {
            "blueprint_hash": compiled.blueprint_hash,
            "inspection_hash": inspection.content_hash,
            "bounds_match": bounds_match,
            "matched": sorted(matched),
            "missing": sorted(missing),
            "conflicts": sorted(conflicts),
            "unknown": sorted(unknown),
            "features": dict(sorted(feature_results.items())),
        }
        return BlueprintVerificationResult(
            satisfied=satisfied,
            blueprint_hash=compiled.blueprint_hash,
            inspection_hash=inspection.content_hash,
            matched_positions=tuple(sorted(set(matched))),
            missing_positions=tuple(sorted(set(missing))),
            conflicting_positions=tuple(sorted(set(conflicts))),
            unknown_positions=tuple(sorted(set(unknown))),
            feature_results=feature_results,
            evidence_hash=canonical_json_hash(evidence_payload),
        )

    def resume(
        self,
        compiled: CompiledBlueprint,
        inspection: RegionInspection,
    ) -> BlueprintResumePlan:
        verification = self.verify(compiled, inspection)
        missing = set(verification.missing_positions)
        conflicts = set(verification.conflicting_positions)
        unknown = set(verification.unknown_positions)
        steps = tuple(
            step
            for step in compiled.steps
            if set(step.effect_positions)
            and set(step.effect_positions) <= missing
            and not set(step.effect_positions) & (conflicts | unknown)
        )
        covered = {position for step in steps for position in step.effect_positions}
        return BlueprintResumePlan(
            blueprint_hash=compiled.blueprint_hash,
            steps=steps,
            blocked_conflicts=verification.conflicting_positions,
            unresolved_missing=tuple(
                sorted(missing - covered | set(verification.unknown_positions))
            ),
            static_cost=BudgetUsage(
                max_actions=len(steps),
                max_blocks_changed=sum(len(step.effect_positions) for step in steps),
                resource_consumption=resource_cost(steps),
            ),
        )
