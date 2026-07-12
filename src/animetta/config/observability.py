"""Configuration for the local-first observation ledger and optional mirrors."""

from typing import Literal

from pydantic import Field

from .core.base import BaseConfig


class ObservationMirrorConfig(BaseConfig):
    enabled: bool = True


class OtlpMirrorConfig(BaseConfig):
    enabled: bool = False
    endpoint: str | None = None
    max_export_batch_size: int = Field(default=512, ge=1)
    schedule_delay_millis: int = Field(default=5000, ge=1)


class ObservationPrivacyConfig(BaseConfig):
    development: Literal["full", "redacted"] = "full"
    golden: Literal["full", "redacted"] = "redacted"
    production: Literal["full", "redacted"] = "redacted"
    digest_salt: str = "animetta-local-observation"


class ObservabilityConfig(BaseConfig):
    enabled: bool = True
    database_path: str = "data/observations.db"
    queue_capacity: int = Field(default=4096, ge=1)
    busy_timeout_ms: int = Field(default=5000, ge=1)
    drain_timeout_seconds: float = Field(default=5.0, gt=0)
    privacy: ObservationPrivacyConfig = Field(default_factory=ObservationPrivacyConfig)
    prometheus: ObservationMirrorConfig = Field(default_factory=ObservationMirrorConfig)
    otlp: OtlpMirrorConfig = Field(default_factory=OtlpMirrorConfig)
