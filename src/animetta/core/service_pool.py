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

from typing import Any

from loguru import logger


class ServicePool:
    """Globally shared LLM/TTS/ASR engine instances."""

    _llm: Any | None = None
    _tts: Any | None = None
    _asr: Any | None = None
    _ready: bool = False
    _ctx: Any | None = None

    # ── Lifecycle ──────────────────────────────────────────

    @classmethod
    async def init(cls, config, model_manager=None) -> None:
        """Create all shareable engines from *config* and keep them alive.

        Spawns a temporary ServiceContext, loads all services, then
        extracts LLM/TTS/ASR and discards the per-session services
        (VAD, Memory).
        """
        if cls._ready:
            logger.debug("[ServicePool] Already initialized")
            return

        import time as _time
        t0 = _time.perf_counter()
        logger.info("[ServicePool] Initializing shared service instances...")

        from .service_context import ServiceContext

        ctx = ServiceContext(model_manager=model_manager)
        ctx.session_id = "__pool__"
        try:
            await ctx.load_from_config(config)
        except Exception as e:
            logger.error(f"[ServicePool] Initialization failed: {e}")
            # Close whatever was opened
            await ctx.close()
            raise

        cls._llm = ctx.llm_engine
        cls._tts = ctx.tts_engine
        cls._asr = ctx.asr_engine
        cls._ready = True

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

        # Keep ctx alive so LLM/TTS/ASR engines stay in memory.
        # We do NOT call ctx.close() — that would destroy the shared engines.
        cls._ctx = ctx

        elapsed = (_time.perf_counter() - t0) * 1000
        logger.info(f"[ServicePool] Ready ({elapsed:.0f}ms) — shared LLM/TTS/ASR")

    @classmethod
    def get_context(cls) -> dict[str, Any]:
        """Return a dict of shareable engines for ``ServiceContext.load_cache()``.

        Returns an empty dict when the pool is not ready (caller falls
        back to full ``load_from_config()``).
        """
        if not cls._ready:
            return {}
        return {
            "llm_engine": cls._llm,
            "tts_engine": cls._tts,
            "asr_engine": cls._asr,
        }

    @classmethod
    async def shutdown(cls) -> None:
        """Cleanly shut down all pooled engines."""
        if not cls._ready:
            return
        logger.info("[ServicePool] Shutting down shared instances...")

        if cls._llm is not None:
            await cls._llm.close()
        if cls._tts is not None:
            await cls._tts.close()
        if cls._asr is not None:
            await cls._asr.close()

        cls._llm = cls._tts = cls._asr = None
        cls._ready = False
        cls._ctx = None
        logger.info("[ServicePool] Shut down")

    @classmethod
    def is_ready(cls) -> bool:
        return cls._ready
