from __future__ import annotations

"""Tests for SessionManager — context, orchestrator, audio processor lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.orchestration.server.session import SessionManager

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def session_manager():
    """SessionManager with mocked model_manager."""
    mm = MagicMock()
    return SessionManager(model_manager=mm)


@pytest.fixture
def mock_service_pool(mock_llm, mock_tts, mock_asr, mock_vad):
    """Mock ServicePool returning pre-initialized engines."""
    return {
        "llm_engine": mock_llm,
        "tts_engine": mock_tts,
        "asr_engine": mock_asr,
        "vad_engine": mock_vad,
    }


# ── SessionManager — Init ──────────────────────────────────────────


class TestSessionManagerInit:
    """SessionManager construction."""

    def test_init_creates_empty_stores(self):
        """__init__ creates empty dicts and a lock."""
        sm = SessionManager()
        assert sm.contexts == {}
        assert sm.orchestrators == {}
        assert sm.audio_processors == {}
        assert sm._orchestrator_lock is not None

    def test_init_stores_model_manager(self):
        """model_manager is stored."""
        mm = MagicMock()
        sm = SessionManager(model_manager=mm)
        assert sm.model_manager is mm

    def test_session_count_property(self):
        """session_count returns number of contexts."""
        sm = SessionManager()
        assert sm.session_count == 0
        sm.contexts["sid1"] = MagicMock()
        assert sm.session_count == 1


# ── SessionManager — get_or_create_context ─────────────────────────


class TestGetOrCreateContext:
    """ServiceContext creation and reuse."""

    @pytest.mark.asyncio
    async def test_creates_new_context_with_service_pool(
        self, session_manager, mock_service_pool, monkeypatch
    ):
        """New session uses ServicePool engines when pool is available."""
        mock_ctx = MagicMock()
        mock_ctx.load_cache = AsyncMock()
        mock_ctx.init_vad = AsyncMock()
        mock_ctx.init_memory = AsyncMock()
        mock_ctx.init_emotion_analyzer = AsyncMock()

        with patch(
            "animetta.orchestration.server.session.ServiceContext",
            return_value=mock_ctx,
        ):
            monkeypatch.setattr(
                "animetta.core.service_pool.ServicePool.get_context",
                lambda: mock_service_pool,
            )

            config = MagicMock()
            ws_send = MagicMock()
            ctx = await session_manager.get_or_create_context("sid1", config, ws_send)

            assert ctx is mock_ctx
            assert session_manager.contexts["sid1"] is mock_ctx
            mock_ctx.load_cache.assert_called_once()
            mock_ctx.init_vad.assert_called_once()
            mock_ctx.init_memory.assert_called_once()
            mock_ctx.init_emotion_analyzer.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_new_context_without_pool(
        self, session_manager, monkeypatch
    ):
        """When ServicePool is not available, load_from_config is called."""
        mock_ctx = MagicMock()
        mock_ctx.load_from_config = AsyncMock()

        with patch(
            "animetta.orchestration.server.session.ServiceContext",
            return_value=mock_ctx,
        ):
            monkeypatch.setattr(
                "animetta.core.service_pool.ServicePool.get_context",
                lambda: None,
            )

            config = MagicMock()
            await session_manager.get_or_create_context("sid2", config, MagicMock())

            mock_ctx.load_from_config.assert_called_once()
            mock_ctx.load_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_reuses_existing_context(self, session_manager):
        """Calling with existing sid returns the cached context."""
        existing = MagicMock()
        session_manager.contexts["sid1"] = existing

        ctx = await session_manager.get_or_create_context(
            "sid1", MagicMock(), MagicMock()
        )

        assert ctx is existing

    @pytest.mark.asyncio
    async def test_multiple_sessions_are_isolated(
        self, session_manager, mock_service_pool, monkeypatch
    ):
        """Different SIDs get different contexts."""
        mock_ctx_a = MagicMock()
        mock_ctx_a.load_cache = AsyncMock()
        mock_ctx_a.init_vad = AsyncMock()
        mock_ctx_a.init_memory = AsyncMock()
        mock_ctx_a.init_emotion_analyzer = AsyncMock()

        mock_ctx_b = MagicMock()
        mock_ctx_b.load_cache = AsyncMock()
        mock_ctx_b.init_vad = AsyncMock()
        mock_ctx_b.init_memory = AsyncMock()
        mock_ctx_b.init_emotion_analyzer = AsyncMock()

        ctx_counter = [0]
        def _make_ctx(**kwargs):
            ctx_counter[0] += 1
            return mock_ctx_a if ctx_counter[0] == 1 else mock_ctx_b

        with patch(
            "animetta.orchestration.server.session.ServiceContext",
            side_effect=_make_ctx,
        ):
            monkeypatch.setattr(
                "animetta.core.service_pool.ServicePool.get_context",
                lambda: mock_service_pool,
            )

            config = MagicMock()
            ctx1 = await session_manager.get_or_create_context("sid_a", config, MagicMock())
            ctx2 = await session_manager.get_or_create_context("sid_b", config, MagicMock())

            assert ctx1 is not ctx2
            assert session_manager.contexts["sid_a"] is ctx1
            assert session_manager.contexts["sid_b"] is ctx2

    def test_get_context_returns_none_for_missing(self, session_manager):
        """get_context returns None for unknown sid."""
        assert session_manager.get_context("nonexistent") is None


# ── SessionManager — get_or_create_orchestrator ────────────────────


class TestGetOrCreateOrchestrator:
    """Orchestrator lifecycle."""

    @pytest.mark.asyncio
    async def test_creates_new_orchestrator(self, session_manager, monkeypatch):
        """get_or_create_orchestrator creates a LangGraphOrchestrator."""
        mock_orch = MagicMock()

        monkeypatch.setattr(
            "animetta.orchestration.graph.orchestrator.LangGraphOrchestrator.create",
            AsyncMock(return_value=mock_orch),
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.session.SessionManager._load_tools_config",
            AsyncMock(return_value={"enable_tools": False, "config": {}}),
        )

        ctx = MagicMock()
        ctx.emotion_analyzer = MagicMock()
        orch = await session_manager.get_or_create_orchestrator(
            "sid1", ctx, MagicMock(), MagicMock(), socketio=None,
        )

        assert orch is mock_orch
        assert session_manager.orchestrators["sid1"] is mock_orch

    @pytest.mark.asyncio
    async def test_reuses_existing_orchestrator(self, session_manager):
        """Calling with existing sid returns cached orchestrator."""
        existing = MagicMock()
        session_manager.orchestrators["sid1"] = existing

        orch = await session_manager.get_or_create_orchestrator(
            "sid1", MagicMock(), MagicMock(), MagicMock(),
        )

        assert orch is existing

    @pytest.mark.asyncio
    async def test_orchestrator_lock_prevents_duplicates(self, session_manager, monkeypatch):
        """The orchestrator lock ensures only one is created per sid."""
        mock_orch = MagicMock()
        create_mock = AsyncMock(return_value=mock_orch)

        monkeypatch.setattr(
            "animetta.orchestration.graph.orchestrator.LangGraphOrchestrator.create",
            create_mock,
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.session.SessionManager._load_tools_config",
            AsyncMock(return_value={"enable_tools": False, "config": {}}),
        )

        ctx = MagicMock()
        ctx.emotion_analyzer = MagicMock()

        # Call twice sequentially — second should hit cache
        orch1 = await session_manager.get_or_create_orchestrator(
            "sid_lock", ctx, MagicMock(), MagicMock(),
        )
        orch2 = await session_manager.get_or_create_orchestrator(
            "sid_lock", ctx, MagicMock(), MagicMock(),
        )

        assert orch1 is orch2
        assert create_mock.call_count == 1

    def test_get_orchestrator_returns_none_for_missing(self, session_manager):
        """get_orchestrator returns None for unknown sid."""
        assert session_manager.get_orchestrator("nonexistent") is None


# ── SessionManager — cleanup_session ───────────────────────────────


class TestCleanupSession:
    """Session resource cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_session_cleans_everything(self, session_manager):
        """cleanup_session removes orchestrator, audio processor, and context."""
        mock_orch = MagicMock()
        mock_orch.stop = AsyncMock()
        mock_processor = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock()

        session_manager.orchestrators["sid1"] = mock_orch
        session_manager.audio_processors["sid1"] = mock_processor
        session_manager.contexts["sid1"] = mock_ctx

        await session_manager.cleanup_session("sid1")

        mock_orch.stop.assert_called_once()
        mock_processor.reset.assert_called_once()
        mock_ctx.close.assert_called_once()
        assert "sid1" not in session_manager.orchestrators
        assert "sid1" not in session_manager.audio_processors
        assert "sid1" not in session_manager.contexts

    @pytest.mark.asyncio
    async def test_cleanup_session_handles_missing_orchestrator(self, session_manager):
        """cleanup_session works when orchestrator is missing."""
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock()
        session_manager.contexts["sid1"] = mock_ctx

        await session_manager.cleanup_session("sid1")
        mock_ctx.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_session_handles_orchestrator_without_stop(self, session_manager):
        """cleanup_session handles orchestrator without stop method."""
        mock_orch = MagicMock(spec=[])  # no methods
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock()

        session_manager.orchestrators["sid1"] = mock_orch
        session_manager.contexts["sid1"] = mock_ctx

        await session_manager.cleanup_session("sid1")
        mock_ctx.close.assert_called_once()


