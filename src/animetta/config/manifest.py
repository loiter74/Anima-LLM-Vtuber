"""Canonical runtime manifest loading and profile resolution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .core.base import ProviderConfig
from .core.registry import ProviderRegistry
from .humor import HumorConfig
from .observability import ObservabilityConfig

ProfileName = Literal["test", "smoke", "production"]
ServiceCategory = Literal["llm", "asr", "tts", "vad"]
PROFILE_NAMES: tuple[ProfileName, ...] = ("test", "smoke", "production")
SERVICE_CATEGORIES: tuple[ServiceCategory, ...] = ("llm", "asr", "tts", "vad")
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "config" / "animetta.yaml"
_MERGE_KEY = re.compile(r"(?m)^\s*<<\s*:")
_ENV_EXPRESSION = re.compile(r"\$\{([^}]+)\}")
_EXACT_ENV_EXPRESSION = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_LEGACY_SELECTORS = (
    "ANIMETTA_CONFIG",
    "ANIMETTA_LLM",
    "ANIMETTA_ASR",
    "ANIMETTA_TTS",
    "ANIMETTA_VAD",
    "ANIMETTA_LOCAL_LLM",
    "ANIMETTA_BASE_MODEL_PATH",
    "ANIMETTA_LORA_PATH",
    "VITE_API_URL",
)
_ENV_FIELD_KINDS = {
    "api_key": "secret",
    "token": "secret",
    "auth_token": "secret",
    "base_url": "endpoint",
    "host": "endpoint",
    "port": "endpoint",
}


class RuntimeConfigError(ValueError):
    """Base error for canonical runtime configuration failures."""


class ManifestValidationError(RuntimeConfigError):
    """Raised when the manifest schema or a provider reference is invalid."""


class ProfileSelectionError(RuntimeConfigError):
    """Raised when the runtime profile is missing or unknown."""


class ProviderPolicyError(RuntimeConfigError):
    """Raised when a selected provider violates profile policy."""


class EnvironmentResolutionError(RuntimeConfigError):
    """Raised when a selected endpoint or secret cannot be resolved."""


class LegacySelectorError(RuntimeConfigError):
    """Raised when a removed configuration selector is still present."""


class StrictFrozenModel(BaseModel):
    """Shared strict immutable model settings for manifest data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationSystem(StrictFrozenModel):
    host: str
    port: int | str


class ApplicationManifest(StrictFrozenModel):
    persona: str
    system: ApplicationSystem
    observability_snapshot_json: str = Field(
        default_factory=lambda: _canonical_model_json(ObservabilityConfig()),
        alias="observability",
        exclude=True,
        repr=False,
    )
    humor_snapshot_json: str = Field(
        default_factory=lambda: _canonical_model_json(HumorConfig()),
        alias="humor",
        exclude=True,
        repr=False,
    )

    @field_validator("observability_snapshot_json", mode="before")
    @classmethod
    def validate_observability_snapshot(cls, value: Any) -> str:
        return _validated_snapshot_json(value, ObservabilityConfig)

    @field_validator("humor_snapshot_json", mode="before")
    @classmethod
    def validate_humor_snapshot(cls, value: Any) -> str:
        return _validated_snapshot_json(value, HumorConfig)

    @property
    def observability(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], _freeze_json(json.loads(self.observability_snapshot_json)))

    @property
    def humor(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], _freeze_json(json.loads(self.humor_snapshot_json)))

    def manifest_dict(self) -> dict[str, Any]:
        """Return the canonical public structure used for hashing and comparison."""
        return {
            "persona": self.persona,
            "system": self.system.model_dump(),
            "observability": json.loads(self.observability_snapshot_json),
            "humor": json.loads(self.humor_snapshot_json),
        }


class EffectiveSystemConfig(StrictFrozenModel):
    """Runtime system view projected from application and selected profile."""

    host: str
    port: int
    debug: bool
    log_level: str = "INFO"
    runtime_profile: Literal["test", "smoke", "production"]
    long_term_memory_mode: Literal["off", "read_only", "read_write"]
    enable_tools: bool
    enable_subtitle_translation: bool
    enable_active_memes: bool
    tts_timeout_seconds: float

    @property
    def golden_tts_timeout_seconds(self) -> float:
        """Compatibility name consumed by the existing TTS graph node."""
        return self.tts_timeout_seconds


