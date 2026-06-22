from __future__ import annotations

from animetta.core.service_context import ServiceContext

"""Tests for ServiceContext — core service container.

Tests cover:
- __init__ default values
- __str__ format
- load_from_config orchestration
- load_cache assignment
- Individual init methods (ASR, TTS, LLM, local LLM, VAD, audio processor, memory, emotion)
- process_text_input (success and error paths)
- close lifecycle
- handle_config_switch
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def ctx():
    """Create a fresh ServiceContext (no model_manager)."""
    return ServiceContext()


@pytest.fixture
def engine_without_preload():
    """Mock engine that does NOT have a preload attribute."""
    mock = MagicMock(spec=["close"])
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def engine_with_preload():
    """Mock engine that HAS a preload coroutine."""
    mock = MagicMock()
    mock.close = AsyncMock()
    mock.preload = AsyncMock()
    return mock


@pytest.fixture
def mock_asr_config():
    """Minimal MockASR-like config dict attributes."""
    cfg = MagicMock()
    cfg.type = "mock"
    cfg.language = "zh"
    cfg.model = "mock-model"
    cfg.api_key = None
    cfg.base_url = None
    cfg.stream = False
    cfg.device = "auto"
    cfg.compute_type = "default"
    cfg.download_root = None
    cfg.beam_size = 5
    cfg.vad_filter = True
    cfg.vad_parameters = {}
    cfg.ncpu = 4
    cfg.vad_model = None
    cfg.punc_model = None
    cfg.spk_model = None
    cfg.hotword = None
    cfg.model_hub = "ms"
    cfg.disable_update = True
    return cfg


@pytest.fixture
def mock_tts_config():
    """Mock TTS config with model_dump support."""
    cfg = MagicMock()
    cfg.type = "mock"
    cfg.model = "mock-model"
    cfg.api_key = None
    cfg.voice = "default"
    cfg.base_url = None
    cfg.response_format = "wav"
    cfg.speed = 1.0
    cfg.volume = 1.0
    cfg.ref_audio_path = None
    cfg.prompt_text = None
    cfg.prompt_lang = None
    cfg.text_lang = None
    cfg.top_k = None
    cfg.top_p = None
    cfg.temperature = None
    cfg.media_type = None
    cfg.streaming_mode = None
    cfg.text_split_method = None
    cfg.sample_steps = None
    cfg.seed = None
    cfg.model_dump = MagicMock(return_value={
        "api_key": None, "model": "mock-model", "voice": "default",
        "base_url": None, "response_format": "wav", "speed": 1.0,
        "volume": 1.0, "ref_audio_path": None, "prompt_text": None,
        "prompt_lang": None, "text_lang": None, "top_k": None, "top_p": None,
        "temperature": None, "media_type": None, "streaming_mode": None,
        "text_split_method": None, "sample_steps": None, "seed": None,
    })
    return cfg


@pytest.fixture
def mock_agent_config():
    """Mock AgentConfig with llm_config sub-object."""
    cfg = MagicMock()
    cfg.llm_config = MagicMock()
    cfg.llm_config.type = "mock"
    cfg.llm_config.model = "mock-model"
    cfg.system_prompt = "Test system prompt"
    cfg.memory_enabled = True
    return cfg


@pytest.fixture
def mock_persona_config():
    """Mock PersonaConfig."""
    cfg = MagicMock()
    cfg.build_system_prompt = MagicMock(return_value="Persona system prompt")
    return cfg


@pytest.fixture
def app_config(mock_agent_config, mock_persona_config):
    """Mock AppConfig with all sub-configs wired up."""
    cfg = MagicMock()
    cfg.persona = "test_persona"
    cfg.get_persona = MagicMock(return_value=mock_persona_config)
    cfg.get_system_prompt = MagicMock(return_value="System prompt with live2d")

    # Sub-configs — each is a MagicMock with a .type attribute
    cfg.asr = MagicMock()
    cfg.asr.type = "mock"
    cfg.tts = MagicMock()
    cfg.tts.type = "mock"
    cfg.agent = mock_agent_config
    cfg.local_llm = MagicMock()
    cfg.local_llm.type = "mock"
    cfg.vad = MagicMock()
    cfg.vad.type = "mock"
    return cfg


@pytest.fixture
def app_config_no_local_llm(mock_agent_config, mock_persona_config):
    """AppConfig with local_llm=None."""
    cfg = MagicMock()
    cfg.persona = "test_persona"
    cfg.get_persona = MagicMock(return_value=mock_persona_config)
    cfg.get_system_prompt = MagicMock(return_value="System prompt with live2d")
    cfg.asr = MagicMock()
    cfg.asr.type = "mock"
    cfg.tts = MagicMock()
    cfg.tts.type = "mock"
    cfg.agent = mock_agent_config
    cfg.local_llm = None
    cfg.vad = MagicMock()
    cfg.vad.type = "mock"
    return cfg


# ═══════════════════════════════════════════════════════════════════
# __init__
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInit:
    """Verify __init__ sets default values correctly."""

    def test_init_defaults(self, ctx):
        assert ctx.config is None
        assert ctx.model_manager is None
        assert ctx.asr_engine is None
        assert ctx.tts_engine is None
        assert ctx.llm_engine is None
        assert ctx.local_llm_engine is None
        assert ctx.vad_engine is None
        assert ctx.audio_processor is None
        assert ctx.memory_system is None
        assert ctx.session_id is None
        assert ctx.is_speaking is False
        assert ctx.is_processing is False
        assert ctx.send_text is None
        assert ctx.emotion_analyzer is None

    def test_init_with_model_manager(self):
        mock_mgr = MagicMock()
        srv = ServiceContext(model_manager=mock_mgr)
        assert srv.model_manager is mock_mgr
        assert srv.asr_engine is None


# ═══════════════════════════════════════════════════════════════════
# __str__
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextStr:
    """Verify __str__ formatting."""

    def test_str_empty(self, ctx):
        s = str(ctx)
        assert "ServiceContext(" in s
        assert "session_id=None" in s
        assert "asr=Not Loaded" in s
        assert "tts=Not Loaded" in s
        assert "llm=Not Loaded" in s
        assert "is_speaking=False" in s
        assert "is_processing=False" in s

    def test_str_with_values(self, ctx):
        ctx.session_id = "sess-01"
        ctx.is_speaking = True
        ctx.is_processing = True

        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "MockEngine"

        ctx.asr_engine = mock_engine
        ctx.tts_engine = mock_engine
        ctx.llm_engine = mock_engine

        s = str(ctx)
        assert "session_id=sess-01" in s
        assert "asr=MockEngine" in s
        assert "tts=MockEngine" in s
        assert "llm=MockEngine" in s
        assert "is_speaking=True" in s
        assert "is_processing=True" in s


# ═══════════════════════════════════════════════════════════════════
# load_from_config
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextLoadFromConfig:
    """Verify load_from_config calls every init in order."""

    @pytest.mark.asyncio
    async def test_calls_all_inits_in_order(self, ctx, app_config):
        """Each init method should receive the correct sub-config."""
        ctx.init_asr = AsyncMock()
        ctx.init_tts = AsyncMock()
        ctx.init_llm = AsyncMock()
        ctx.init_local_llm = AsyncMock()
        ctx.init_vad = AsyncMock()
        ctx.init_audio_processor = AsyncMock()
        ctx.init_memory = AsyncMock()
        ctx.init_emotion_analyzer = AsyncMock()
        ctx._preload_tokenizers = AsyncMock()

        await ctx.load_from_config(app_config)

        ctx.init_asr.assert_awaited_once_with(app_config.asr)
        ctx.init_tts.assert_awaited_once_with(app_config.tts)
        ctx.init_llm.assert_awaited_once_with(
            app_config.agent, app_config.get_persona(), app_config=app_config
        )
        ctx.init_local_llm.assert_awaited_once_with(
            app_config.local_llm, app_config=app_config
        )
        ctx.init_vad.assert_awaited_once_with(app_config.vad)
        ctx.init_audio_processor.assert_awaited_once()
        ctx.init_memory.assert_awaited_once()
        ctx.init_emotion_analyzer.assert_awaited_once_with(app_config)
        ctx._preload_tokenizers.assert_awaited_once()
        assert ctx.config is app_config

    @pytest.mark.asyncio
    async def test_stores_config(self, ctx, app_config):
        await ctx.load_from_config(app_config)
        assert ctx.config is app_config

    @pytest.mark.asyncio
    async def test_warmup_called_when_model_manager_present(self, ctx, app_config):
        """When model_manager is set, warmup() should be scheduled."""
        mock_mgr = MagicMock()
        # Make warmup() return a real coroutine so asyncio.create_task doesn't fail
        mock_mgr.warmup.return_value = asyncio.sleep(0)
        ctx.model_manager = mock_mgr

        # Mock out all init methods so they don't interfere
        ctx.init_asr = AsyncMock()
        ctx.init_tts = AsyncMock()
        ctx.init_llm = AsyncMock()
        ctx.init_local_llm = AsyncMock()
        ctx.init_vad = AsyncMock()
        ctx.init_audio_processor = AsyncMock()
        ctx.init_memory = AsyncMock()
        ctx.init_emotion_analyzer = AsyncMock()
        ctx._preload_tokenizers = AsyncMock()

        await ctx.load_from_config(app_config)
        mock_mgr.warmup.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# load_cache
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextLoadCache:
    """Verify load_cache correctly assigns passed engines."""

    @pytest.mark.asyncio
    async def test_assigns_all_values(self, ctx, app_config):
        asr = MagicMock()
        tts = MagicMock()
        llm = MagicMock()
        send_text = MagicMock()

        await ctx.load_cache(
            config=app_config,
            asr_engine=asr,
            tts_engine=tts,
            llm_engine=llm,
            send_text=send_text,
        )

        assert ctx.config is app_config
        assert ctx.asr_engine is asr
        assert ctx.tts_engine is tts
        assert ctx.llm_engine is llm
        assert ctx.send_text is send_text

    @pytest.mark.asyncio
    async def test_partial_assign(self, ctx, app_config):
        """Omitted engines remain None."""
        await ctx.load_cache(config=app_config)
        assert ctx.asr_engine is None
        assert ctx.tts_engine is None
        assert ctx.llm_engine is None
        assert ctx.send_text is None


# ═══════════════════════════════════════════════════════════════════
# init_asr
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitASR:
    """Verify ASR initialization."""

    @pytest.mark.asyncio
    async def test_calls_asr_factory(self, ctx, mock_asr_config, engine_without_preload):
        with patch("animetta.core.service_context.ASRFactory.create",
                   return_value=engine_without_preload) as mock_create:
            await ctx.init_asr(mock_asr_config)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "mock"
        assert kwargs["language"] == "zh"
        assert ctx.asr_engine is engine_without_preload

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.close = AsyncMock()
        ctx.asr_engine = existing

        with patch("animetta.core.service_context.ASRFactory.create") as mock_create:
            await ctx.init_asr(MagicMock())

        mock_create.assert_not_called()
        assert ctx.asr_engine is existing

    @pytest.mark.asyncio
    async def test_registers_with_model_manager(self, ctx, mock_asr_config, engine_with_preload):
        """Engine with preload() should register with model_manager."""
        mock_mgr = MagicMock()
        ctx.model_manager = mock_mgr

        with patch("animetta.core.service_context.ASRFactory.create",
                   return_value=engine_with_preload):
            await ctx.init_asr(mock_asr_config)

        mock_mgr.register.assert_called_once_with(
            "asr", engine_with_preload.preload, "asr"
        )

    @pytest.mark.asyncio
    async def test_skips_register_without_model_manager(self, ctx, mock_asr_config):
        """When model_manager is None, no registration happens."""
        # Ensure model_manager is None
        ctx.model_manager = None

        with patch("animetta.core.service_context.ASRFactory.create") as mock_create:
            mock_engine = MagicMock()
            mock_engine.close = AsyncMock()
            mock_create.return_value = mock_engine

            await ctx.init_asr(mock_asr_config)
            # No error should occur


# ═══════════════════════════════════════════════════════════════════
# init_tts
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitTTS:
    """Verify TTS initialization."""

    @pytest.mark.asyncio
    async def test_calls_tts_factory(self, ctx, mock_tts_config, engine_without_preload):
        with patch("animetta.core.service_context.TTSFactory.create",
                   return_value=engine_without_preload) as mock_create:
            await ctx.init_tts(mock_tts_config)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "mock"
        assert ctx.tts_engine is engine_without_preload

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.close = AsyncMock()
        ctx.tts_engine = existing

        with patch("animetta.core.service_context.TTSFactory.create") as mock_create:
            await ctx.init_tts(MagicMock())

        mock_create.assert_not_called()
        assert ctx.tts_engine is existing

    @pytest.mark.asyncio
    async def test_calls_model_dump(self, ctx, mock_tts_config, engine_without_preload):
        """Uses model_dump() when available (Pydantic v2 path)."""
        with patch("animetta.core.service_context.TTSFactory.create",
                   return_value=engine_without_preload):
            await ctx.init_tts(mock_tts_config)

        mock_tts_config.model_dump.assert_called_once_with(exclude={"type"})
        assert ctx.tts_engine is engine_without_preload

    @pytest.mark.asyncio
    async def test_falls_back_to_field_iteration(self, ctx, engine_without_preload):
        """When config lacks model_dump(), falls back to manual field extraction."""
        cfg = MagicMock()
        cfg.type = "mock"
        # Delete model_dump to simulate non-Pydantic config
        del cfg.model_dump
        cfg.api_key = None
        cfg.model = "my-model"
        cfg.voice = "my-voice"

        with patch("animetta.core.service_context.TTSFactory.create",
                   return_value=engine_without_preload) as mock_create:
            await ctx.init_tts(cfg)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "mock"
        assert kwargs["model"] == "my-model"
        assert kwargs["voice"] == "my-voice"

    @pytest.mark.asyncio
    async def test_registers_with_model_manager(self, ctx, mock_tts_config, engine_with_preload):
        mock_mgr = MagicMock()
        ctx.model_manager = mock_mgr

        with patch("animetta.core.service_context.TTSFactory.create",
                   return_value=engine_with_preload):
            await ctx.init_tts(mock_tts_config)

        mock_mgr.register.assert_called_once_with(
            "tts", engine_with_preload.preload, "tts"
        )


# ═══════════════════════════════════════════════════════════════════
# init_llm
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitLLM:
    """Verify LLM initialization."""

    @pytest.mark.asyncio
    async def test_calls_llm_factory(self, ctx, mock_agent_config, mock_persona_config):
        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.LLMFactory.create_from_config",
                   return_value=engine) as mock_create:
            await ctx.init_llm(mock_agent_config, mock_persona_config)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["config"] is mock_agent_config.llm_config
        assert "system_prompt" in call_kwargs
        assert ctx.llm_engine is engine

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.close = AsyncMock()
        ctx.llm_engine = existing

        with patch("animetta.core.service_context.LLMFactory.create_from_config") as mock_create:
            await ctx.init_llm(MagicMock(), MagicMock())

        mock_create.assert_not_called()
        assert ctx.llm_engine is existing

    @pytest.mark.asyncio
    async def test_with_app_config_uses_live2d_prompt(self, ctx, mock_agent_config, app_config):
        """When app_config is provided, get_system_prompt is called with live2d prompt."""
        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.LLMFactory.create_from_config",
                   return_value=engine):
            await ctx.init_llm(mock_agent_config, app_config.get_persona(), app_config=app_config)

        app_config.get_system_prompt.assert_called_once()
        # First arg to get_system_prompt is live2d_prompt — may be None
        assert ctx.llm_engine is engine

    @pytest.mark.asyncio
    async def test_without_app_config_uses_build_system_prompt(self, ctx, mock_agent_config, mock_persona_config):
        """Without app_config, _build_system_prompt is used."""
        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.LLMFactory.create_from_config",
                   return_value=engine) as mock_create:
            await ctx.init_llm(mock_agent_config, mock_persona_config)

        mock_create.assert_called_once()
        assert ctx.llm_engine is engine

    @pytest.mark.asyncio
    async def test_registers_with_model_manager(self, ctx, mock_agent_config, mock_persona_config):
        engine = MagicMock()
        engine.close = AsyncMock()
        engine.preload = AsyncMock()

        mock_mgr = MagicMock()
        ctx.model_manager = mock_mgr

        with patch("animetta.core.service_context.LLMFactory.create_from_config",
                   return_value=engine):
            await ctx.init_llm(mock_agent_config, mock_persona_config)

        mock_mgr.register.assert_called_once_with(
            "llm", engine.preload, "llm"
        )


# ═══════════════════════════════════════════════════════════════════
# init_local_llm
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitLocalLLM:
    """Verify local LLM initialization."""

    @pytest.mark.asyncio
    async def test_skips_when_config_is_none(self, ctx):
        with patch("animetta.core.service_context.LLMFactory.create_from_config") as mock_create:
            await ctx.init_local_llm(None)

        mock_create.assert_not_called()
        assert ctx.local_llm_engine is None

    @pytest.mark.asyncio
    async def test_creates_when_config_provided(self, ctx):
        llm_config = MagicMock()
        llm_config.type = "mock"
        llm_config.model = "mock-model"

        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.LLMFactory.create_from_config",
                   return_value=engine) as mock_create:
            await ctx.init_local_llm(llm_config)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["config"] is llm_config
        assert kwargs["system_prompt"] == ""
        assert ctx.local_llm_engine is engine

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.close = AsyncMock()
        ctx.local_llm_engine = existing

        with patch("animetta.core.service_context.LLMFactory.create_from_config") as mock_create:
            await ctx.init_local_llm(MagicMock())

        mock_create.assert_not_called()
        assert ctx.local_llm_engine is existing


# ═══════════════════════════════════════════════════════════════════
# init_vad
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitVAD:
    """Verify VAD initialization."""

    @pytest.mark.asyncio
    async def test_calls_vad_factory(self, ctx):
        vad_config = MagicMock()
        vad_config.type = "mock"

        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.VADFactory.create_from_config",
                   return_value=engine) as mock_create:
            await ctx.init_vad(vad_config)

        mock_create.assert_called_once_with(vad_config)
        assert ctx.vad_engine is engine

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.close = AsyncMock()
        ctx.vad_engine = existing

        with patch("animetta.core.service_context.VADFactory.create_from_config") as mock_create:
            await ctx.init_vad(MagicMock())

        mock_create.assert_not_called()
        assert ctx.vad_engine is existing

    @pytest.mark.asyncio
    async def test_failure_graceful(self, ctx):
        """When VAD factory raises, engine is set to None (not crash)."""
        with patch("animetta.core.service_context.VADFactory.create_from_config",
                   side_effect=ValueError("no VAD for you")):
            await ctx.init_vad(MagicMock())

        assert ctx.vad_engine is None

    @pytest.mark.asyncio
    async def test_registers_with_model_manager(self, ctx):
        vad_config = MagicMock()
        vad_config.type = "mock"

        engine = MagicMock()
        engine.close = AsyncMock()
        engine.preload = AsyncMock()

        mock_mgr = MagicMock()
        ctx.model_manager = mock_mgr

        with patch("animetta.core.service_context.VADFactory.create_from_config",
                   return_value=engine):
            await ctx.init_vad(vad_config)

        mock_mgr.register.assert_called_once_with(
            "vad", engine.preload, "vad"
        )


# ═══════════════════════════════════════════════════════════════════
# init_audio_processor
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitAudioProcessor:
    """Verify audio processor initialization."""

    @pytest.mark.asyncio
    async def test_skips_when_no_vad(self, ctx):
        ctx.vad_engine = None
        await ctx.init_audio_processor()
        assert ctx.audio_processor is None

    @pytest.mark.asyncio
    async def test_with_vad_does_not_crash(self, ctx):
        ctx.vad_engine = MagicMock()
        # Current impl just logs, does not create audio processor
        await ctx.init_audio_processor()
        # audio_processor stays None (SessionManager creates it later)
        assert ctx.audio_processor is None

    @pytest.mark.asyncio
    async def test_skip_if_already_set(self, ctx):
        existing = MagicMock()
        existing.reset = MagicMock()
        ctx.audio_processor = existing
        ctx.vad_engine = MagicMock()

        await ctx.init_audio_processor()
        # Should still be the same reference (not replaced)
        assert ctx.audio_processor is existing


# ═══════════════════════════════════════════════════════════════════
# init_memory
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitMemory:
    """Verify memory system initialization."""

    @pytest.mark.asyncio
    async def test_missing_config_file_graceful(self, ctx):
        """When memory.yaml does not exist, should not crash."""
        with patch("pathlib.Path.exists", return_value=False):
            await ctx.init_memory()

        # init_memory() does not check for config files — it always
        # attempts to create LivingMemorySystem, so memory_system is set.
        assert ctx.memory_system is not None

    @pytest.mark.asyncio
    async def test_disabled_in_config(self, ctx):
        """When LivingMemorySystem creation fails, memory_system is None."""
        with patch("animetta.memory.v2.system.LivingMemorySystem",
                   side_effect=RuntimeError("memory disabled")):
            await ctx.init_memory()

        assert ctx.memory_system is None

    @pytest.mark.asyncio
    async def test_enabled_creates_memory_system(self, ctx):
        """When LivingMemorySystem creation succeeds, memory_system is set."""
        mock_memory_system = MagicMock()
        mock_memory_system.initialize = AsyncMock()

        with patch("animetta.memory.v2.system.LivingMemorySystem",
                   return_value=mock_memory_system):
            await ctx.init_memory()

        assert ctx.memory_system is mock_memory_system
        mock_memory_system.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_graceful(self, ctx):
        """When LivingMemorySystem creation raises, engine is set to None."""
        with patch("animetta.memory.v2.system.LivingMemorySystem",
                   side_effect=RuntimeError("corrupt db")):
            await ctx.init_memory()

        assert ctx.memory_system is None


# ═══════════════════════════════════════════════════════════════════
# init_emotion_analyzer
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextInitEmotionAnalyzer:
    """Verify emotion analyzer initialization."""

    @pytest.mark.asyncio
    async def test_disabled_live2d_skips(self, ctx):
        """When Live2D is disabled, emotion analyzer is not initialized."""
        mock_live2d_config = MagicMock()
        mock_live2d_config.enabled = False

        with patch("animetta.core.service_context.get_live2d_config",
                   return_value=mock_live2d_config), \
             patch("animetta.core.service_context.EmotionAnalyzerFactory") as mock_factory:
            await ctx.init_emotion_analyzer(MagicMock())

        mock_factory.create.assert_not_called()
        assert ctx.emotion_analyzer is None

    @pytest.mark.asyncio
    async def test_enabled_live2d_creates_analyzer(self, ctx):
        """When Live2D is enabled, EmotionAnalyzerFactory.create is called."""
        mock_live2d_config = MagicMock()
        mock_live2d_config.enabled = True
        mock_live2d_config.valid_emotions = ["happy", "sad", "neutral"]

        mock_analyzer = MagicMock()

        with patch("animetta.core.service_context.get_live2d_config",
                   return_value=mock_live2d_config), \
             patch("animetta.core.service_context.EmotionAnalyzerFactory") as mock_factory:
            mock_factory.create.return_value = mock_analyzer
            await ctx.init_emotion_analyzer(MagicMock())

        mock_factory.create.assert_called_once_with(
            name="keyword_analyzer",
            config={"valid_emotions": ["happy", "sad", "neutral"]},
        )
        assert ctx.emotion_analyzer is mock_analyzer

    @pytest.mark.asyncio
    async def test_exception_graceful(self, ctx):
        """When get_live2d_config raises, engine is set to None."""
        with patch("animetta.core.service_context.get_live2d_config",
                   side_effect=FileNotFoundError("no config")):
            await ctx.init_emotion_analyzer(MagicMock())

        assert ctx.emotion_analyzer is None


# ═══════════════════════════════════════════════════════════════════
# _get_live2d_prompt
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextGetLive2dPrompt:
    """Verify _get_live2d_prompt behavior."""

    def test_disabled_returns_none(self, ctx):
        mock_live2d_config = MagicMock()
        mock_live2d_config.enabled = False

        with patch("animetta.core.service_context.get_live2d_config",
                   return_value=mock_live2d_config):
            result = ctx._get_live2d_prompt()

        assert result is None

    def test_enabled_returns_prompt(self, ctx):
        mock_live2d_config = MagicMock()
        mock_live2d_config.enabled = True
        mock_live2d_config.valid_emotions = ["happy"]

        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = "emotion prompt"

        with patch("animetta.core.service_context.get_live2d_config",
                   return_value=mock_live2d_config), \
             patch("animetta.core.service_context.EmotionPromptBuilder") as mock_builder_cls:
            mock_builder_cls.from_config.return_value = mock_builder
            result = ctx._get_live2d_prompt()

        assert result == "emotion prompt"

    def test_exception_returns_none(self, ctx):
        with patch("animetta.core.service_context.get_live2d_config",
                   side_effect=Exception("oops")):
            result = ctx._get_live2d_prompt()

        assert result is None


# ═══════════════════════════════════════════════════════════════════
# _build_system_prompt
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextBuildSystemPrompt:
    """Verify _build_system_prompt delegates to persona config."""

    def test_delegates_to_persona(self, ctx):
        mock_agent = MagicMock()
        mock_persona = MagicMock()
        mock_persona.build_system_prompt.return_value = "built prompt"

        result = ctx._build_system_prompt(mock_agent, mock_persona)

        mock_persona.build_system_prompt.assert_called_once()
        assert result == "built prompt"


# ═══════════════════════════════════════════════════════════════════
# process_text_input
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextProcessTextInput:
    """Verify process_text_input behavior."""

    @pytest.mark.asyncio
    async def test_returns_llm_response(self, ctx):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="Hello world!")
        ctx.llm_engine = mock_llm

        result = await ctx.process_text_input("Hi")

        assert result == "Hello world!"
        mock_llm.chat.assert_awaited_once_with("Hi")

    @pytest.mark.asyncio
    async def test_sets_and_clears_processing_flag(self, ctx):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="response")
        ctx.llm_engine = mock_llm

        assert ctx.is_processing is False
        await ctx.process_text_input("test")
        assert ctx.is_processing is False  # cleared in finally

    @pytest.mark.asyncio
    async def test_processing_flag_cleared_on_error(self, ctx):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=ValueError("model error"))
        ctx.llm_engine = mock_llm

        with pytest.raises(ValueError, match="model error"):
            await ctx.process_text_input("test")

        assert ctx.is_processing is False  # cleared in finally

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_no_llm(self, ctx):
        ctx.llm_engine = None

        with pytest.raises(RuntimeError, match="LLM not initialized"):
            await ctx.process_text_input("test")


# ═══════════════════════════════════════════════════════════════════
# close
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextClose:
    """Verify close lifecycle."""

    @pytest.mark.asyncio
    async def test_closes_all_services(self, ctx):
        memory_system = MagicMock()
        memory_system.shutdown = AsyncMock()

        vad = MagicMock()
        vad.close = AsyncMock()

        ctx.memory_system = memory_system
        ctx.vad_engine = vad

        await ctx.close()

        memory_system.shutdown.assert_awaited_once()
        vad.close.assert_awaited_once()

        # Memory and VAD set to None
        assert ctx.memory_system is None
        assert ctx.vad_engine is None

    @pytest.mark.asyncio
    async def test_closes_partial_services(self, ctx):
        """Only initialized services should be closed."""
        vad = MagicMock()
        vad.close = AsyncMock()
        ctx.vad_engine = vad
        # memory_system is None

        await ctx.close()

        vad.close.assert_awaited_once()
        assert ctx.vad_engine is None

    @pytest.mark.asyncio
    async def test_closes_none_no_error(self, ctx):
        """Calling close with no services initialized should not crash."""
        await ctx.close()

    @pytest.mark.asyncio
    async def test_closes_audio_processor_with_reset(self, ctx):
        """Audio processor with reset() should be reset and cleared."""
        mock_ap = MagicMock()
        mock_ap.reset = MagicMock()
        ctx.audio_processor = mock_ap

        await ctx.close()

        mock_ap.reset.assert_called_once()
        assert ctx.audio_processor is None


# ═══════════════════════════════════════════════════════════════════
# handle_config_switch
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextHandleConfigSwitch:
    """Verify config switch calls close + load_from_config."""

    @pytest.mark.asyncio
    async def test_calls_close_and_load(self, ctx, app_config):
        ctx.close = AsyncMock()
        ctx.load_from_config = AsyncMock()

        await ctx.handle_config_switch(app_config)

        ctx.close.assert_awaited_once()
        ctx.load_from_config.assert_awaited_once_with(app_config)


# ═══════════════════════════════════════════════════════════════════
# _preload_tokenizers
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextPreloadTokenizers:
    """Verify tokenizer preloading.

    The _preload_tokenizers method does ``import tiktoken`` inside its body
    (not at module level).  We intercept ``builtins.__import__`` to control
    whether tiktoken is available.  We **must** save the original __import__
    *before* the patch to avoid recursion.
    """

    @pytest.fixture
    def _orig_import(self):
        """Capture the real __import__ before any patch runs."""
        import builtins
        return builtins.__import__

    @pytest.mark.asyncio
    async def test_success(self, ctx, _orig_import):
        """When tiktoken is available, preload should call get_encoding."""
        mock_tiktoken = MagicMock()

        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                return mock_tiktoken
            return _orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            await ctx._preload_tokenizers()

        mock_tiktoken.get_encoding.assert_called_once_with("cl100k_base")

    @pytest.mark.asyncio
    async def test_import_error_graceful(self, ctx, _orig_import):
        """When tiktoken is not installed, should not crash."""
        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                raise ImportError("no tiktoken")
            return _orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            await ctx._preload_tokenizers()
            # Should not raise

    @pytest.mark.asyncio
    async def test_other_error_graceful(self, ctx, _orig_import):
        """When tiktoken.get_encoding raises, should not crash."""
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = Exception("network error")

        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                return mock_tiktoken
            return _orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            await ctx._preload_tokenizers()
            # Should not raise


# ═══════════════════════════════════════════════════════════════════
# Integration-style: factory delegation parameter correctness
# ═══════════════════════════════════════════════════════════════════


class TestServiceContextFactoryParameters:
    """Verify that init methods forward parameters correctly to factories."""

    @pytest.mark.asyncio
    async def test_asr_parameters_forwarded(self, ctx):
        """All ASR config attributes are forwarded to ASRFactory.create."""
        cfg = MagicMock()
        cfg.type = "faster_whisper"
        cfg.language = "en"
        cfg.model = "large-v3"
        cfg.api_key = None
        cfg.base_url = None
        cfg.stream = False
        cfg.device = "cuda"
        cfg.compute_type = "float16"
        cfg.download_root = "/tmp/models"
        cfg.beam_size = 3
        cfg.vad_filter = False
        cfg.vad_parameters = {"threshold": 0.5}
        cfg.ncpu = 2
        cfg.vad_model = None
        cfg.punc_model = None
        cfg.spk_model = None
        cfg.hotword = None
        cfg.model_hub = "hf"
        cfg.disable_update = False

        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.ASRFactory.create",
                   return_value=engine) as mock_create:
            await ctx.init_asr(cfg)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "faster_whisper"
        assert kwargs["language"] == "en"
        assert kwargs["model"] == "large-v3"
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "float16"
        assert kwargs["download_root"] == "/tmp/models"
        assert kwargs["beam_size"] == 3
        assert kwargs["vad_filter"] is False
        assert kwargs["vad_parameters"] == {"threshold": 0.5}
        assert kwargs["ncpu"] == 2
        assert kwargs["model_hub"] == "hf"
        assert kwargs["disable_update"] is False

    @pytest.mark.asyncio
    async def test_tts_parameters_forwarded(self, ctx):
        """TTS config attributes are forwarded (via model_dump)."""
        cfg = MagicMock()
        cfg.type = "edge_tts"
        cfg.model_dump = MagicMock(return_value={
            "api_key": None,
            "model": "my-model",
            "voice": "zh-CN-XiaoxiaoNeural",
            "base_url": None,
            "response_format": "wav",
            "speed": 1.2,
            "volume": 1.0,
        })

        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.TTSFactory.create",
                   return_value=engine) as mock_create:
            await ctx.init_tts(cfg)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "edge_tts"
        assert kwargs["voice"] == "zh-CN-XiaoxiaoNeural"
        assert kwargs["speed"] == 1.2

    @pytest.mark.asyncio
    async def test_vad_parameters_forwarded(self, ctx):
        """VAD config is forwarded to VADFactory.create_from_config."""
        cfg = MagicMock()
        cfg.type = "silero"

        engine = MagicMock()
        engine.close = AsyncMock()

        with patch("animetta.core.service_context.VADFactory.create_from_config",
                   return_value=engine) as mock_create:
            await ctx.init_vad(cfg)

        mock_create.assert_called_once_with(cfg)
