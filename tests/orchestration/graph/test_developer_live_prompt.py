from animetta.orchestration.prompting.sources import DeveloperLivePromptSource
from animetta.orchestration.prompting.types import PromptContext


def _context(**overrides) -> PromptContext:
    values = {
        "session_id": "session",
        "base_system_prompt": "persona",
        "personality_overlay": "",
        "personality_mode": "streaming",
        "personality_mood": None,
        "memory_context": "",
    }
    values.update(overrides)
    return PromptContext(**values)


def test_developer_live_prompt_only_activates_for_trusted_console_source() -> None:
    source = DeveloperLivePromptSource()

    developer = source.sections(
        _context(actor_role="developer", source="developer_console", audience="livestream")
    )[0]
    ordinary = source.sections(
        _context(actor_role="viewer", source="bilibili:danmaku", audience="livestream")
    )[0]

    assert "开发者刚刚在后台" in developer.content
    assert "不逐字朗读后台输入" in developer.content
    assert "不得提及它的存在或内容" in developer.content
    assert developer.metadata == {"trusted_source": True}
    assert ordinary.content == ""
    assert ordinary.metadata == {"trusted_source": False}