class ProviderCatalog(StrictFrozenModel):
    llm: dict[str, dict[str, Any]]
    asr: dict[str, dict[str, Any]]
    tts: dict[str, dict[str, Any]]
    vad: dict[str, dict[str, Any]]


class ServiceReferences(StrictFrozenModel):
    llm: str
    asr: str
    tts: str
    vad: str

    @property
    def agent(self) -> str:
        """Compatibility identity for call sites that name the LLM slot agent."""
        return self.llm


class ProviderPolicy(StrictFrozenModel):
    allow_mock: bool
    require_remote_identity: bool


class RuntimeSettings(StrictFrozenModel):
    debug: bool = False
    long_term_memory_mode: Literal["off", "read_only", "read_write"] = "off"
    enable_tools: bool = True
    enable_subtitle_translation: bool = True
    enable_active_memes: bool = True
    tts_timeout_seconds: float = Field(default=20.0, ge=1.0, le=60.0)


class ProfileManifest(StrictFrozenModel):
    services: ServiceReferences
    policy: ProviderPolicy
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)


class RuntimeManifest(StrictFrozenModel):
    schema_version: Literal[1]
    application: ApplicationManifest
    providers: ProviderCatalog
    profiles: dict[str, ProfileManifest]

    @model_validator(mode="after")
    def require_exact_profiles(self) -> RuntimeManifest:
        actual = set(self.profiles)
        expected = set(PROFILE_NAMES)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(
                f"profiles must be exactly {PROFILE_NAMES}; missing={missing}, extra={extra}"
            )
        return self


class ConfiguredProvider(StrictFrozenModel):
    category: ServiceCategory
    name: str
    type: str
    model: str | None = None
    voice: str | None = None
    declaration_json: str = Field(exclude=True, repr=False)

    @property
    def declaration(self) -> Mapping[str, Any]:
        return _freeze_json(json.loads(self.declaration_json))

    def declaration_dict(self) -> dict[str, Any]:
        return json.loads(self.declaration_json)

    def typed_config(self) -> ProviderConfig:
        """Return a fresh typed provider config from the immutable declaration."""
        config_class = ProviderRegistry.get_config(self.category, self.type)
        if config_class is None:
            raise ManifestValidationError(
                f"No registered config schema for {self.category} provider type '{self.type}'"
            )
        try:
            return config_class.model_validate(self.declaration_dict())
        except ValidationError as exc:
            raise ManifestValidationError(
                f"Invalid {self.category} provider '{self.name}': {_validation_message(exc)}"
            ) from exc

    def public_identity(self) -> dict[str, str | None]:
        declaration = self.declaration
        return {
            "name": self.name,
            "type": self.type,
            "provider": str(declaration.get("provider") or self.type),
            "model": self.model,
            "voice": self.voice,
        }


