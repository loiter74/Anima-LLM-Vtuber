"""Unit tests for SkillLibrary matching, search, and cleanup logic."""

from __future__ import annotations

import pytest

from animetta.tools.minecraft.skill.library import Skill, SkillLibrary

# ── Helpers ──────────────────────────────────────────────────────────────────


def _skill(
    skill_id: str,
    name: str = "test",
    description: str = "test skill",
    category: str = "",
    preconditions: list[str] | None = None,
    tags: list[str] | None = None,
    success_count: int = 0,
    fail_count: int = 0,
    avg_duration: float = 0.0,
) -> Skill:
    return Skill(
        id=skill_id,
        name=name,
        description=description,
        category=category,
        preconditions=preconditions or [],
        tags=tags or [],
        success_count=success_count,
        fail_count=fail_count,
        avg_duration=avg_duration,
    )


async def _populate(*skills: Skill) -> SkillLibrary:
    lib = SkillLibrary()
    for s in skills:
        await lib.save_skill(s)
    return lib


# ── Matching ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMatchSkills:
    """SkillLibrary.match_skills() filtering and sorting."""

    async def test_match_skills_by_precondition(self) -> None:
        s1 = _skill("s1", preconditions=["is_day"])
        s2 = _skill("s2", preconditions=["has_pickaxe"])
        s3 = _skill("s3", preconditions=[])  # always matches

        lib = await _populate(s1, s2, s3)

        # is_day=True, no pickaxe → s1 and s3 match
        matched = await lib.match_skills({"is_day": True, "inventory": {}})
        ids = [s.id for s in matched]
        assert "s1" in ids
        assert "s3" in ids
        assert "s2" not in ids

    async def test_match_skills_sorted_by_success_rate(self) -> None:
        s1 = _skill("s1", success_count=10, fail_count=10)   # 0.5
        s2 = _skill("s2", success_count=20, fail_count=0)    # 1.0
        s3 = _skill("s3", success_count=1, fail_count=9)     # 0.1

        lib = await _populate(s1, s2, s3)
        matched = await lib.match_skills({})

        assert matched[0].id == "s2"  # highest success rate first
        assert matched[1].id == "s1"
        assert matched[2].id == "s3"

    async def test_match_skills_secondary_sort_by_duration(self) -> None:
        """Same success rate → shorter avg_duration first."""
        s1 = _skill("s1", success_count=5, fail_count=5, avg_duration=30.0)
        s2 = _skill("s2", success_count=5, fail_count=5, avg_duration=10.0)

        lib = await _populate(s1, s2)
        matched = await lib.match_skills({})

        assert matched[0].id == "s2"  # shorter duration first
        assert matched[1].id == "s1"

    async def test_match_skills_limit(self) -> None:
        skills = [_skill(f"s{i}") for i in range(10)]
        lib = await _populate(*skills)

        matched = await lib.match_skills({}, limit=3)
        assert len(matched) == 3

    async def test_match_skills_empty_library(self) -> None:
        lib = SkillLibrary()
        matched = await lib.match_skills({})
        assert matched == []


# ── Keyword Search ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSearchByKeyword:
    """SkillLibrary.search_by_keyword() scoring and matching."""

    async def test_search_by_keyword_name_match(self) -> None:
        s1 = _skill("s1", name="gather_wood", description="do stuff")
        s2 = _skill("s2", name="mine_stone", description="do stuff")

        lib = await _populate(s1, s2)
        results = await lib.search_by_keyword("wood")

        assert len(results) == 1
        assert results[0].id == "s1"

    async def test_search_by_keyword_description_match(self) -> None:
        s1 = _skill("s1", name="task", description="collect wood logs")
        s2 = _skill("s2", name="task2", description="mine stone")

        lib = await _populate(s1, s2)
        results = await lib.search_by_keyword("wood")

        assert len(results) == 1
        assert results[0].id == "s1"

    async def test_search_by_keyword_tag_match(self) -> None:
        s1 = _skill("s1", name="a", description="b", tags=["mining", "stone"])
        s2 = _skill("s2", name="c", description="d", tags=["building"])

        lib = await _populate(s1, s2)
        results = await lib.search_by_keyword("mining")

        assert len(results) == 1
        assert results[0].id == "s1"

    async def test_search_by_keyword_ranking(self) -> None:
        """Name match (2pts) > description match (1pt)."""
        s1 = _skill("s1", name="wood_gather", description="generic task")
        s2 = _skill("s2", name="task", description="gather wood")

        lib = await _populate(s1, s2)
        results = await lib.search_by_keyword("wood")

        assert len(results) == 2
        assert results[0].id == "s1"  # name match scores higher

    async def test_search_by_keyword_case_insensitive(self) -> None:
        s1 = _skill("s1", name="Gather Wood", description="stuff")
        lib = await _populate(s1)

        results = await lib.search_by_keyword("wood")
        assert len(results) == 1

    async def test_search_by_keyword_no_match(self) -> None:
        s1 = _skill("s1", name="build", description="build a house")
        lib = await _populate(s1)

        results = await lib.search_by_keyword("mining")
        assert results == []

    async def test_search_by_keyword_limit(self) -> None:
        skills = [_skill(f"s{i}", name=f"wood_{i}", description="wood task") for i in range(10)]
        lib = await _populate(*skills)

        results = await lib.search_by_keyword("wood", limit=3)
        assert len(results) == 3


