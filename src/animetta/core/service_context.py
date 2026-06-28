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

        # Session state
        self.session_id: str | None = None
        self.is_speaking: bool = False
        self.is_processing: bool = False

        # Callback functions
        self.send_text: Callable | None = None

        # Emotion analyzer
        self.emotion_analyzer: Any = None

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

    # Initialization methods
    async def load_from_config(self, config: AppConfig) -> None:
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
        await self.init_memory()
        await self.init_emotion_analyzer(config)

        # Preload conversation tokenizer to avoid download/load delay on first use
        await self._preload_tokenizers()

        # Trigger preload for all registered services via model manager
        if self.model_manager is not None:
            asyncio.create_task(self.model_manager.warmup())

        logger.info(f"[{self.session_id}] Services loaded")
        logger.info(get_availability_summary())

        # Verify LLM API connectivity (non-blocking, populates health probe cache)
        asyncio.create_task(self._verify_llm_connectivity())

    async def load_cache(
        self,
        config: AppConfig,
        asr_engine: ASRInterface | None = None,
        tts_engine: TTSInterface | None = None,
        llm_engine: LLMInterface | None = None,
        send_text: Callable | None = None,
    ) -> None:
        """Load services from cache (reuse existing instances)"""
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
        """Initialize TTS service with fallback chain: requested → CPU fallback → MockTTS."""
        if self.tts_engine is not None:
            logger.debug(f"[{self.session_id}] TTS already initialized, skipping")
            return

        provider = tts_config.type
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
        self.tts_engine = TTSFactory.create(**tts_kwargs)

        # 2. If GPU provider fell back to MockTTS, retry with CPU
        device = tts_kwargs.get("device", "")
        if self.tts_engine is not None and device and "cuda" in str(device).lower():
            from animetta.services.tts.mock_tts import MockTTS
            # TracingProxy wraps the real engine in _target
            inner = getattr(self.tts_engine, "_target", self.tts_engine)
            if isinstance(inner, MockTTS) and provider != "mock":
                logger.warning(
                    f"[{self.session_id}] TTS provider '{provider}' failed with device='{device}', "
                    f"retrying with device='cpu'"
                )
                fallback_kwargs = {**tts_kwargs, "device": "cpu"}
                self.tts_engine = TTSFactory.create(**fallback_kwargs)

        # 3. Log final fallback state
        from animetta.services.tts.mock_tts import MockTTS
        inner = getattr(self.tts_engine, "_target", self.tts_engine)
        if isinstance(inner, MockTTS) and provider != "mock":
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
        logger.info(f"[{self.session_id}] Initializing LLM: {llm_config.type}/{llm_config.model}")

        if app_config:
            live2d_prompt = self._get_live2d_prompt()
            system_prompt = app_config.get_system_prompt(live2d_prompt=live2d_prompt)
            persona_name = app_config.persona
            logger.info(f"[{self.session_id}] Using persona: {persona_name}")
        else:
            system_prompt = self._build_system_prompt(agent_config, persona_config)

        self.llm_engine = LLMFactory.create_from_config(config=llm_config, system_prompt=system_prompt)
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

        logger.info(f"[{self.session_id}] Initializing local LLM: {llm_config.type}/{llm_config.model}")
        self.local_llm_engine = LLMFactory.create_from_config(config=llm_config, system_prompt="")
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
        try:
            from animetta.memory.v2.system import LivingMemorySystem
            self.memory_system = LivingMemorySystem(
                db_path="memory_db/living_memory.sqlite"
            )
            await self.memory_system.initialize()
            logger.info(f"[{self.session_id}] LivingMemory V2 initialized")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Memory system initialization failed: {e}")
            self.memory_system = None

    async def init_emotion_analyzer(self, config: AppConfig) -> None:
        """Initialize emotion analyzer"""
        try:
            live2d_config = get_live2d_config()
            if not live2d_config.enabled:
                logger.info(f"[{self.session_id}] Live2D not enabled, skipping emotion analyzer initialization")
                return

            self.emotion_analyzer = EmotionAnalyzerFactory.create(
                name="keyword_analyzer",
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

        if self.memory_system:
            try:
                await self.memory_system.shutdown()
                self.memory_system = None
                logger.info(f"[{self.session_id}] LivingMemory V2 closed")
            except Exception as e:
                logger.warning(f"[{self.session_id}] Memory shutdown failed: {e}")

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

    async def _verify_llm_connectivity(self) -> None:
        """Verify LLM API endpoint is reachable with the configured API key.

        Calls GET {base_url}/models with the API key, stores result in
        the module-level cache used by the health probe.
        Populates `inspection.checks.health._llm_connectivity_cache`.
        """
        import time as time_mod

        from animetta.inspection.checks import health as health_checks

        llm = self.llm_engine
        if llm is None:
            health_checks._llm_connectivity_cache = {
                "ok": None, "status": "llm_not_initialized"
            }
            return

        # Only probe remote APIs — skip local models
        if not hasattr(llm, "base_url") or not llm.base_url:
            health_checks._llm_connectivity_cache = {
                "ok": True, "status": "local_model"
            }
            logger.info("[health] LLM connectivity: skipped (local model)")
            return

        api_key = getattr(llm, "api_key", None)
        base_url = llm.base_url.rstrip("/")

        if not api_key:
            health_checks._llm_connectivity_cache = {
                "ok": False, "error": "no_api_key"
            }
            logger.error("[health] LLM connectivity: FAILED — no API key configured")
            return

        try:
            import httpx
            t0 = time_mod.perf_counter()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            latency_ms = (time_mod.perf_counter() - t0) * 1000

            if resp.status_code == 200:
                health_checks._llm_connectivity_cache = {
                    "ok": True, "latency_ms": round(latency_ms, 1)
                }
                logger.info(f"[health] LLM connectivity: OK ({latency_ms:.0f}ms)")
            elif resp.status_code == 401:
                health_checks._llm_connectivity_cache = {
                    "ok": False, "error": "invalid_api_key"
                }
                logger.error("[health] LLM connectivity: FAILED — invalid API key (401)")
            else:
                health_checks._llm_connectivity_cache = {
                    "ok": False, "error": f"http_{resp.status_code}"
                }
                logger.warning(
                    f"[health] LLM connectivity: returned HTTP {resp.status_code}"
                )
        except Exception as e:
            health_checks._llm_connectivity_cache = {
                "ok": False, "error": f"connection_failed: {e}"
            }
            logger.error(f"[health] LLM connectivity: FAILED — {e}")

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
