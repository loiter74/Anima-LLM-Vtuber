"""
ServicePool — globally shared service instances for LLM/TTS/ASR.

These services are stateless (each API call is independent), so a single
instance can be safely shared across all sessions.  VAD and Memory are
NOT pooled because they carry per-session state.

Usage:
    # On server start:
    await ServicePool.init(config)

    # When creating a session context:
    if ServicePool.ready:
        ctx.load_cache(config, **ServicePool.get_context())
        await ctx.init_vad(config.vad)
        await ctx.init_memory()
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from animetta.config.manifest import EffectiveConfig
    from animetta.core.model_loading_manager import ModelLoadingManager
    from animetta.observability.ports import ObservationRecorder


class ServicePool:
    """Globally shared LLM/TTS/ASR engine instances."""

    _llm: Any | None = None
    _tts: Any | None = None
    _asr: Any | None = None
    _ready: bool = False
    _ctx: Any | None = None
    _runtime_config: Any | None = None
    _model_manager: Any | None = None
    _init_state: str = "pending"
    _init_error: str | None = None
    _initializing_task: asyncio.Task[None] | None = None
    _shutdown_task: asyncio.Task[None] | None = None
    _shutdown_requested: bool = False
    _shutdown_errors: tuple[str, ...] = ()
    _resolved_identities: dict[str, dict[str, str | None]] = {}
    _llm_connectivity: dict[str, Any] = {
        "state": "pending",
        "ready": False,
        "reason": None,
    }

    # ── Lifecycle ──────────────────────────────────────────

    @classmethod
    async def init(
        cls,
        config: EffectiveConfig,
        model_manager: ModelLoadingManager | None = None,
        observation_recorder: ObservationRecorder | None = None,
    ) -> None:
        """Initialize once; concurrent callers await the same lifecycle task."""
        if cls._init_state == "closed" and (
            cls._shutdown_task is None or cls._shutdown_task.done()
        ):
            cls._init_state = "pending"
            cls._shutdown_task = None
            cls._shutdown_requested = False
        if cls._shutdown_requested or cls._init_state == "closing":
            raise RuntimeError("ServicePool shutdown is in progress")

        current_task = asyncio.current_task()
        existing_task = cls._initializing_task
        if (
            existing_task is not None
            and existing_task is not current_task
            and not existing_task.done()
        ):
            await asyncio.shield(existing_task)
            return

        if cls._ready:
            logger.debug("[ServicePool] Already initialized")
            return
        if cls._init_state == "ready" and (
            cls._ctx is not None
            or cls._llm is not None
            or cls._tts is not None
            or cls._asr is not None
        ):
            logger.debug("[ServicePool] Already initialized")
            return
        if cls._init_state in {"loading", "failed"}:
            raise RuntimeError(
                "ServicePool initialization is not retryable; "
                "perform explicit shutdown before retry"
            )

        cls._initializing_task = current_task
        try:
            await cls._init_once(
                config,
                model_manager=model_manager,
                observation_recorder=observation_recorder,
            )
        finally:
            if cls._initializing_task is current_task:
                cls._initializing_task = None

    @classmethod
    async def _init_once(
        cls,
        config: EffectiveConfig,
        model_manager: ModelLoadingManager | None = None,
        observation_recorder: ObservationRecorder | None = None,
    ) -> None:
        """Create all shareable engines from *config* and keep them alive.

        Spawns a temporary ServiceContext, loads all services, then
        extracts LLM/TTS/ASR and discards the per-session services
        (VAD, Memory).
        """
        import time as _time

        t0 = _time.perf_counter()
        logger.info("[ServicePool] Initializing shared service instances...")
        cls._runtime_config = config
        cls._model_manager = model_manager
        cls._init_state = "loading"
        cls._init_error = None
        cls._llm_connectivity = {
            "state": "pending",
            "ready": False,
            "reason": None,
        }
        cls._ready = False
        cls._resolved_identities = {}

        from .service_context import ServiceContext

        if observation_recorder is None:
            ctx = ServiceContext(model_manager=model_manager)
        else:
            ctx = ServiceContext(
                model_manager=model_manager,
                observation_recorder=observation_recorder,
            )
        ctx.session_id = "__pool__"
        try:
            await ctx.load_from_config(config, initialize_memory=False)
            cls._llm = ctx.llm_engine
            cls._tts = ctx.tts_engine
            cls._asr = ctx.asr_engine
            cls._ctx = ctx
            vad_engine = ctx.vad_engine

            # Close per-session services — they are NOT shared.
            if ctx.vad_engine is not None:
                await ctx.vad_engine.close()
                ctx.vad_engine = None
            if ctx.memory_system is not None:
                await ctx.memory_system.shutdown()
                ctx.memory_system = None
            if ctx.emotion_analyzer is not None:
                ctx.emotion_analyzer = None
            if ctx.audio_processor is not None:
                ctx.audio_processor = None

            profile = cls._runtime_profile(config)
            strict_runtime = profile in {"smoke", "production", "golden"}
            if strict_runtime:
                # ServiceContext registers preload functions before returning.
                # Await a post-registration pass even though the ASGI bootstrap
                # also launches an intentionally early, possibly empty warmup.
                if model_manager is not None:
                    await model_manager.warmup()

                try:
                    cls._llm_connectivity = dict(await ctx.wait_for_llm_connectivity())
                except Exception:
                    cls._llm_connectivity = {
                        "state": "failed",
                        "ready": False,
                        "reason": "request_failed",
                    }
            else:
                cls._llm_connectivity = dict(
                    getattr(
                        ctx,
                        "llm_connectivity_status",
                        {"state": "pending", "ready": False, "reason": None},
                    )
                )

            if hasattr(config, "providers"):
                from .readiness import resolve_service_identity

                engines = {
                    "llm": cls._llm,
                    "asr": cls._asr,
                    "tts": cls._tts,
                    "vad": vad_engine,
                }
                cls._resolved_identities = {
                    category: identity
                    for category, engine in engines.items()
                    if (
                        identity := resolve_service_identity(
                            category,
                            engine,
                            config.providers[category],
                        )
                    )
                    is not None
                }

            # Engine construction has reached a terminal state.  Golden
            # readiness is computed from the real provider, connectivity, and
            # preload caches; development retains explicit-mock behavior.
            if cls._shutdown_requested:
                raise asyncio.CancelledError
            cls._init_state = "ready"
            cls._ready = cls._compute_engine_readiness()

            elapsed = (_time.perf_counter() - t0) * 1000
            if cls._ready:
                logger.info(f"[ServicePool] Ready ({elapsed:.0f}ms) — shared LLM/TTS/ASR")
            else:
                logger.warning("[ServicePool] Shared engines initialized but readiness is pending")
        except asyncio.CancelledError:
            logger.warning("[ServicePool] Initialization cancelled")
            await cls._abort_initialization(ctx, "initialization_cancelled")
            raise
        except Exception as exc:
            logger.error(
                "[ServicePool] Initialization failed: {}",
                type(exc).__name__,
            )
            await cls._abort_initialization(ctx, "initialization_failed")
            raise

    @classmethod
    def configure_runtime(cls, config: Any, model_manager: Any | None = None) -> None:
        """Register the effective profile before background initialization starts."""
        if cls._init_state not in {"closing"}:
            cls._runtime_config = config
            if model_manager is not None:
                cls._model_manager = model_manager
        if cls._init_state in {"pending", "closed"} and cls._ctx is None:
            cls._model_manager = model_manager
            if cls._init_state == "closed":
                cls._init_state = "pending"
                cls._shutdown_task = None
                cls._shutdown_requested = False

    @classmethod
    def get_context(cls) -> dict[str, Any]:
        """Return a dict of shareable engines for ``ServiceContext.load_cache()``.

        Development callers receive an empty dict while the pool is unavailable.
        Golden callers fail closed so they cannot allocate a second engine set.
        """
        if not cls.is_ready():
            if cls._runtime_profile(cls._runtime_config) in {
                "smoke",
                "production",
                "golden",
            }:
                raise RuntimeError(
                    "Real-profile ServicePool is not ready; refusing per-session engine initialization"
                )
            return {}
        return {
            "llm_engine": cls._llm,
            "tts_engine": cls._tts,
            "asr_engine": cls._asr,
        }

    @classmethod
    def apply_llm_config(cls, llm_config: Any, system_prompt: str | None = None) -> None:
        """Apply lightweight LLM config and prompt updates to the pooled engine."""
        if cls._llm is None:
            return
        from animetta.config.runtime_reload import apply_runtime_llm_config

        apply_runtime_llm_config(cls._llm, llm_config, system_prompt)

    @classmethod
    async def shutdown(cls) -> None:
        """Await one shielded, process-wide best-effort shutdown operation."""
        existing = cls._shutdown_task
        if cls._init_state == "closed" and existing is not None and existing.done():
            await asyncio.shield(existing)
            return

        # Atomic lifecycle gate: no await is allowed before every readiness
        # signal becomes non-ready and late initialization is forbidden.
        cls._shutdown_requested = True
        cls._ready = False
        cls._init_state = "closing"
        cls._llm_connectivity = {
            "state": "pending",
            "ready": False,
            "reason": None,
        }

        if existing is None:
            existing = asyncio.create_task(cls._shutdown_once())
            cls._shutdown_task = existing
        await asyncio.shield(existing)

    @classmethod
    async def _shutdown_once(cls) -> None:
        """Close shared resources once and always clear lifecycle references."""
        initializing_task = cls._initializing_task
        current_task = asyncio.current_task()
        errors: list[str] = []
        try:
            if (
                initializing_task is not None
                and initializing_task is not current_task
                and not initializing_task.done()
            ):
                initializing_task.cancel()
                await asyncio.gather(
                    initializing_task,
                    return_exceptions=True,
                )

            if any(engine is not None for engine in (cls._llm, cls._tts, cls._asr)):
                logger.info("[ServicePool] Shutting down shared instances...")

            context = cls._ctx
            try:
                if context is not None:
                    await context.close()
            except asyncio.CancelledError:
                errors.append("context:CancelledError")
            except Exception as exc:
                errors.append(f"context:{type(exc).__name__}")

            seen: set[int] = set()
            for name, engine in (
                ("llm", cls._llm),
                ("tts", cls._tts),
                ("asr", cls._asr),
            ):
                if engine is None or id(engine) in seen:
                    continue
                seen.add(id(engine))
                try:
                    await engine.close()
                except asyncio.CancelledError:
                    errors.append(f"{name}:CancelledError")
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}")
        finally:
            cls._ready = False
            cls._llm = None
            cls._tts = None
            cls._asr = None
            cls._ctx = None
            cls._runtime_config = None
            cls._model_manager = None
            cls._init_state = "closed"
            cls._init_error = None
            cls._initializing_task = None
            cls._shutdown_requested = False
            cls._shutdown_errors = tuple(errors)
            cls._resolved_identities = {}
            cls._llm_connectivity = {
                "state": "pending",
                "ready": False,
                "reason": None,
            }
            if errors:
                logger.warning(
                    "[ServicePool] Shutdown completed with cleanup errors: {}",
                    ",".join(errors),
                )
            else:
                logger.info("[ServicePool] Shut down")

    @classmethod
    def is_ready(cls) -> bool:
        cls._ready = cls._compute_engine_readiness()
        return cls._ready

    @classmethod
    def get_readiness_snapshot(
        cls,
        *,
        config: Any | None = None,
        model_manager: Any | None = None,
        frontend: Any | None = None,
    ):
        """Return the cached, content-free runtime readiness snapshot."""
        from .readiness import build_runtime_readiness_snapshot

        active_config = config if config is not None else cls._runtime_config
        active_manager = model_manager if model_manager is not None else cls._model_manager
        frontend_status = frontend or {
            "state": "failed",
            "ready": False,
            "reason": "frontend_state_unavailable",
        }
        return build_runtime_readiness_snapshot(
            config=active_config,
            llm_engine=cls._llm,
            tts_engine=cls._tts,
            model_manager=active_manager,
            init_state=cls._init_state,
            init_reason=cls._init_error,
            connectivity=cls._llm_connectivity,
            frontend=frontend_status,
            development_ready=cls._ready,
            pool_config=cls._runtime_config,
            resolved_identities=cls._resolved_identities,
        )

    @classmethod
    def _compute_engine_readiness(cls) -> bool:
        """Evaluate cached engine readiness without frontend policy or I/O."""
        if cls._shutdown_requested or cls._init_state in {"closing", "closed"}:
            return False
        profile = cls._runtime_profile(cls._runtime_config)
        if profile not in {"smoke", "production", "golden"}:
            return cls._ready or (
                cls._init_state == "ready" and cls._llm is not None and cls._tts is not None
            )
        snapshot = cls.get_readiness_snapshot(
            frontend={"state": "ready", "ready": True, "reason": None},
        )
        return bool(snapshot.components.get("pool", {}).get("ready"))

    @staticmethod
    def _runtime_profile(config: Any | None) -> str:
        direct = getattr(config, "profile", None)
        if direct in {"test", "smoke", "production"}:
            return direct
        try:
            profile = config.system.runtime_profile
        except Exception:
            return "development"
        return (
            profile
            if profile in {"development", "test", "smoke", "production", "golden"}
            else "development"
        )

    @classmethod
    async def _abort_initialization(cls, ctx: Any, reason: str) -> None:
        """Best-effort cleanup for failed or cancelled initialization."""
        errors: list[str] = []
        try:
            await ctx.close()
        except asyncio.CancelledError:
            errors.append("context:CancelledError")
        except Exception as exc:
            errors.append(f"context:{type(exc).__name__}")

        candidates = (
            ("llm", getattr(ctx, "llm_engine", None)),
            ("tts", getattr(ctx, "tts_engine", None)),
            ("asr", getattr(ctx, "asr_engine", None)),
            ("llm", cls._llm),
            ("tts", cls._tts),
            ("asr", cls._asr),
        )
        seen: set[int] = set()
        for name, engine in candidates:
            if engine is None or id(engine) in seen:
                continue
            seen.add(id(engine))
            try:
                await engine.close()
            except asyncio.CancelledError:
                errors.append(f"{name}:CancelledError")
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}")

        for attr in ("llm_engine", "tts_engine", "asr_engine"):
            setattr(ctx, attr, None)
        cls._llm = cls._tts = cls._asr = None
        cls._ctx = None
        cls._ready = False
        if cls._shutdown_requested:
            cls._init_state = "closing"
            cls._init_error = None
        else:
            cls._init_state = "failed"
            cls._init_error = reason
        cls._shutdown_errors = tuple(errors)
        if errors:
            logger.warning(
                "[ServicePool] Initialization cleanup errors: {}",
                ",".join(errors),
            )