# ── SessionManager — cleanup_all ───────────────────────────────────


class TestCleanupAll:
    """Complete cleanup of all sessions."""

    @pytest.mark.asyncio
    async def test_cleanup_all_clears_all_sessions(self, session_manager):
        """cleanup_all stops all orchestrators and closes all contexts."""
        for i in range(3):
            sid = f"sid_{i}"
            orch = MagicMock()
            orch.stop = AsyncMock()
            proc = MagicMock()
            ctx = MagicMock()
            ctx.close = AsyncMock()
            session_manager.orchestrators[sid] = orch
            session_manager.audio_processors[sid] = proc
            session_manager.contexts[sid] = ctx

        await session_manager.cleanup_all()

        assert len(session_manager.orchestrators) == 0
        assert len(session_manager.audio_processors) == 0
        assert len(session_manager.contexts) == 0


# ── SessionManager — Audio Processor ───────────────────────────────


class TestAudioProcessor:
    """Audio processor lifecycle."""

    @pytest.mark.asyncio
    async def test_get_or_create_audio_processor_creates_new(self, session_manager, monkeypatch):
        """get_or_create_audio_processor creates SimpleVADProcessor."""
        mock_processor = MagicMock()
        mock_cls = MagicMock(return_value=mock_processor)

        monkeypatch.setattr(
            "animetta.services.audio.simple_vad_processor.SimpleVADProcessor",
            mock_cls,
        )

        ctx = MagicMock()
        ctx.vad_engine = MagicMock()

        proc = await session_manager.get_or_create_audio_processor("sid1", ctx)

        assert proc is mock_processor
        assert session_manager.audio_processors["sid1"] is mock_processor
        mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_audio_processor_reuses(self, session_manager):
        """get_or_create_audio_processor returns cached processor."""
        existing = MagicMock()
        session_manager.audio_processors["sid1"] = existing

        proc = await session_manager.get_or_create_audio_processor("sid1", MagicMock())

        assert proc is existing

    def test_get_audio_processor_returns_none_for_missing(self, session_manager):
        """get_audio_processor returns None for unknown sid."""
        assert session_manager.get_audio_processor("nonexistent") is None
