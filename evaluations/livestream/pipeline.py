"""Auditable, staging-first livestream dataset cleaning publication."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType

from .cleaning import BalancedCleaner, DecisionCache, SemanticProcessor
from .cleaning_evidence import write_cleaning_evidence
from .dataset import DatasetValidator, DatasetWriter, HeatTier
from .enrichment import derive_high_events, derive_medium_events, enrich_scenarios
from .semantic import PROMPT_VERSION

_REPLYABLE_TYPES = {
    LivestreamEventType.DANMAKU,
    LivestreamEventType.GIFT,
    LivestreamEventType.SUPER_CHAT,
}
_MIN_HIGH_DURATION_MS = 5_400_000


@dataclass(frozen=True, slots=True)
class CleanOptions:
    """Frozen command contract for balanced Chinese dataset processing."""

    profile: str = "balanced"
    target_language: str = "zh-CN"
    synthetic_ratio: float = 0.10
    seed: int = 20260717
    derive_medium: bool = False
    medium_rate: int = 40

    def __post_init__(self) -> None:
        if self.profile != "balanced":
            raise ValueError("only the balanced cleaning profile is supported")
        if self.target_language != "zh-CN":
            raise ValueError("target_language must be zh-CN")
        if self.synthetic_ratio != 0.10:
            raise ValueError("synthetic_ratio must be exactly 0.10")
        if not 11 <= self.medium_rate <= 60:
            raise ValueError("medium_rate must be between 11 and 60")


async def publish_clean_datasets(
    source_dir: Path,
    output_root: Path,
    *,
    processor: SemanticProcessor,
    options: CleanOptions = CleanOptions(),
    cache_path: Path | None = None,
    evidence_root: Path | None = None,
) -> list[Path]:
    """Build, validate, and then rename a clean dataset family into place."""
    source_dir = Path(source_dir)
    output_root = Path(output_root)
    source_result = DatasetValidator().validate(source_dir)
    if not source_result.valid:
        raise ValueError(
            "source dataset validation failed: " + ",".join(source_result.error_codes),
        )
    source_manifest = source_result.manifest
    source_id = str(source_manifest["dataset_id"])
    names = _output_names(source_id, derive_medium=options.derive_medium)
    destinations = [output_root / name for name in names]
    existing = [path for path in destinations if path.exists()]
    if existing:
        raise FileExistsError(f"dataset output already exists: {existing[0]}")
    evidence_destination = (
        Path(evidence_root) / f"{source_id}-cleaning-v2" if evidence_root is not None else None
    )
    if evidence_destination is not None and evidence_destination.exists():
        raise FileExistsError(f"cleaning evidence already exists: {evidence_destination}")
    output_root.mkdir(parents=True, exist_ok=True)

    cache = (
        DecisionCache(cache_path, source_checksum=str(source_manifest["events_sha256"]))
        if cache_path is not None
        else None
    )
    result = await BalancedCleaner(processor=processor, cache=cache).clean(source_result.events)
    original_duration_ms = int(source_manifest["duration_ms"])
    duration_ms = original_duration_ms
    heat_tier = HeatTier(source_manifest["heat_tier"])
    real_events = result.events
    high_derivation: dict[str, object] | None = None
    if heat_tier is HeatTier.HIGH:
        real_events, duration_ms, compression_factor = derive_high_events(
            real_events,
            duration_ms=duration_ms,
            min_duration_ms=_MIN_HIGH_DURATION_MS,
        )
        if compression_factor > 1.0:
            high_derivation = {
                "kind": "high_time_compression",
                "compression_factor": compression_factor,
                "original_duration_ms": original_duration_ms,
            }
    processing = _processing(processor, options)

    with tempfile.TemporaryDirectory(prefix=".clean-staging-", dir=output_root) as temporary:
        staging_root = Path(temporary)
        staged: list[tuple[Path, Path | None]] = []
        real_path = staging_root / names[0]
        real_manifest = _write_dataset(
            real_path,
            dataset_id=names[0],
            heat_tier=heat_tier,
            events=real_events,
            duration_ms=duration_ms,
            parent_manifest=source_manifest,
            processing=processing,
            dropped=len(result.drops),
            translated=result.translated_count,
            variant="clean-real",
            synthetic_ratio=0.0,
            derivation=high_derivation,
        )
        staged.append((real_path, source_dir))

        enriched_path = staging_root / names[1]
        enriched_events = enrich_scenarios(
            real_events,
            synthetic_ratio=options.synthetic_ratio,
            seed=options.seed,
        )
        _write_dataset(
            enriched_path,
            dataset_id=names[1],
            heat_tier=heat_tier,
            events=enriched_events,
            duration_ms=duration_ms,
            parent_manifest=real_manifest,
            processing=processing,
            dropped=len(result.drops),
            translated=result.translated_count,
            variant="clean-enriched",
            synthetic_ratio=options.synthetic_ratio,
            derivation=high_derivation,
        )
        staged.append((enriched_path, real_path))

        if options.derive_medium:
            medium_events = derive_medium_events(
                real_events,
                duration_ms=duration_ms,
                target_rate=options.medium_rate,
                seed=options.seed,
            )
            medium_path = staging_root / names[2]
            medium_manifest = _write_dataset(
                medium_path,
                dataset_id=names[2],
                heat_tier=HeatTier.MEDIUM,
                events=medium_events,
                duration_ms=duration_ms,
                parent_manifest=real_manifest,
                processing=processing,
                dropped=_replyable_count(real_events) - _replyable_count(medium_events),
                translated=result.translated_count,
                variant="clean-real",
                synthetic_ratio=0.0,
                derivation={
                    "kind": "medium",
                    "target_rate": options.medium_rate,
                    "seed": options.seed,
                    **(
                        {"source_compression_factor": high_derivation["compression_factor"]}
                        if high_derivation is not None
                        else {}
                    ),
                },
            )
            staged.append((medium_path, real_path))

            medium_enriched_path = staging_root / names[3]
            medium_enriched = enrich_scenarios(
                medium_events,
                synthetic_ratio=options.synthetic_ratio,
                seed=options.seed,
            )
            _write_dataset(
                medium_enriched_path,
                dataset_id=names[3],
                heat_tier=HeatTier.MEDIUM,
                events=medium_enriched,
                duration_ms=duration_ms,
                parent_manifest=medium_manifest,
                processing=processing,
                dropped=_replyable_count(real_events) - _replyable_count(medium_events),
                translated=result.translated_count,
                variant="clean-enriched",
                synthetic_ratio=options.synthetic_ratio,
                derivation={
                    "kind": "medium",
                    "target_rate": options.medium_rate,
                    "seed": options.seed,
                    **(
                        {"source_compression_factor": high_derivation["compression_factor"]}
                        if high_derivation is not None
                        else {}
                    ),
                },
            )
            staged.append((medium_enriched_path, medium_path))

        validation_results = [
            DatasetValidator().validate(path, parent_dir=parent_dir) for path, parent_dir in staged
        ]
        invalid_details = []
        for (path, _parent), validation in zip(staged, validation_results, strict=True):
            if validation.valid:
                continue
            errors = "|".join(f"{item['code']}({item['message']})" for item in validation.errors)
            invalid_details.append(f"{path.name}:{errors}")
        if invalid_details:
            raise ValueError("staged dataset validation failed: " + "; ".join(invalid_details))

        evidence_staging: Path | None = None
        if evidence_destination is not None:
            evidence_staging = staging_root / "_evidence"
            write_cleaning_evidence(
                evidence_staging,
                source_replyable_count=_replyable_count(source_result.events),
                cleaning_result=result,
                datasets={
                    name: validation
                    for name, validation in zip(names, validation_results, strict=True)
                },
                seed=options.seed,
            )

        published: list[Path] = []
        try:
            for (staged_path, _parent), destination in zip(staged, destinations, strict=True):
                staged_path.replace(destination)
                published.append(destination)
            if evidence_staging is not None and evidence_destination is not None:
                evidence_destination.parent.mkdir(parents=True, exist_ok=True)
                evidence_staging.replace(evidence_destination)
        except OSError:
            for path in published:
                if path.is_dir():
                    shutil.rmtree(path)
            if evidence_destination is not None and evidence_destination.is_dir():
                shutil.rmtree(evidence_destination)
            raise
    return destinations


def _write_dataset(
    path: Path,
    *,
    dataset_id: str,
    heat_tier: HeatTier,
    events: list[LivestreamEvent],
    duration_ms: int,
    parent_manifest: dict[str, object],
    processing: dict[str, object],
    dropped: int,
    translated: int,
    variant: str,
    synthetic_ratio: float,
    derivation: dict[str, object] | None = None,
) -> dict[str, object]:
    writer = DatasetWriter(
        path,
        dataset_id=dataset_id,
        heat_tier=heat_tier,
        schema_version=2,
        parent_dataset={
            "dataset_id": parent_manifest["dataset_id"],
            "events_sha256": parent_manifest["events_sha256"],
        },
        processing=processing,
        cleaning_counts={
            "retained": 0,
            "dropped": dropped,
            "translated": translated,
            "synthetic": 0,
        },
        derivation=derivation,
        variant=variant,
        synthetic_ratio=synthetic_ratio,
    )
    for event in events:
        writer.write(event)
    return writer.finalize(duration_ms=duration_ms)


def _processing(processor: SemanticProcessor, options: CleanOptions) -> dict[str, object]:
    return {
        "profile": options.profile,
        "target_language": options.target_language,
        "cleaner_version": "balanced-v2",
        "prompt_version": PROMPT_VERSION,
        "provider": str(getattr(processor, "provider_name", "injected")),
        "model": str(getattr(processor, "model_name", processor.__class__.__name__)),
        "seed": options.seed,
    }


def _output_names(source_id: str, *, derive_medium: bool) -> list[str]:
    names = [
        f"{source_id}-clean-real-v2",
        f"{source_id}-clean-enriched-v2",
    ]
    if derive_medium:
        names.extend(
            [
                f"{source_id}-medium-clean-real-v2",
                f"{source_id}-medium-clean-enriched-v2",
            ],
        )
    return names


def _replyable_count(events: list[LivestreamEvent]) -> int:
    return sum(event.event_type in _REPLYABLE_TYPES for event in events)
