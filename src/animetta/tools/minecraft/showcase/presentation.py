"""Fresh, sanitized, content-addressed showcase presentation bundles."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.mission.models import EvidenceRef, StageIO, WalkthroughManifest

REQUIRED_STAGE_IDS = (
    "scenario-setup",
    "capture-readiness",
    "dialogue",
    "mission-admission",
    "combat",
    "construction",
    "autonomous-exploration",
    "discovery-acquisition",
    "skill-learning-validation",
    "skill-reuse",
    "progress-projection",
    "final-summary",
)

REQUIRED_JSON_ARTIFACT_KINDS = (
    "scenario_input",
    "scenario_receipt",
    "readiness",
    "dialogue",
    "mission",
    "proposals",
    "commands",
    "receipts",
    "discoveries",
    "skills",
    "advancements",
    "mission_report",
    "final_status",
    "final_narration",
    "stage_io",
)

ArtifactKind = Literal[
    "scenario_input",
    "scenario_receipt",
    "readiness",
    "dialogue",
    "mission",
    "proposals",
    "commands",
    "receipts",
    "discoveries",
    "skills",
    "advancements",
    "mission_report",
    "final_status",
    "final_narration",
    "stage_io",
    "screenshot",
    "video",
]

_ARTIFACT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,127}$"
_RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_SECRET_KEYS = {"authorization", "api_key", "apikey", "password", "secret", "token"}


class PresentationValidationError(ValueError):
    """A stable presentation publication failure."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PresentationArtifact(_FrozenModel):
    schema_version: Literal["1"] = "1"
    artifact_id: str = Field(pattern=_ARTIFACT_ID_PATTERN)
    kind: ArtifactKind
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    relative_path: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    created_at_ms: int = Field(ge=0)
    captured_at_ms: int | None = Field(default=None, ge=0)
    media_started_at_ms: int | None = Field(default=None, ge=0)
    media_finished_at_ms: int | None = Field(default=None, ge=0)
    stage_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _safe_relative_media_contract(self) -> Self:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact path must be bundle-relative")
        is_media = self.kind in {"screenshot", "video"}
        timestamps = (
            self.captured_at_ms,
            self.media_started_at_ms,
            self.media_finished_at_ms,
        )
        if is_media != all(timestamp is not None for timestamp in timestamps):
            raise ValueError("media timestamps must be complete and media-only")
        if is_media and self.media_finished_at_ms < self.media_started_at_ms:  # type: ignore[operator]
            raise ValueError("media finish precedes media start")
        return self


class PresentationManifest(_FrozenModel):
    schema_version: Literal["2"] = "2"
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
    created_at_ms: int = Field(ge=0)
    projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_valid: bool
    acceptance_passed: bool
    stages: tuple[StageIO, ...]
    artifacts: tuple[PresentationArtifact, ...]
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def hash_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"manifest_hash"})


