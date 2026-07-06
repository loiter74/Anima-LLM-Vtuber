"""Tests for SkillExtractor — LLM-based skill extraction from task traces."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.tools.minecraft.other.trace_recorder import ActionTrace, TaskTrace
from animetta.tools.minecraft.skill.extractor import (
    _FEW_SHOT_EXAMPLES,
    _FULL_SYSTEM_PROMPT,
    SkillExtractor,
    SkillExtractorError,
    _format_context,
    _format_trace_steps,
)
from animetta.tools.minecraft.skill.library import Skill, SkillLibrary, SkillStep

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_action_trace(
    action: str = "collect",
    params: dict | None = None,
    result: str = "success",
    duration: float = 5.0,
    error: str | None = None,
) -> ActionTrace:
    """Build a minimal ActionTrace."""
    return ActionTrace(
        action=action,
        params=params or {"block_type": "oak_log", "count": 5},
        result=result,
        duration=duration,
        state_before={"inventory": {"oak_log": 0}},
        state_after={"inventory": {"oak_log": 5}},
        error=error,
    )


def _make_task_trace(
    goal: str = "collect 10 oak logs",
    final_result: str = "success",
    steps: list[ActionTrace] | None = None,
    total_duration: float = 37.1,
    items_gained: dict | None = None,
    items_lost: dict | None = None,
    distance_traveled: float = 12.0,
) -> TaskTrace:
    """Build a minimal TaskTrace."""
    if steps is None:
        steps = [
            _make_action_trace("goto", {"x": 120, "y": 64, "z": -340}, duration=2.1),
            _make_action_trace("collect", {"block_type": "oak_log", "count": 5}, duration=18.3),
            _make_action_trace("collect", {"block_type": "oak_log", "count": 5}, duration=16.7),
        ]
    return TaskTrace(
        id="test_trace_001",
        goal=goal,
        steps=steps,
        final_result=final_result,
        total_duration=total_duration,
        items_gained=items_gained or {"oak_log": 10},
        items_lost=items_lost or {},
        distance_traveled=distance_traveled,
        start_position={"x": 120, "y": 64, "z": -340},
        end_position={"x": 125, "y": 64, "z": -335},
        timestamp="2026-01-01T00:00:00",
    )


def _sample_skill_json() -> dict:
    """Valid skill JSON the LLM might return."""
    return {
        "name": "collect_wood",
        "description": "Gather oak logs by navigating to nearby trees and mining them.",
        "category": "collection",
        "parameters": {"count": "int", "block_type": "str"},
        "preconditions": [],
        "postconditions": ["has_oak_log >= count"],
        "tags": ["wood", "gathering", "oak", "logs"],
        "steps": [
            {
                "name": "collect",
                "params": {"block_type": "oak_log", "count": 5},
                "preconditions": [],
                "timeout": 60.0,
                "retry": 1,
            },
            {
                "name": "collect",
                "params": {"block_type": "oak_log", "count": 5},
                "preconditions": [],
                "timeout": 60.0,
                "retry": 1,
            },
        ],
    }


def _mock_llm_response(content: str) -> MagicMock:
    """Build a mock LLM response object with .content attribute."""
    resp = MagicMock()
    resp.content = content
    return resp


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm():
    """Mock LLM service with async chat method."""
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_library():
    """Mock SkillLibrary with async search_skills."""
    lib = MagicMock(spec=SkillLibrary)
    lib.search_skills = AsyncMock(return_value=[])
    lib.save_skill = AsyncMock(return_value=True)
    return lib


@pytest.fixture
def extractor(mock_llm, mock_library):
    """SkillExtractor with mocked LLM and library."""
    return SkillExtractor(
        llm_service=mock_llm,
        skill_library=mock_library,
        similarity_threshold=0.8,
    )


# ── _format_trace_steps ─────────────────────────────────────────────────────


class TestFormatTraceSteps:
    """_format_trace_steps helper tests."""

    def test_formats_numbered_list(self):
        steps = [
            _make_action_trace("goto", {"x": 0, "y": 64, "z": 0}, duration=2.0),
            _make_action_trace("collect", {"block_type": "oak_log", "count": 5}, duration=10.0),
        ]
        result = _format_trace_steps(steps)
        assert "1. goto" in result
        assert "2. collect" in result
        assert "success" in result

    def test_error_status_shown(self):
        step = _make_action_trace("mine", error="Timeout")
        result = _format_trace_steps([step])
        assert "error" in result


# ── _format_context ──────────────────────────────────────────────────────────


class TestFormatContext:
    """_format_context helper tests."""

    def test_none_returns_placeholder(self):
        assert _format_context(None) == "  (none)"

    def test_empty_returns_placeholder(self):
        assert _format_context({}) == "  (none)"

    def test_formats_key_value_pairs(self):
        result = _format_context({"time": "day", "biome": "forest"})
        assert "time: day" in result
        assert "biome: forest" in result


# ── SkillExtractor._extract_json ────────────────────────────────────────────


class TestExtractJson:
    """JSON extraction from LLM responses."""

    def test_direct_json(self):
        data = SkillExtractor._extract_json('{"key": "value"}')
        assert data == {"key": "value"}

    def test_json_in_markdown_block(self):
        text = '```json\n{"key": "value"}\n```'
        data = SkillExtractor._extract_json(text)
        assert data == {"key": "value"}

    def test_json_in_generic_code_block(self):
        text = '```\n{"key": "value"}\n```'
        data = SkillExtractor._extract_json(text)
        assert data == {"key": "value"}

    def test_no_json_raises(self):
        import json as json_mod
        with pytest.raises(json_mod.JSONDecodeError):
            SkillExtractor._extract_json("just plain text, no json here")


# ── SkillExtractor._build_skill ─────────────────────────────────────────────


class TestBuildSkill:
    """Skill construction from parsed JSON + trace."""

    def test_builds_skill_with_steps(self):
        data = _sample_skill_json()
        trace = _make_task_trace()
        skill = SkillExtractor._build_skill(data, trace)
        assert skill.name == "collect_wood"
        assert len(skill.steps) == 2
        assert skill.steps[0].name == "collect"
        assert skill.category == "collection"
        assert skill.success_count == 1
        assert skill.fail_count == 0

    def test_build_skill_seeds_stats(self):
        data = _sample_skill_json()
        trace = _make_task_trace(total_duration=42.5)
        skill = SkillExtractor._build_skill(data, trace)
        assert skill.avg_duration == 42.5
        assert skill.last_used == trace.timestamp

    def test_empty_steps_raises(self):
        data = {"name": "empty", "steps": []}
        trace = _make_task_trace()
        with pytest.raises(ValueError, match="no steps"):
            SkillExtractor._build_skill(data, trace)


# ── SkillExtractor.extract ──────────────────────────────────────────────────


class TestExtractSuccess:
    """Successful extraction from a valid trace."""

    async def test_extract_success(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        mock_llm.chat.return_value = _mock_llm_response(
            json.dumps(_sample_skill_json())
        )

        skill = await extractor.extract(trace)

        assert skill is not None
        assert skill.name == "collect_wood"
        assert skill.category == "collection"
        assert len(skill.steps) == 2
        mock_llm.chat.assert_awaited_once()

    async def test_extract_passes_context_to_prompt(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        mock_llm.chat.return_value = _mock_llm_response(
            json.dumps(_sample_skill_json())
        )
        context = {"time": "day", "biome": "forest"}

        await extractor.extract(trace, context=context)

        call_args = mock_llm.chat.call_args[1]
        messages = call_args["messages"]
        user_msg = messages[1]["content"]
        assert "day" in user_msg
        assert "forest" in user_msg

    async def test_extract_system_prompt_includes_few_shot(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        mock_llm.chat.return_value = _mock_llm_response(
            json.dumps(_sample_skill_json())
        )

        await extractor.extract(trace)

        call_args = mock_llm.chat.call_args[1]
        system_msg = call_args["messages"][0]["content"]
        assert system_msg == _FULL_SYSTEM_PROMPT


class TestExtractFailure:
    """Extraction failure scenarios."""

    async def test_no_llm_raises_error(self, mock_library):
        extractor = SkillExtractor(llm_service=None, skill_library=mock_library)
        trace = _make_task_trace()
        with pytest.raises(SkillExtractorError, match="No LLM service"):
            await extractor.extract(trace)

    async def test_invalid_json_raises_error(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        mock_llm.chat.return_value = _mock_llm_response("not valid json!!!")

        with pytest.raises(SkillExtractorError, match="Failed to parse"):
            await extractor.extract(trace)

    async def test_llm_exception_raises_error(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        mock_llm.chat.side_effect = RuntimeError("connection lost")

        with pytest.raises(SkillExtractorError, match="LLM call failed"):
            await extractor.extract(trace)

    async def test_non_success_trace_returns_none(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace(final_result="failed: timeout")
        result = await extractor.extract(trace)
        assert result is None
        mock_llm.chat.assert_not_awaited()

    async def test_empty_steps_returns_none(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace(steps=[])
        result = await extractor.extract(trace)
        assert result is None
        mock_llm.chat.assert_not_awaited()


class TestDuplicateDetection:
    """Duplicate skill detection."""

    async def test_duplicate_skips_extraction(self, extractor, mock_llm, mock_library):
        """When library finds a high-confidence match, extraction is skipped."""
        existing_skill = Skill(
            id="existing_001",
            name="collect_wood",
            description="Gather oak logs",
            steps=[SkillStep(name="collect", params={"block_type": "oak_log", "count": 10})],
        )
        existing_skill.success_count = 10
        existing_skill.fail_count = 0  # 100% success rate
        mock_library.search_skills.return_value = [existing_skill]

        trace = _make_task_trace()
        result = await extractor.extract(trace)

        assert result is None
        mock_llm.chat.assert_not_awaited()

    async def test_low_success_rate_not_duplicate(self, extractor, mock_llm, mock_library):
        """When match exists but has low success_rate, extraction proceeds."""
        existing_skill = Skill(
            id="existing_002",
            name="collect_wood",
            description="Gather oak logs",
            steps=[SkillStep(name="collect", params={"block_type": "oak_log", "count": 10})],
        )
        existing_skill.success_count = 2
        existing_skill.fail_count = 8  # 20% success rate < 0.8 threshold
        mock_library.search_skills.return_value = [existing_skill]
        mock_llm.chat.return_value = _mock_llm_response(
            json.dumps(_sample_skill_json())
        )

        trace = _make_task_trace()
        result = await extractor.extract(trace)

        assert result is not None
        mock_llm.chat.assert_awaited_once()

    async def test_no_library_skips_duplicate_check(self, mock_llm):
        """Without a library, duplicate check is skipped entirely."""
        extractor = SkillExtractor(llm_service=mock_llm, skill_library=None)
        mock_llm.chat.return_value = _mock_llm_response(
            json.dumps(_sample_skill_json())
        )

        trace = _make_task_trace()
        result = await extractor.extract(trace)

        assert result is not None


class TestFewShotExamples:
    """Few-shot prompt content tests."""

    def test_four_examples_exist(self):
        assert len(_FEW_SHOT_EXAMPLES) == 4

    def test_each_example_has_user_and_assistant(self):
        for ex in _FEW_SHOT_EXAMPLES:
            assert "user" in ex
            assert "assistant" in ex

    def test_examples_have_valid_json_assistant(self):
        for ex in _FEW_SHOT_EXAMPLES:
            data = json.loads(ex["assistant"])
            assert "name" in data
            assert "steps" in data
            assert isinstance(data["steps"], list)

    def test_system_prompt_includes_all_examples(self):
        for ex in _FEW_SHOT_EXAMPLES:
            # The user portion of each example should appear in the full prompt
            assert ex["user"][:30] in _FULL_SYSTEM_PROMPT


class TestSetLLM:
    """set_llm() tests."""

    def test_set_llm_updates_service(self):
        extractor = SkillExtractor(llm_service=None)
        new_llm = MagicMock()
        extractor.set_llm(new_llm)
        assert extractor._llm is new_llm


class TestJsonParsing:
    """Various JSON format handling."""

    async def test_json_with_extra_whitespace(self, extractor, mock_llm, mock_library):
        trace = _make_task_trace()
        raw = "   " + json.dumps(_sample_skill_json()) + "   \n"
        mock_llm.chat.return_value = _mock_llm_response(raw)

        skill = await extractor.extract(trace)
        assert skill is not None
        assert skill.name == "collect_wood"

    async def test_json_with_leading_text(self, extractor, mock_llm, mock_library):
        """LLM sometimes prefixes with explanation text before the JSON block."""
        trace = _make_task_trace()
        raw = (
            "Here is the extracted skill:\n\n"
            "```json\n"
            + json.dumps(_sample_skill_json())
            + "\n```"
        )
        mock_llm.chat.return_value = _mock_llm_response(raw)

        skill = await extractor.extract(trace)
        assert skill is not None