class EffectiveConfig(StrictFrozenModel):
    schema_version: Literal[1]
    profile: ProfileName
    application: ApplicationManifest
    services: ServiceReferences
    policy: ProviderPolicy
    runtime: RuntimeSettings
    provider_entries: tuple[ConfiguredProvider, ...] = Field(exclude=True)
    persona_snapshot_json: str = Field(exclude=True, repr=False)
    version: int = 1
    effective_hash: str
    semantic_hash: str
    manifest_path: str = Field(
        default=str(DEFAULT_MANIFEST_PATH),
        exclude=True,
        repr=False,
    )

    @property
    def persona(self) -> str:
        return self.application.persona

    @property
    def system(self) -> EffectiveSystemConfig:
        return EffectiveSystemConfig(
            host=self.application.system.host,
            port=int(self.application.system.port),
            debug=self.runtime.debug,
            runtime_profile=self.profile,
            long_term_memory_mode=self.runtime.long_term_memory_mode,
            enable_tools=self.runtime.enable_tools,
            enable_subtitle_translation=self.runtime.enable_subtitle_translation,
            enable_active_memes=self.runtime.enable_active_memes,
            tts_timeout_seconds=self.runtime.tts_timeout_seconds,
        )

    @property
    def asr(self) -> ProviderConfig:
        return self.typed_provider("asr")

    @property
    def tts(self) -> ProviderConfig:
        return self.typed_provider("tts")

    @property
    def vad(self) -> ProviderConfig:
        return self.typed_provider("vad")

    @property
    def agent(self) -> Any:
        from .agent import AgentConfig

        return AgentConfig(llm_config=self.typed_provider("llm"))

    @property
    def local_llm(self) -> None:
        return None

    @property
    def humor(self) -> Any:
        return HumorConfig.model_validate_json(self.application.humor_snapshot_json)

    @property
    def observability(self) -> Any:
        return ObservabilityConfig.model_validate_json(self.application.observability_snapshot_json)

    @property
    def bilibili(self) -> None:
        return None

    def get_persona(self) -> Any:
        from .persona.base import PersonaConfig

        return PersonaConfig.model_validate_json(self.persona_snapshot_json)

    def get_system_prompt(self, live2d_prompt: str | None = None) -> str:
        return self.get_persona().build_system_prompt(live2d_prompt=live2d_prompt)

    @property
    def providers(self) -> Mapping[str, ConfiguredProvider]:
        return MappingProxyType({provider.category: provider for provider in self.provider_entries})

    def typed_provider(self, category: str) -> ProviderConfig:
        """Resolve one selected declaration through its registered Pydantic schema."""
        if category not in SERVICE_CATEGORIES:
            raise KeyError(category)
        return self.providers[category].typed_config()

    def to_public_dict(
        self,
        *,
        resolved_identities: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        resolved_identities = resolved_identities or {}
        providers: dict[str, Any] = {}
        for category in SERVICE_CATEGORIES:
            provider = self.providers[category]
            configured = provider.public_identity()
            supplied = resolved_identities.get(category)
            if supplied is None:
                resolved = {
                    "type": provider.type,
                    "provider": configured["provider"],
                    "model": provider.model,
                    "voice": provider.voice,
                }
            else:
                resolved = {
                    "type": supplied.get("type", provider.type),
                    "provider": supplied.get("provider"),
                    "model": supplied.get("model"),
                    "voice": supplied.get("voice"),
                }
            ready = all(
                configured[field] == resolved[field]
                for field in ("type", "provider", "model", "voice")
            )
            providers[category] = {
                "configured": configured,
                "resolved": resolved,
                "ready": ready,
                "error": None if ready else "identity_mismatch",
            }
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "version": self.version,
            "persona": self.application.persona,
            "effective_hash": self.effective_hash,
            "semantic_hash": self.semantic_hash,
            "providers": providers,
        }


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def _canonical_model_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _validated_snapshot_json(value: Any, model_type: type[BaseModel]) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("snapshot must contain valid JSON") from exc
    else:
        parsed = value
    try:
        return _canonical_model_json(model_type.model_validate(parsed))
    except ValidationError as exc:
        raise ValueError(_validation_message(exc)) from exc


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _read_manifest(path: Path) -> tuple[RuntimeManifest, dict[str, Any]]:
    if not path.exists():
        raise ManifestValidationError(f"Runtime manifest not found: {path}")

    text = path.read_text(encoding="utf-8")
    if _MERGE_KEY.search(text):
        raise ManifestValidationError("YAML merge keys are forbidden in runtime profiles")

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(f"Invalid runtime manifest YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestValidationError("Runtime manifest root must be a mapping")

    try:
        return RuntimeManifest.model_validate(raw), raw
    except ValidationError as exc:
        raise ManifestValidationError(_validation_message(exc)) from exc


def _path_label(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _validate_environment_locations(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_environment_locations(child, (*path, str(key)))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_environment_locations(child, (*path, str(index)))
        return
    if not isinstance(value, str) or not _ENV_EXPRESSION.search(value):
        return

    leaf = path[-1] if path else ""
    if leaf not in _ENV_FIELD_KINDS:
        raise ManifestValidationError(f"Environment expansion is forbidden at {_path_label(path)}")
    if ":" in value:
        raise ManifestValidationError(
            f"Environment default syntax is forbidden for {leaf} at {_path_label(path)}"
        )
    if not _EXACT_ENV_EXPRESSION.fullmatch(value):
        raise ManifestValidationError(
            f"Environment reference at {_path_label(path)} must occupy the entire field"
        )


def _detect_legacy_selectors() -> None:
    present = [name for name in _LEGACY_SELECTORS if name in os.environ]
    if present:
        names = ", ".join(present)
        raise LegacySelectorError(
            f"Legacy runtime selector(s) detected: {names}. "
            "Use config/animetta.yaml plus ANIMETTA_PROFILE; inject only endpoints and secrets."
        )


def _resolve_environment_value(value: Any, path: tuple[str, ...]) -> Any:
    if not isinstance(value, str) or not _ENV_EXPRESSION.search(value):
        return value
    match = _EXACT_ENV_EXPRESSION.fullmatch(value)
    if match is None:
        raise ManifestValidationError(f"Invalid environment reference at {_path_label(path)}")
    variable = match.group(1)
    resolved = os.getenv(variable)
    if resolved is None or resolved == "":
        raise EnvironmentResolutionError(
            f"Required environment variable {variable} is missing for {_path_label(path)}"
        )
    return resolved


def _resolve_selected_declaration(
    declaration: dict[str, Any],
    path: tuple[str, ...],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in declaration.items():
        child_path = (*path, str(key))
        if isinstance(value, dict):
            resolved[key] = _resolve_selected_declaration(value, child_path)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_environment_value(item, (*child_path, str(index)))
                for index, item in enumerate(value)
            ]
        else:
            resolved[key] = _resolve_environment_value(value, child_path)
    return resolved


def _resolve_application(application: ApplicationManifest) -> ApplicationManifest:
    host = _resolve_environment_value(
        application.system.host,
        ("application", "system", "host"),
    )
    raw_port = _resolve_environment_value(
        application.system.port,
        ("application", "system", "port"),
    )
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError("application.system.port must resolve to an integer") from exc
    if not 1 <= port <= 65535:
        raise ManifestValidationError("application.system.port must be between 1 and 65535")
    return application.model_copy(update={"system": ApplicationSystem(host=str(host), port=port)})


def _select_profile(
    manifest: RuntimeManifest,
    profile: str | None,
) -> tuple[ProfileName, ProfileManifest]:
    selected = profile or os.getenv("ANIMETTA_PROFILE")
    if not selected:
        raise ProfileSelectionError(
            "ANIMETTA_PROFILE is required; choose test, smoke, or production"
        )
    if selected not in manifest.profiles:
        raise ProfileSelectionError(
            f"Unknown profile '{selected}'. Valid profiles: test, smoke, production"
        )
    profile_name = cast(ProfileName, selected)
    return profile_name, manifest.profiles[profile_name]


def _resolve_providers(
    manifest: RuntimeManifest,
    profile_name: ProfileName,
    profile: ProfileManifest,
) -> dict[str, ConfiguredProvider]:
    resolved: dict[str, ConfiguredProvider] = {}
    for category in SERVICE_CATEGORIES:
        name = getattr(profile.services, category)
        declarations = getattr(manifest.providers, category)
        if name not in declarations:
            raise ManifestValidationError(f"{category} provider reference '{name}' is not declared")
        declaration = _resolve_selected_declaration(
            declarations[name],
            ("providers", category, name),
        )
        provider_type = declaration.get("type")
        if not isinstance(provider_type, str) or not provider_type:
            raise ManifestValidationError(
                f"{category} provider '{name}' must declare a non-empty type"
            )
        if not profile.policy.allow_mock and provider_type == "mock":
            raise ProviderPolicyError(
                f"Profile '{profile_name}' forbids {category} provider '{name}' of type mock"
            )
        configured = ConfiguredProvider(
            category=category,
            name=name,
            type=provider_type,
            model=declaration.get("model"),
            voice=declaration.get("voice"),
            declaration_json=json.dumps(
                declaration,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        configured.typed_config()
        resolved[category] = configured
    return resolved


def _secret_marker(raw_value: Any) -> str:
    if isinstance(raw_value, str):
        match = _EXACT_ENV_EXPRESSION.fullmatch(raw_value)
        if match is not None:
            return f"<secret-env:{match.group(1)}>"
    return "<redacted-secret>"


def _hashable_value(
    raw_value: Any,
    resolved_value: Any,
    path: tuple[str, ...],
    *,
    semantic: bool,
) -> Any:
    if isinstance(resolved_value, Mapping):
        raw_mapping = raw_value if isinstance(raw_value, Mapping) else {}
        return {
            str(key): _hashable_value(
                raw_mapping.get(key),
                child,
                (*path, str(key)),
                semantic=semantic,
            )
            for key, child in resolved_value.items()
        }
    if isinstance(resolved_value, (list, tuple)):
        raw_list = raw_value if isinstance(raw_value, (list, tuple)) else []
        return [
            _hashable_value(
                raw_list[index] if index < len(raw_list) else None,
                child,
                (*path, str(index)),
                semantic=semantic,
            )
            for index, child in enumerate(resolved_value)
        ]

    leaf = path[-1] if path else ""
    kind = _ENV_FIELD_KINDS.get(leaf)
    if kind == "secret":
        return _secret_marker(raw_value)
    if kind == "endpoint" and semantic:
        return "<deployment-endpoint>"
    return resolved_value


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _calculate_hashes(
    manifest: RuntimeManifest,
    raw: dict[str, Any],
    profile_name: str,
    selected: ProfileManifest,
    application: ApplicationManifest,
    persona_snapshot: Mapping[str, Any],
    providers: Mapping[str, ConfiguredProvider],
) -> tuple[str, str]:
    raw_application = raw.get("application", {})
    resolved_application = application.manifest_dict()
    raw_catalog = raw.get("providers", {})

    def payload(*, semantic: bool) -> dict[str, Any]:
        provider_payload: dict[str, Any] = {}
        for category in SERVICE_CATEGORIES:
            provider = providers[category]
            raw_declaration = raw_catalog.get(category, {}).get(provider.name, {})
            provider_payload[category] = {
                "name": provider.name,
                "declaration": _hashable_value(
                    raw_declaration,
                    provider.declaration_dict(),
                    ("providers", category, provider.name),
                    semantic=semantic,
                ),
            }
        return {
            "schema_version": manifest.schema_version,
            "profile": profile_name,
            "application": _hashable_value(
                raw_application,
                resolved_application,
                ("application",),
                semantic=semantic,
            ),
            "persona_snapshot": persona_snapshot,
            "services": selected.services.model_dump(),
            "policy": selected.policy.model_dump(),
            "runtime": selected.runtime.model_dump(),
            "providers": provider_payload,
        }

    return _digest(payload(semantic=False)), _digest(payload(semantic=True))


def load_effective_config(
    path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    profile: str | None = None,
    personas_dir: str | Path | None = None,
) -> EffectiveConfig:
    """Load and resolve the one canonical runtime manifest."""
    _detect_legacy_selectors()
    manifest_path = Path(path).resolve()
    manifest, raw = _read_manifest(manifest_path)
    _validate_environment_locations(raw)
    profile_name, selected = _select_profile(manifest, profile)
    providers = _resolve_providers(manifest, profile_name, selected)
    application = _resolve_application(manifest.application)
    from .persona.base import PersonaConfig

    persona_snapshot = PersonaConfig.load(
        application.persona,
        personas_dir=str(personas_dir) if personas_dir is not None else None,
        strict=True,
    )
    persona_snapshot_data = persona_snapshot.model_dump(mode="json")
    effective_hash, semantic_hash = _calculate_hashes(
        manifest,
        raw,
        profile_name,
        selected,
        application,
        persona_snapshot_data,
        providers,
    )
    return EffectiveConfig(
        schema_version=manifest.schema_version,
        profile=profile_name,
        application=application,
        services=selected.services,
        policy=selected.policy,
        runtime=selected.runtime,
        provider_entries=tuple(providers[category] for category in SERVICE_CATEGORIES),
        persona_snapshot_json=json.dumps(
            persona_snapshot_data,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        effective_hash=effective_hash,
        semantic_hash=semantic_hash,
        manifest_path=str(manifest_path),
    )


def load_remote_tts_worker_config(
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> ProviderConfig:
    """Resolve only production TTS fields for the least-privilege GPU worker."""
    _detect_legacy_selectors()
    manifest, raw = _read_manifest(Path(path).resolve())
    _validate_environment_locations(raw)
    selected = manifest.profiles["production"]
    name = selected.services.tts
    declarations = manifest.providers.tts
    if name not in declarations:
        raise ManifestValidationError(f"tts provider reference '{name}' is not declared")
    declaration = _resolve_selected_declaration(
        declarations[name],
        ("providers", "tts", name),
    )
    provider_type = declaration.get("type")
    if provider_type == "mock" or not isinstance(provider_type, str):
        raise ProviderPolicyError("Production TTS worker requires a non-Mock provider")
    configured = ConfiguredProvider(
        category="tts",
        name=name,
        type=provider_type,
        model=declaration.get("model"),
        voice=declaration.get("voice"),
        declaration_json=json.dumps(
            declaration,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    return configured.typed_config()