def _sha256_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _assert_safe_payload(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.casefold()
            if (
                lowered in _SECRET_KEYS
                or lowered.endswith("_token")
                or lowered.endswith("_secret")
                or lowered.endswith("_password")
            ):
                raise PresentationValidationError(f"UNSAFE_ARTIFACT:{path}.{key_text}")
            _assert_safe_payload(child, path=f"{path}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_safe_payload(child, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if path.endswith(".json_pointer") and value.startswith("/"):
        return
    if (
        re.search(r"(?i)\bBearer\s+\S+", value)
        or re.search(r"(?i)\bsk-[A-Za-z0-9_-]{6,}", value)
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith("/")
    ):
        raise PresentationValidationError(f"UNSAFE_ARTIFACT:{path}")


class PresentationWriter:
    """Write one immutable run directory and validate it before publication."""

    def __init__(
        self,
        *,
        output_root: Path,
        run_id: str,
        mission_id: str,
        started_at_ms: int,
    ) -> None:
        if re.fullmatch(_RUN_ID_PATTERN, run_id) is None:
            raise PresentationValidationError("INVALID_RUN_ID")
        self.run_id = run_id
        self.mission_id = mission_id
        self.started_at_ms = started_at_ms
        self.run_root = output_root.resolve() / run_id
        self.run_root.mkdir(parents=True, exist_ok=False)
        self._artifacts: list[PresentationArtifact] = []

    def evidence_ref(self, artifact_id: str, *, json_pointer: str = "/") -> EvidenceRef:
        """Return a content-addressed pointer to one already-written artifact."""

        matches = [artifact for artifact in self._artifacts if artifact.artifact_id == artifact_id]
        if len(matches) != 1:
            raise PresentationValidationError(f"ARTIFACT_REF_UNAVAILABLE:{artifact_id}")
        artifact = matches[0]
        return EvidenceRef(
            artifact_id=artifact.artifact_id,
            artifact_kind=artifact.kind,
            json_pointer=json_pointer,
            content_hash=artifact.sha256,
        )

    def _path(self, artifact_id: str, suffix: str) -> tuple[Path, str]:
        if re.fullmatch(_ARTIFACT_ID_PATTERN, artifact_id) is None:
            raise PresentationValidationError("INVALID_ARTIFACT_ID")
        if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) is None:
            raise PresentationValidationError("INVALID_ARTIFACT_SUFFIX")
        relative = f"artifacts/{artifact_id}{suffix}"
        path = self.run_root / PurePosixPath(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise PresentationValidationError("DUPLICATE_ARTIFACT")
        return path, relative

    def write_json_artifact(
        self,
        *,
        artifact_id: str,
        kind: ArtifactKind,
        payload: object,
        created_at_ms: int,
    ) -> PresentationArtifact:
        if kind in {"screenshot", "video"}:
            raise PresentationValidationError("MEDIA_REQUIRES_MEDIA_WRITER")
        _assert_safe_payload(payload)
        content = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        path, relative = self._path(artifact_id, ".json")
        path.write_bytes(content)
        artifact = PresentationArtifact(
            artifact_id=artifact_id,
            kind=kind,
            run_id=self.run_id,
            mission_id=self.mission_id,
            relative_path=relative,
            sha256=_sha256_bytes(content),
            size_bytes=len(content),
            created_at_ms=created_at_ms,
        )
        self._artifacts.append(artifact)
        return artifact

    def write_media_artifact(
        self,
        *,
        artifact_id: str,
        kind: Literal["screenshot", "video"],
        content: bytes,
        suffix: str,
        captured_at_ms: int,
        media_started_at_ms: int,
        media_finished_at_ms: int,
        stage_ids: tuple[str, ...],
    ) -> PresentationArtifact:
        if not content:
            raise PresentationValidationError("EMPTY_MEDIA")
        path, relative = self._path(artifact_id, suffix)
        path.write_bytes(content)
        artifact = PresentationArtifact(
            artifact_id=artifact_id,
            kind=kind,
            run_id=self.run_id,
            mission_id=self.mission_id,
            relative_path=relative,
            sha256=_sha256_bytes(content),
            size_bytes=len(content),
            created_at_ms=captured_at_ms,
            captured_at_ms=captured_at_ms,
            media_started_at_ms=media_started_at_ms,
            media_finished_at_ms=media_finished_at_ms,
            stage_ids=stage_ids,
        )
        self._artifacts.append(artifact)
        return artifact

    def _validate(
        self, walkthrough: WalkthroughManifest, finished_at_ms: int
    ) -> tuple[PresentationArtifact, ...]:
        stages = walkthrough.stages
        stage_ids = tuple(stage.stage_id for stage in stages)
        missing = set(REQUIRED_STAGE_IDS) - set(stage_ids)
        if missing:
            raise PresentationValidationError(f"MISSING_REQUIRED_STAGE:{','.join(sorted(missing))}")
        if stage_ids != REQUIRED_STAGE_IDS:
            raise PresentationValidationError("STAGE_ORDER_INVALID")
        for stage in stages:
            if not stage.input_refs or not stage.output_refs or not stage.evidence_refs:
                raise PresentationValidationError(f"STAGE_IO_INCOMPLETE:{stage.stage_id}")
            if (
                stage.started_at_ms < self.started_at_ms
                or stage.finished_at_ms > finished_at_ms
                or not stage.media
            ):
                raise PresentationValidationError(f"STAGE_TIME_INVALID:{stage.stage_id}")

        artifacts = tuple(self._artifacts)
        artifact_ids = {artifact.artifact_id for artifact in artifacts}
        if len(artifact_ids) != len(artifacts):
            raise PresentationValidationError("DUPLICATE_ARTIFACT_ID")
        kinds = {artifact.kind for artifact in artifacts}
        missing_kinds = set(REQUIRED_JSON_ARTIFACT_KINDS) - kinds
        if missing_kinds:
            raise PresentationValidationError(
                f"MISSING_REQUIRED_ARTIFACT:{','.join(sorted(missing_kinds))}"
            )
        if not {"screenshot", "video"}.issubset(kinds):
            raise PresentationValidationError("MISSING_REQUIRED_MEDIA")

        artifacts_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        for stage in stages:
            refs = (*stage.input_refs, *stage.output_refs, *stage.evidence_refs)
            for ref in refs:
                artifact = artifacts_by_id.get(ref.artifact_id)
                if artifact is None or artifact.sha256 != ref.content_hash:
                    raise PresentationValidationError(f"STAGE_REF_MISSING:{stage.stage_id}")
            for media in stage.media:
                artifact = artifacts_by_id.get(media.evidence_ref.artifact_id)
                if (
                    artifact is None
                    or artifact.sha256 != media.evidence_ref.content_hash
                    or artifact.kind not in {"screenshot", "video"}
                    or artifact.captured_at_ms != media.captured_at_ms
                    or stage.stage_id not in artifact.stage_ids
                ):
                    raise PresentationValidationError(f"STAGE_MEDIA_REF_INVALID:{stage.stage_id}")

        covered_screenshot_stages: set[str] = set()
        videos: list[PresentationArtifact] = []
        for artifact in artifacts:
            path = self.run_root / PurePosixPath(artifact.relative_path)
            if not path.is_file() or _sha256_bytes(path.read_bytes()) != artifact.sha256:
                raise PresentationValidationError(f"ARTIFACT_HASH_MISMATCH:{artifact.artifact_id}")
            if (
                artifact.created_at_ms < self.started_at_ms
                or artifact.created_at_ms > finished_at_ms
            ):
                raise PresentationValidationError(f"STALE_ARTIFACT:{artifact.artifact_id}")
            if artifact.kind not in {"screenshot", "video"}:
                continue
            assert artifact.captured_at_ms is not None
            if not self.started_at_ms <= artifact.captured_at_ms <= finished_at_ms:
                raise PresentationValidationError(f"STALE_MEDIA:{artifact.artifact_id}")
            if artifact.kind == "screenshot":
                covered_screenshot_stages.update(artifact.stage_ids)
            else:
                videos.append(artifact)
        if not set(REQUIRED_STAGE_IDS).issubset(covered_screenshot_stages):
            raise PresentationValidationError("SCREENSHOT_STAGE_COVERAGE")
        first_stage = stages[0].started_at_ms
        last_stage = stages[-1].finished_at_ms
        assert first_stage is not None and last_stage is not None
        if not any(
            video.media_started_at_ms <= first_stage  # type: ignore[operator]
            and video.media_finished_at_ms >= last_stage  # type: ignore[operator]
            and set(REQUIRED_STAGE_IDS).issubset(video.stage_ids)
            for video in videos
        ):
            raise PresentationValidationError("VIDEO_COVERAGE")
        return artifacts

    def finalize(
        self, *, walkthrough: WalkthroughManifest, finished_at_ms: int
    ) -> PresentationManifest:
        artifacts = self._validate(walkthrough, finished_at_ms)
        base: dict[str, object] = {
            "schema_version": "2",
            "run_id": self.run_id,
            "mission_id": self.mission_id,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": finished_at_ms,
            "created_at_ms": finished_at_ms,
            "projection_hash": walkthrough.projection_hash,
            "bundle_valid": walkthrough.bundle_valid,
            "acceptance_passed": walkthrough.acceptance_passed,
            "stages": [stage.model_dump(mode="json") for stage in walkthrough.stages],
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
        manifest = PresentationManifest(
            schema_version="2",
            run_id=self.run_id,
            mission_id=self.mission_id,
            started_at_ms=self.started_at_ms,
            finished_at_ms=finished_at_ms,
            created_at_ms=finished_at_ms,
            projection_hash=walkthrough.projection_hash,
            bundle_valid=walkthrough.bundle_valid,
            acceptance_passed=walkthrough.acceptance_passed,
            stages=walkthrough.stages,
            artifacts=artifacts,
            manifest_hash=canonical_json_hash(base),
        )
        content = (
            json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        (self.run_root / "manifest.json").write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )
        return manifest