# ── Category Filter ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetSkillsByCategory:
    """SkillLibrary.get_skills_by_category() filtering."""

    async def test_get_skills_by_category(self) -> None:
        s1 = _skill("s1", category="survival")
        s2 = _skill("s2", category="building")
        s3 = _skill("s3", category="survival")

        lib = await _populate(s1, s2, s3)
        results = await lib.get_skills_by_category("survival")

        assert len(results) == 2
        assert all(s.category == "survival" for s in results)

    async def test_get_skills_by_category_case_insensitive(self) -> None:
        s1 = _skill("s1", category="Building")
        lib = await _populate(s1)

        results = await lib.get_skills_by_category("building")
        assert len(results) == 1

    async def test_get_skills_by_category_no_match(self) -> None:
        s1 = _skill("s1", category="survival")
        lib = await _populate(s1)

        results = await lib.get_skills_by_category("farming")
        assert results == []

    async def test_get_skills_by_category_empty(self) -> None:
        lib = SkillLibrary()
        results = await lib.get_skills_by_category("any")
        assert results == []


# ── Tag Search ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSearchByTags:
    """SkillLibrary.search_by_tags() filtering."""

    async def test_search_by_tags_match(self) -> None:
        s1 = _skill("s1", tags=["mining", "stone"])
        s2 = _skill("s2", tags=["building", "wood"])

        lib = await _populate(s1, s2)
        results = await lib.search_by_tags(["mining"])

        assert len(results) == 1
        assert results[0].id == "s1"

    async def test_search_by_tags_multiple(self) -> None:
        s1 = _skill("s1", tags=["mining", "stone"])
        s2 = _skill("s2", tags=["building", "mining"])

        lib = await _populate(s1, s2)
        results = await lib.search_by_tags(["mining", "building"])

        assert len(results) == 2


# ── Cleanup ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCleanup:
    """SkillLibrary.cleanup() quality-based pruning."""

    async def test_cleanup_removes_low_quality(self) -> None:
        """Skills with success_rate < 0.3 AND >= 10 executions AND is_learned are removed."""
        bad = _skill("bad", success_count=2, fail_count=8)   # 0.2 rate, 10 total → removed
        bad.is_learned = True  # Only learned skills are removed
        good = _skill("good", success_count=8, fail_count=2) # 0.8 rate, 10 total → kept
        good.is_learned = True

        lib = await _populate(bad, good)
        await lib.cleanup()

        remaining = await lib.get_all_skills()
        ids = [s.id for s in remaining]
        assert "bad" not in ids
        assert "good" in ids

    async def test_cleanup_keeps_new_skills(self) -> None:
        """Skills with < 10 total executions are kept regardless of rate."""
        new_bad = _skill("new", success_count=0, fail_count=3)  # 0.0 rate, 3 total → kept

        lib = await _populate(new_bad)
        await lib.cleanup()

        remaining = await lib.get_all_skills()
        assert len(remaining) == 1
        assert remaining[0].id == "new"

    async def test_cleanup_boundary_10_executions(self) -> None:
        """Exactly 10 executions with rate < 0.3 AND is_learned → removed."""
        boundary = _skill("boundary", success_count=2, fail_count=8)  # 10 total, 0.2 rate
        boundary.is_learned = True
        lib = await _populate(boundary)

        await lib.cleanup()
        remaining = await lib.get_all_skills()
        assert len(remaining) == 0

    async def test_cleanup_boundary_9_executions(self) -> None:
        """9 executions → kept even with bad rate."""
        almost = _skill("almost", success_count=1, fail_count=8)  # 9 total
        lib = await _populate(almost)

        await lib.cleanup()
        remaining = await lib.get_all_skills()
        assert len(remaining) == 1

    async def test_cleanup_boundary_rate_03(self) -> None:
        """Rate exactly 0.3 (3/10) → not removed (threshold is < 0.3)."""
        borderline = _skill("borderline", success_count=3, fail_count=7)  # 0.3 rate
        lib = await _populate(borderline)

        await lib.cleanup()
        remaining = await lib.get_all_skills()
        assert len(remaining) == 1

    async def test_cleanup_empty_library(self) -> None:
        lib = SkillLibrary()
        await lib.cleanup()  # should not raise
        assert len(await lib.get_all_skills()) == 0


# ── Misc Library Operations ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLibraryOperations:
    """Basic CRUD operations."""

    async def test_save_and_get(self) -> None:
        lib = SkillLibrary()
        skill = _skill("s1")
        await lib.save_skill(skill)

        retrieved = await lib.get_skill("s1")
        assert retrieved is not None
        assert retrieved.id == "s1"

    async def test_get_nonexistent(self) -> None:
        lib = SkillLibrary()
        assert await lib.get_skill("missing") is None

    async def test_remove_skill(self) -> None:
        lib = SkillLibrary()
        await lib.save_skill(_skill("s1"))
        await lib.remove_skill("s1")
        assert await lib.get_skill("s1") is None

    async def test_remove_nonexistent(self) -> None:
        lib = SkillLibrary()
        await lib.remove_skill("missing")  # should not raise

    async def test_update_success(self) -> None:
        lib = SkillLibrary()
        await lib.save_skill(_skill("s1"))
        await lib.update_success("s1")

        skill = await lib.get_skill("s1")
        assert skill is not None
        assert skill.success_count == 1

    async def test_update_failure(self) -> None:
        lib = SkillLibrary()
        await lib.save_skill(_skill("s1"))
        await lib.update_failure("s1")

        skill = await lib.get_skill("s1")
        assert skill is not None
        assert skill.fail_count == 1

    async def test_get_all_skills(self) -> None:
        lib = SkillLibrary()
        await lib.save_skill(_skill("s1"))
        await lib.save_skill(_skill("s2"))
        await lib.save_skill(_skill("s3"))

        all_skills = await lib.get_all_skills()
        assert len(all_skills) == 3
