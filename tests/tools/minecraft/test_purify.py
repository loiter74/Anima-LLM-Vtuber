"""Tests for purify_validated_skills (mc-evo-purity T7)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.other import purify
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import Skill
from animetta.tools.minecraft.skill.verifier import VerifyResult

# ── Helpers ──────────────────────────────────────────────────────────────────


def _code_skill(
    id_: str,
    name: str,
    code: str,
    postconditions: list[str],
    *,
    fail_count: int = 0,
) -> Skill:
    return Skill(
        id=id_,
        name=name,
        description=f"voyager skill {name}",
        body={"type": "code", "code": code, "api_version": "v1", "timeout": 180.0},
        postconditions=postconditions,
        tags=["voyager", "learned", "code-body"],
        validated=True,
        is_learned=False,
        fail_count=fail_count,
    )


def _bridge_for(codes_that_disconnect: set[str] | None = None):
    """AsyncMock bridge：code 含 DISCONNECT 标记时抛异常（模拟断连）。"""
    codes_that_disconnect = codes_that_disconnect or set()

    async def _send(cmd, payload, timeout=None):
        if payload.get("code", "") in codes_that_disconnect:
            raise ConnectionError("bridge disconnected")
        return {"status": "success", "result": "ok"}

    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = _send
    return bridge


async def _get_state_fn(_bridge, inv: dict | None = None):
    """快照替身（verify 被 mock，inv 仅作可观测）。"""
    return ({"inventory": inv or {}, "position": None, "health": 20, "food": 20}, inv or {})


# ── T7: purify 降级 / 保留 / 跳过 ─────────────────────────────────────────────


async def test_purify_demotes_fake_keeps_real_skips_dead(monkeypatch):
    """假技能降级、真技能保留、断连 skill 跳过（不中断整体复验）。"""
    real = _code_skill("real", "real_skill", "// real", ["has_oak_log >= 1"])
    fake = _code_skill("fake", "fake_skill", "// fake", ["has_iron_ingot >= 3"])
    dead = _code_skill("dead", "dead_skill", "DISCONNECT", ["has_coal >= 1"])

    lib = SkillLibrary()
    for s in (real, fake, dead):
        await lib.save_skill(s)

    bridge = _bridge_for(codes_that_disconnect={"DISCONNECT"})

    # verify 按 skill.name 分流：real → 通过，其余 → 失败
    async def fake_verify(skill_or_task, criteria, snapshot, llm=None):
        name = getattr(skill_or_task, "name", str(skill_or_task))
        if name == "real_skill":
            return VerifyResult(passed=True, gate="deterministic", reason="ok")
        return VerifyResult(passed=False, gate="deterministic", reason="missing item")

    monkeypatch.setattr(purify, "verify", fake_verify)

    report = await purify.purify_validated_skills(
        bridge, lib, get_state_fn=_get_state_fn
    )

    # 计数
    assert report["total"] == 3
    assert report["kept"] == 1
    assert report["demoted"] == 1
    assert report["skipped"] == 1
    assert report["evicted"] == 0

    # 状态：real 仍 validated；fake 已降级；dead 未触碰（跳过）
    assert (await lib.get_skill("real")).validated is True
    assert (await lib.get_skill("fake")).validated is False
    assert (await lib.get_skill("dead")).validated is True


async def test_purify_evicts_repeated_failure(monkeypatch):
    """连续失败达阈值（fail_count ≥ 3）→ remove_skill 淘汰。"""
    # fail_count 已为 2 → 本次 verify 失败后 update_failure 到 3 → 淘汰
    stale = _code_skill("stale", "stale_skill", "// stale", ["has_diamond >= 1"], fail_count=2)

    lib = SkillLibrary()
    await lib.save_skill(stale)

    bridge = _bridge_for()

    async def fail_verify(skill_or_task, criteria, snapshot, llm=None):
        return VerifyResult(passed=False, gate="deterministic", reason="no diamonds")

    monkeypatch.setattr(purify, "verify", fail_verify)

    report = await purify.purify_validated_skills(
        bridge, lib, fail_threshold=3, get_state_fn=_get_state_fn
    )

    assert report["demoted"] == 0
    assert report["evicted"] == 1
    assert await lib.get_skill("stale") is None  # 已被 remove_skill 淘汰


async def test_purify_skips_when_bridge_not_running(monkeypatch):
    """bridge 未运行（断连）→ 跳过 skill、不中断。"""
    skill = _code_skill("s1", "s", "// s", ["has_oak_log >= 1"])
    lib = SkillLibrary()
    await lib.save_skill(skill)

    bridge = _bridge_for()
    bridge.is_running = False  # 断连

    async def pass_verify(skill_or_task, criteria, snapshot, llm=None):
        return VerifyResult(passed=True, gate="deterministic")

    monkeypatch.setattr(purify, "verify", pass_verify)

    report = await purify.purify_validated_skills(bridge, lib, get_state_fn=_get_state_fn)

    assert report["skipped"] == 1
    assert report["kept"] == 0
    assert (await lib.get_skill("s1")).validated is True  # 未被改动


async def test_purify_forces_give_off(monkeypatch):
    """purify 强制 MC_EVO_ALLOW_GIVE=False（env + self_evolution 模块属性）。"""
    from animetta.tools.minecraft.other import self_evolution

    monkeypatch.setenv("MC_EVO_ALLOW_GIVE", "1")
    self_evolution.MC_EVO_ALLOW_GIVE = True  # 模拟外部开启

    lib = SkillLibrary()  # 空 lib → 无 candidate，但仍应强制关闭 give
    bridge = _bridge_for()

    await purify.purify_validated_skills(bridge, lib, get_state_fn=_get_state_fn)

    import os
    assert os.environ.get("MC_EVO_ALLOW_GIVE") == "0"
    assert self_evolution.MC_EVO_ALLOW_GIVE is False
