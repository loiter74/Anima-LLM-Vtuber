from __future__ import annotations

from animetta.config.core.registry import ProviderRegistry
from animetta.orchestration.graph.output_node import output_node
from animetta.services.llm import LLMFactory, MockLLM
from animetta.services.vad import MockVAD, VADFactory

"""
主链路 Bug 修复自动化测试

覆盖：VAD/LLM 服务注册与降级、output_node 事件推送
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保项目 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ============================================================
# Bug 1: VAD 服务注册
# ============================================================

class TestVADServicesRegistered:
    """验证 VAD silero + mock 注册成功"""

    def test_vad_services_registered(self):
        """导入 VAD 模块后 silero 和 mock 都应在 Registry 中"""

        # 触发导入
        import animetta.services.vad  # noqa: F401

        services = ProviderRegistry.list_services("vad")
        assert "silero" in services, f"silero 未注册, 当前: {services}"
        assert "mock" in services, f"mock 未注册, 当前: {services}"


# ============================================================
# Bug 2: VAD 工厂降级
# ============================================================

class TestVADFactoryFallback:
    """验证 VAD 创建失败降级到 MockVAD"""

    def test_vad_factory_fallback_to_mock(self):
        """VAD 主创建失败时应降级到 MockVAD，不抛 ModuleNotFoundError"""

        # 用一个会触发 ProviderRegistry 创建失败的 config
        fake_config = MagicMock()
        fake_config.type = "nonexistent_provider"
        fake_config.sample_rate = 16000

        result = VADFactory.create_from_config(fake_config)
        assert isinstance(result, MockVAD), f"降级失败，返回了 {type(result)}"


# ============================================================
# Bug 3: LLM 工厂降级
# ============================================================

class TestLLMFactoryFallback:
    """验证 LLM 创建失败降级到 MockLLM"""

    def test_llm_factory_fallback_to_mock(self):
        """LLM 主创建失败时应降级到 MockLLM，不抛 ModuleNotFoundError"""

        # 用一个会触发创建失败的 config
        fake_config = MagicMock()
        fake_config.type = "nonexistent_provider"

        result = LLMFactory.create_from_config(fake_config, system_prompt="test")
        assert isinstance(result, MockLLM), f"降级失败，返回了 {type(result)}"


# ============================================================
# Bug 4-6: output_node 事件推送
# ============================================================

class TestOutputNodeExpression:
    """验证 output_node 发送 expression 事件"""

    @pytest.mark.asyncio
    async def test_output_node_sends_expression(self):
        """当 state["emotion"] 有值时，应发送 expression 事件"""

        mock_sio = AsyncMock()
        mock_sc = MagicMock(memory_system=None)

        state = {
            "session_id": "test",
            "channel_id": "ch1",
            "response_text": "你好",
            "emotion": "happy",
            "tts_audio": None,
            "user_text": "hi",
        }
        config = {
            "configurable": {
                "socketio": mock_sio,
                "service_context": mock_sc,
            }
        }

        await output_node(state, config)

        # 验证 expression 事件被发送
        expression_calls = [
            c for c in mock_sio.emit.call_args_list
            if c.args[0] == "chat:expression"
        ]
        assert len(expression_calls) == 1, f"expression 事件未发送, calls: {mock_sio.emit.call_args_list}"
        payload = expression_calls[0].args[1]
        assert payload["emotion"] == "happy"


class TestOutputNodeVolumes:
    """验证 audio_with_expression 包含 volumes"""

    @pytest.mark.asyncio
    async def test_output_node_sends_volumes(self, tmp_path):
        """当 TTS 返回文件路径时，audio_with_expression 应包含 volumes"""

        # 创建一个假的音频文件（足够短，不需要真实音频内容）
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"\xff\xfb\x90\x00" * 500)

        mock_sio = AsyncMock()
        mock_sc = MagicMock(memory_system=None)

        state = {
            "session_id": "test",
            "channel_id": "ch1",
            "response_text": "你好",
            "emotion": None,
            "user_text": "hi",
            "tts_audio": str(audio_file),
        }
        config = {
            "configurable": {
                "socketio": mock_sio,
                "service_context": mock_sc,
            }
        }

        # mock AudioAnalyzer 因为假文件不是真正的 mp3
        with patch(
            "animetta.orchestration.graph.output_node._compute_volumes",
            return_value=[0.1, 0.5, 0.3]
        ):
            await output_node(state, config)

        # 验证 audio_with_expression 包含 volumes
        audio_calls = [
            c for c in mock_sio.emit.call_args_list
            if c.args[0] == "chat:audio_with_expression"
        ]
        assert len(audio_calls) == 1, "audio_with_expression 事件未发送"
        payload = audio_calls[0].args[1]
        assert "volumes" in payload, "audio_with_expression 缺少 volumes 字段"
        assert payload["volumes"] == [0.1, 0.5, 0.3]


class TestOutputNodeControlSignals:
    """验证 conversation-start/end 控制信号"""

    @pytest.mark.asyncio
    async def test_output_node_sends_control_signals(self):
        """output_node 应在开头发 conversation-start，末尾发 conversation-end"""

        mock_sio = AsyncMock()
        mock_sc = MagicMock(memory_system=None)

        state = {
            "session_id": "test",
            "channel_id": "ch1",
            "response_text": "你好",
            "emotion": None,
            "tts_audio": None,
            "user_text": "hi",
        }
        config = {
            "configurable": {
                "socketio": mock_sio,
                "service_context": mock_sc,
            }
        }

        await output_node(state, config)

        control_calls = [
            c for c in mock_sio.emit.call_args_list
            if c.args[0] == "chat:control"
        ]

        signals = [c.args[1]["signal"] for c in control_calls]
        assert "conversation-start" in signals, f"缺少 conversation-start, signals: {signals}"
        assert "conversation-end" in signals, f"缺少 conversation-end, signals: {signals}"

        # 验证顺序：start 在 end 之前
        start_idx = signals.index("conversation-start")
        end_idx = signals.index("conversation-end")
        assert start_idx < end_idx, "conversation-start 必须在 conversation-end 之前"
