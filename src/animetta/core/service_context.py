"""
Service context - core service container
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from animetta.avatar.factory import EmotionAnalyzerFactory
from animetta.avatar.prompts import EmotionPromptBuilder
from animetta.config.agent import AgentConfig
from animetta.config.app import AppConfig
from animetta.config.live2d import get_live2d_config
from animetta.config.persona.base import PersonaConfig
from animetta.config.providers.asr import ASRConfig
from animetta.config.providers.tts import TTSConfig
from animetta.config.providers.vad import VADConfig
from animetta.core.model_loading_manager import ModelLoadingManager
from animetta.core.readiness import (
    canonical_deepseek_endpoint,
    unwrap_tracing_proxy,
)
from animetta.services.asr import ASRFactory, ASRInterface
from animetta.services.audio.processor import AudioProcessorInterface
from animetta.services.llm import LLMFactory, LLMInterface
from animetta.services.tts import TTSFactory, TTSInterface
from animetta.services.vad import VADFactory, VADInterface
from animetta.utils.service_availability import get_availability_summary

if TYPE_CHECKING:
    from animetta.memory.v2.system import LivingMemorySystem


class ServiceContext:
    """Service context class"""

    def __init__(self, model_manager: ModelLoadingManager | None = None):
        self.config: AppConfig | None = None
        self.model_manager = model_manager

        # Service instances
        self.asr_engine: ASRInterface | None = None
        self.tts_engine: TTSInterface | None = None
        self.llm_engine: LLMInterface | None = None
        self.local_llm_engine: LLMInterface | None = None
        self.vad_engine: VADInterface | None = None

        # Memory system
        self.audio_processor: AudioProcessorInterface | None = None
        self.memory_system: LivingMemorySystem | None = None
        self.memory_runtime: Any | None = None
        self._owns_memory_system = True

        # Session state
        self.session_id: str | None = None
        self.runtime_config_version: int = 1
        self.is_speaking: bool = False
        self.is_processing: bool = False

        # Callback functions
        self.send_text: Callable | None = None

        # Emotion analyzer
        self.emotion_analyzer: Any = None

        # Cached startup connectivity probe.  Public snapshots contain only
        # lifecycle state, a reason code, and optional latency.
        self._llm_connectivity_status: dict[str, str | bool | float | None] = {
            "state": "pending",
            "ready": False,
            "reason": None,
        }
        self._llm_connectivity_task: asyncio.Task[dict[str, Any]] | None = None
        self._model_warmup_task: asyncio.Task[None] | None = None

    def __str__(self) -> str:
        return (
            f"ServiceContext(\n"
            f"  session_id={self.session_id},\n"
            f"  asr={type(self.asr_engine).__name__ if self.asr_engine else 'Not Loaded'},\n"
            f"  tts={type(self.tts_engine).__name__ if self.tts_engine else 'Not Loaded'},\n"
            f"  llm={type(self.llm_engine).__name__ if self.llm_engine else 'Not Loaded'},\n"
            f"  is_speaking={self.is_speaking},\n"
            f"  is_processing={self.is_processing}\n"
            f")"
        )

    @staticmethod
    def _is_golden_profile(config: AppConfig | None) -> bool:
        """Return whether *config* selects fail-closed golden runtime behavior."""
        if config is None:
            return False
        system = getattr(config, "system", None)
        return getattr(system, "runtime_profile", None) == "golden"

    @staticmethod
    def _unwrap_tracing_proxy(engine: Any) -> Any:
        """Return the concrete service hidden behind any tracing wrappers."""
        return unwrap_tracing_proxy(engine)

    @classmethod
    def _is_mock_llm(cls, engine: Any) -> bool:
        from animetta.services.llm.mock_llm import MockLLM

        return isinstance(cls._unwrap_tracing_proxy(engine), MockLLM)

    @classmethod
    def _is_mock_tts(cls, engine: Any) -> bool:
        from animetta.services.tts.mock_tts import MockTTS

        return isinstance(cls._unwrap_tracing_proxy(engine), MockTTS)

    @classmethod
    def _validate_golden_cached_engines(
        cls,
        *,
        llm_engine: LLMInterface | None,
        tts_engine: TTSInterface | None,
    ) -> None:
        """Reject cached engines without the concrete golden provider identity."""
        from animetta.services.llm.openai_llm import OpenAILLM
        from animetta.services.tts.qwen3_tts import Qwen3TTSTTS

        concrete_llm = cls._unwrap_tracing_proxy(llm_engine)
        concrete_tts = cls._unwrap_tracing_proxy(tts_engine)
        if not isinstance(concrete_llm, OpenAILLM):
            raise RuntimeError("Golden profile requires a real LLM engine")
        try:
            provider_identity = concrete_llm.provider_identity
        except Exception:
            provider_identity = None
        if provider_identity != "deepseek":
            raise RuntimeError(
                "Golden profile requires DeepSeek provider identity"
            )
        if not isinstance(concrete_tts, Qwen3TTSTTS):
            raise RuntimeError("Golden profile requires a real TTS engine")

    # Initialization methods
    async def load_from_config(
        self,
        config: AppConfig,
        *,
        initialize_memory: bool = True,
    ) -> None:
        """Load all services from config"""
        self.config = config
        logger.info(f"[{self.session_id}] Loading services from config...")

        await self.init_asr(config.asr)
        await self.init_tts(config.tts)
        if config.agent is not None:
            await self.init_llm(config.agent, config.get_persona(), app_config=config)
        await self.init_local_llm(config.local_llm, app_config=config)
        await self.init_vad(config.vad)
        await self.init_audio_processor()
        if initialize_memory:
            await self.init_memory()
        await self.init_emotion_analyzer(config)

        if self._is_golden_profile(config):
            self._validate_golden_cached_engines(
                llm_engine=self.llm_engine,
                tts_engine=self.tts_engine,
            )

        # Preload conversation tokenizer to avoid download/load delay on first use
        await self._preload_tokenizers()

        # Trigger preload for all registered services via model manager
        if self.model_manager is not None and (
            self._model_warmup_task is None
            or self._model_warmup_task.done()
        ):
            self._model_warmup_task = asyncio.create_task(
                self.model_manager.warmup()
            )

        logger.info(f"[{self.session_id}] Services loaded")
        logger.info(get_availability_summary())

        # Verify remote OpenAI-compatible engines in a tracked startup task.
        # Explicit mock/local development contexts remain pending instead of
        # mutating the process-wide inspection cache.
        from animetta.services.llm.openai_llm import OpenAILLM

        concrete_llm = self._unwrap_tracing_proxy(self.llm_engine)
        if self._is_golden_profile(config) or isinstance(concrete_llm, OpenAILLM):
            self.start_llm_connectivity_probe()

    async def load_cache(
        self,
        config: AppConfig,
        asr_engine: ASRInterface | None = None,
        tts_engine: TTSInterface | None = None,
        llm_engine: LLMInterface | None = None,
        send_text: Callable | None = None,
    ) -> None:
        """Load services from cache (reuse existing instances)"""
        if self._is_golden_profile(config):
            self._validate_golden_cached_engines(
                llm_engine=llm_engine,
                tts_engine=tts_engine,
            )
        self.config = config
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.llm_engine = llm_engine
        self.send_text = send_text
        logger.debug(f"[{self.session_id}] Loading service context from cache")

    async def init_asr(self, asr_config: ASRConfig) -> None:
        """Initialize ASR service"""
        if self.asr_engine is not None:
            logger.debug(f"[{self.session_id}] ASR already initialized, skipping")
            return

        provider = asr_config.type
        model = getattr(asr_config, 'model', 'default')
        logger.info(f"[{self.session_id}] Initializing ASR: {provider}/{model}")

        self.asr_engine = ASRFactory.create(
            provider=provider,
            api_key=getattr(asr_config, 'api_key', None),
            model=getattr(asr_config, 'model', 'whisper-1'),
            language=asr_config.language,
            base_url=getattr(asr_config, 'base_url', None),
            stream=getattr(asr_config, 'stream', False),
            device=getattr(asr_config, 'device', 'auto'),
            compute_type=getattr(asr_config, 'compute_type', 'default'),
            download_root=getattr(asr_config, 'download_root', None),
            beam_size=getattr(asr_config, 'beam_size', 5),
            vad_filter=getattr(asr_config, 'vad_filter', True),
            vad_parameters=getattr(asr_config, 'vad_parameters', {}),
            ncpu=getattr(asr_config, 'ncpu', 4),
            vad_model=getattr(asr_config, 'vad_model', None),
            punc_model=getattr(asr_config, 'punc_model', None),
            spk_model=getattr(asr_config, 'spk_model', None),
            hotword=getattr(asr_config, 'hotword', None),
            model_hub=getattr(asr_config, 'model_hub', 'ms'),
            disable_update=getattr(asr_config, 'disable_update', True),
        )

        if hasattr(self.asr_engine, 'preload') and self.model_manager is not None:
            self.model_manager.register("asr", self.asr_engine.preload, "asr")

    async def _preload_tokenizers(self) -> None:
        """Preload conversation tokenizer (tiktoken, etc.) to avoid download/load delay on first use"""
        try:
            import asyncio

            import tiktoken
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: tiktoken.get_encoding("cl100k_base"))
            logger.info(f"[{self.session_id}] tiktoken tokenizer preloaded")
        except ImportError:
            logger.debug(f"[{self.session_id}] tiktoken not installed, skipping preload")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Tokenizer preload failed (does not affect operation): {e}")

    async def init_tts(self, tts_config: TTSConfig) -> None:
        """Initialize TTS, retaining the legacy CPU/Mock chain outside golden mode."""
        if self.tts_engine is not None:
            logger.debug(f"[{self.session_id}] TTS already initialized, skipping")
            return

        provider = tts_config.type
        golden = self._is_golden_profile(self.config)
        if golden and provider == "mock":
            raise RuntimeError("MockTTS is forbidden in the golden profile")

        model = getattr(tts_config, 'model', 'default')
        logger.info(f"[{self.session_id}] Initializing TTS: {provider}/{model}")

        # Convert the config object to dict and pass all fields to factory
        tts_kwargs = {"provider": provider}
        if hasattr(tts_config, 'model_dump'):
            cfg_dict = tts_config.model_dump(exclude={'type'})
            tts_kwargs.update(cfg_dict)
        else:
            for field in ['api_key', 'model', 'voice', 'base_url', 'response_format',
                          'speed', 'volume', 'ref_audio_path', 'prompt_text',
                          'prompt_lang', 'text_lang', 'top_k', 'top_p', 'temperature',
                          'media_type', 'streaming_mode', 'text_split_method',
                          'sample_steps', 'seed']:
                val = getattr(tts_config, field, None)
                if val is not None:
                    tts_kwargs[field] = val

        # --- Fallback chain ---
        # 1. Try requested config (e.g. kokoro + cuda)
        tts_engine = TTSFactory.create(**tts_kwargs, strict=golden)
        if golden and self._is_mock_tts(tts_engine):
            raise RuntimeError("MockTTS is forbidden in the golden profile")
        self.tts_engine = tts_engine

        # 2. If GPU provider fell back to MockTTS, retry with CPU
        device = tts_kwargs.get("device", "")
        if (
            not golden
            and self.tts_engine is not None
            and device
            and "cuda" in str(device).lower()
            and self._is_mock_tts(self.tts_engine)
            and provider != "mock"
        ):
            logger.warning(
                f"[{self.session_id}] TTS provider '{provider}' failed with device='{device}', "
                f"retrying with device='cpu'"
            )
            fallback_kwargs = {**tts_kwargs, "device": "cpu"}
            self.tts_engine = TTSFactory.create(**fallback_kwargs, strict=False)

        # 3. Log final fallback state
        if self._is_mock_tts(self.tts_engine) and provider != "mock":
            logger.warning(
                f"[{self.session_id}] TTS fallback: '{provider}' unavailable, using MockTTS (silent)"
            )

        if hasattr(self.tts_engine, 'preload') and self.model_manager is not None:
            self.model_manager.register("tts", self.tts_engine.preload, "tts")

    async def init_llm(self, agent_config: AgentConfig, persona_config: PersonaConfig, app_config: AppConfig = None) -> None:
        """Initialize LLM service"""
        if self.llm_engine is not None:
            logger.debug(f"[{self.session_id}] LLM already initialized, skipping")
            return

        llm_config = agent_config.llm_config
        profile_config = app_config if app_config is not None else self.config
        golden = self._is_golden_profile(profile_config)
        if golden and llm_config.type == "mock":
            raise RuntimeError("MockLLM is forbidden in the golden profile")

        logger.info(f"[{self.session_id}] Initializing LLM: {llm_config.type}/{llm_config.model}")

        if app_config:
            live2d_prompt = self._get_live2d_prompt()
            system_prompt = app_config.get_system_prompt(live2d_prompt=live2d_prompt)
            persona_name = app_config.persona
            logger.info(f"[{self.session_id}] Using persona: {persona_name}")
        else:
            system_prompt = self._build_system_prompt(agent_config, persona_config)

        llm_engine = LLMFactory.create_from_config(
            config=llm_config,
            system_prompt=system_prompt,
            strict=golden,
        )
        if golden and self._is_mock_llm(llm_engine):
            raise RuntimeError("MockLLM is forbidden in the golden profile")
        self.llm_engine = llm_engine
        logger.info(f"[{self.session_id}] LLM created: {type(self.llm_engine).__name__}")

        if hasattr(self.llm_engine, 'preload') and self.model_manager is not None:
            self.model_manager.register("llm", self.llm_engine.preload, "llm")

    async def init_local_llm(self, llm_config, app_config: AppConfig = None) -> None:
        """Initialize local LLM service (no persona)"""
        if self.local_llm_engine is not None:
            logger.debug(f"[{self.session_id}] Local LLM already initialized, skipping")
            return

        if llm_config is None:
            logger.info(f"[{self.session_id}] Local LLM config is empty, skipping initialization")
            return

        profile_config = app_config if app_config is not None else self.config
        golden = self._is_golden_profile(profile_config)
        if golden:
            if llm_config.type == "mock":
                raise RuntimeError("MockLLM is forbidden in the golden profile")
            raise RuntimeError("Local LLM is forbidden in the golden profile")

        logger.info(f"[{self.session_id}] Initializing local LLM: {llm_config.type}/{llm_config.model}")
        local_llm_engine = LLMFactory.create_from_config(
            config=llm_config,
            system_prompt="",
            strict=golden,
        )
        self.local_llm_engine = local_llm_engine
        logger.info(f"[{self.session_id}] Local LLM created: {type(self.local_llm_engine).__name__}")

    def _get_live2d_prompt(self) -> str | None:
        """Get Live2D emotion prompt"""
        try:
            live2d_config = get_live2d_config()
            if not live2d_config.enabled:
                return None

            builder = EmotionPromptBuilder.from_config({"valid_emotions": live2d_config.valid_emotions})
            return builder.build_prompt()
        except Exception as e:
            logger.warning(f"Failed to get Live2D prompt: {e}")
            return None

    def _build_system_prompt(self, agent_config: AgentConfig, persona_config: PersonaConfig) -> str:
        """Build system prompt (fallback method)"""
        return persona_config.build_system_prompt()

    async def init_vad(self, vad_config: VADConfig) -> None:
        """Initialize VAD service"""
        if self.vad_engine is not None:
            logger.debug(f"[{self.session_id}] VAD already initialized, skipping")
            return

        provider = vad_config.type
        logger.info(f"[{self.session_id}] Initializing VAD engine: {provider}")

        try:
            self.vad_engine = VADFactory.create_from_config(vad_config)
            logger.info(f"[{self.session_id}] VAD engine created: {type(self.vad_engine).__name__}")

            if hasattr(self.vad_engine, 'preload') and self.model_manager is not None:
                self.model_manager.register("vad", self.vad_engine.preload, "vad")

            if hasattr(self.vad_engine, 'prob_threshold'):
                logger.info(f"[{self.session_id}] VAD config: "
                           f"prob_threshold={self.vad_engine.prob_threshold}, "
                           f"db_threshold={getattr(self.vad_engine, 'db_threshold', 'N/A')}, "
                           f"required_hits={getattr(self.vad_engine, 'required_hits', 'N/A')}, "
                           f"required_misses={getattr(self.vad_engine, 'required_misses', 'N/A')}")
        except Exception as e:
            logger.error(f"[{self.session_id}] VAD engine creation failed: {e}")
            self.vad_engine = None

    async def init_audio_processor(self) -> None:
        """Initialize audio processor"""
        if hasattr(self, 'audio_processor') and self.audio_processor is not None:
            logger.debug(f"[{self.session_id}] AudioProcessor already initialized, skipping")
            return
        if self.vad_engine is None:
            logger.debug(f"[{self.session_id}] No VAD engine, skipping audio processor initialization")
            return
        logger.debug(f"[{self.session_id}] Audio processor will be created by SessionManager")

    async def init_memory(self) -> None:
        """Initialize LivingMemorySystem V2."""
        system = getattr(self.config, "system", None)
        if getattr(system, "long_term_memory_mode", "off") == "off":
            self.memory_system = None
            logger.info(f"[{self.session_id}] LivingMemory disabled by policy")
            return
        try:
            from animetta.memory.v2.system import LivingMemorySystem
            self.memory_system = LivingMemorySystem(
                db_path="memory_db/living_memory.sqlite"
            )
            await self.memory_system.initialize()
            self._owns_memory_system = True
            logger.info(f"[{self.session_id}] LivingMemory V2 initialized")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Memory system initialization failed: {e}")
            self.memory_system = None

    def attach_memory_system(
        self,
        memory_system: LivingMemorySystem,
        *,
        owned: bool = False,
    ) -> None:
        """Attach an initialized memory system with explicit ownership."""

        self.memory_system = memory_system
        self._owns_memory_system = owned

    async def init_emotion_analyzer(self, config: AppConfig) -> None:
        """Initialize emotion analyzer"""
        try:
            live2d_config = get_live2d_config()
            if not live2d_config.enabled:
                logger.info(f"[{self.session_id}] Live2D not enabled, skipping emotion analyzer initialization")
                return

            self.emotion_analyzer = EmotionAnalyzerFactory.create(
                name="llm_tag_analyzer",
                config={"valid_emotions": live2d_config.valid_emotions}
            )
            logger.info(f"[{self.session_id}] Emotion analyzer initialized")

        except Exception as e:
            logger.warning(f"[{self.session_id}] Emotion analyzer initialization failed: {e}")
            self.emotion_analyzer = None

    # Lifecycle management
    async def close(self) -> None:
        """Close and clean up per-session resources.

        Shared engines (LLM/TTS/ASR from ServicePool) are NOT closed here
        — they are managed by ServicePool.shutdown().
        """
        logger.info(f"[{self.session_id}] Shutting down service context...")

        connectivity_task = self._llm_connectivity_task
        if connectivity_task is not None:
            if not connectivity_task.done():
                connectivity_task.cancel()
            await asyncio.gather(connectivity_task, return_exceptions=True)
            self._llm_connectivity_task = None

        warmup_task = self._model_warmup_task
        if warmup_task is not None:
            if not warmup_task.done():
                warmup_task.cancel()
            await asyncio.gather(warmup_task, return_exceptions=True)
            self._model_warmup_task = None

        if self.memory_system and self._owns_memory_system:
            try:
                await self.memory_system.shutdown()
                self.memory_system = None
                logger.info(f"[{self.session_id}] LivingMemory V2 closed")
            except Exception as e:
                logger.warning(f"[{self.session_id}] Memory shutdown failed: {e}")
        elif self.memory_system:
            self.memory_system = None

        # Only close per-session engines (VAD), NOT shared engines from pool
        # Shared engines are managed by ServicePool and shared across sessions
        if self.vad_engine:
            await self.vad_engine.close()
            self.vad_engine = None
        if hasattr(self, 'audio_processor') and self.audio_processor:
            if hasattr(self.audio_processor, 'reset'):
                self.audio_processor.reset()
            self.audio_processor = None

        logger.info(f"[{self.session_id}] Service context closed")

    @property
    def llm_connectivity_status(self) -> dict[str, str | bool | float | None]:
        """Return detached, content-free cached connectivity metadata."""
        return dict(self._llm_connectivity_status)

    def start_llm_connectivity_probe(self) -> asyncio.Task[dict[str, Any]]:
        """Start the explicit startup probe once and retain its task."""
        if self._llm_connectivity_task is None:
            self._llm_connectivity_task = asyncio.create_task(
                self.verify_llm_connectivity()
            )
        return self._llm_connectivity_task

    async def wait_for_llm_connectivity(self) -> dict[str, Any]:
        """Await the tracked startup probe and return its safe status."""
        return await self.start_llm_connectivity_probe()

    def _set_llm_connectivity_status(
        self,
        *,
        state: str,
        ready: bool,
        reason: str | None = None,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        status: dict[str, Any] = {
            "state": state,
            "ready": ready,
            "reason": reason,
        }
        if latency_ms is not None:
            status["latency_ms"] = round(latency_ms, 1)
        self._llm_connectivity_status = status

        # Preserve the inspection cache contract without exposing endpoint,
        # credentials, provider response bodies, or exception text.
        from animetta.inspection.checks import health as health_checks

        health_checks._llm_connectivity_cache = {
            "ok": ready,
            "status": state,
            **({"error": reason} if reason else {}),
            **(
                {"latency_ms": round(latency_ms, 1)}
                if latency_ms is not None
                else {}
            ),
        }
        return dict(status)

    async def verify_llm_connectivity(
        self,
        *,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Probe the configured client once during startup and cache the result.

        The provider model list is deliberately discarded.  No network work is
        performed by the readiness endpoint itself.
        """
        import time as time_mod

        self._set_llm_connectivity_status(state="loading", ready=False)
        llm = self._unwrap_tracing_proxy(self.llm_engine)
        if llm is None:
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason="probe_unavailable",
            )

        golden = self._is_golden_profile(self.config)
        expected_model: str | None = None
        if golden:
            try:
                configured = self.config.agent.llm_config
                configured_raw_endpoint = configured.base_url
                engine_raw_endpoint = llm.base_url
                expected_model = configured.model
            except Exception:
                return self._set_llm_connectivity_status(
                    state="failed",
                    ready=False,
                    reason="endpoint_missing",
                )
            if not configured_raw_endpoint or not engine_raw_endpoint:
                return self._set_llm_connectivity_status(
                    state="failed",
                    ready=False,
                    reason="endpoint_missing",
                )
            configured_endpoint = canonical_deepseek_endpoint(
                configured_raw_endpoint
            )
            engine_endpoint = canonical_deepseek_endpoint(engine_raw_endpoint)
            if configured_endpoint is None or engine_endpoint is None:
                return self._set_llm_connectivity_status(
                    state="failed",
                    ready=False,
                    reason="endpoint_policy",
                )
            if configured_endpoint != engine_endpoint:
                return self._set_llm_connectivity_status(
                    state="failed",
                    ready=False,
                    reason="endpoint_mismatch",
                )

        if not getattr(llm, "base_url", None):
            logger.info("[health] LLM connectivity: local provider, probe skipped")
            return self._set_llm_connectivity_status(
                state="ready",
                ready=True,
            )
        if not getattr(llm, "api_key", None):
            logger.error("[health] LLM connectivity failed: no API key")
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason="no_api_key",
            )

        try:
            list_models = llm.client.models.list
            if not callable(list_models):
                raise TypeError("models.list is unavailable")
        except Exception:
            logger.error("[health] LLM connectivity failed: probe unavailable")
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason="probe_unavailable",
            )

        started = time_mod.perf_counter()
        try:
            model_catalog = await asyncio.wait_for(
                list_models(),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("[health] LLM connectivity timed out")
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason="timeout",
            )
        except Exception as exc:
            reason = (
                "unauthorized"
                if getattr(exc, "status_code", None) == 401
                else "request_failed"
            )
            logger.warning("[health] LLM connectivity failed: {}", reason)
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason=reason,
            )

        if golden and not self._model_catalog_contains(
            model_catalog,
            expected_model,
        ):
            logger.warning("[health] LLM configured model unavailable")
            return self._set_llm_connectivity_status(
                state="failed",
                ready=False,
                reason="model_unavailable",
            )

        latency_ms = (time_mod.perf_counter() - started) * 1000
        logger.info("[health] LLM connectivity ready ({:.0f}ms)", latency_ms)
        return self._set_llm_connectivity_status(
            state="ready",
            ready=True,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _model_catalog_contains(catalog: Any, expected_model: str | None) -> bool:
        """Check a provider response without retaining or serializing its content."""
        if not expected_model:
            return False
        try:
            entries = (
                catalog.get("data")
                if isinstance(catalog, dict)
                else getattr(catalog, "data", None)
            )
            if not isinstance(entries, (list, tuple)):
                return False
            for entry in entries:
                model_id = (
                    entry.get("id")
                    if isinstance(entry, dict)
                    else getattr(entry, "id", None)
                )
                if model_id == expected_model:
                    return True
        except Exception:
            return False
        return False

    async def _verify_llm_connectivity(self) -> dict[str, Any]:
        """Backward-compatible alias for the tracked connectivity probe."""
        return await self.verify_llm_connectivity()

    # Core business flow
    async def process_text_input(self, text: str) -> str:
        """Process text input"""
        if not self.llm_engine:
            raise RuntimeError("LLM not initialized")
        self.is_processing = True
        try:
            response = await self.llm_engine.chat(text)
            return response
        finally:
            self.is_processing = False

    # Configuration switching
    async def handle_config_switch(self, new_config: AppConfig) -> None:
        """Handle configuration switch"""
        logger.info(f"[{self.session_id}] Switching configuration...")
        await self.close()
        await self.load_from_config(new_config)
        logger.info(f"[{self.session_id}] Configuration switch complete")
