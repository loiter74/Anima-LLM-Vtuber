"""Tests for self_evolution give-purity guard + evo_state (mc-evo-purity T5/T6)."""

from __future__ import annotations

import asyncio

from animetta.tools.minecraft.other import self_evolution

# ── Helpers ──────────────────────────────────────────────────────────────────


def _task(criteria: list[str]):
    """轻量 task 替身（仅需 .success_criteria）。"""

    class _T:
        success_criteria = criteria

    return _T()


async def _nosleep(*_a, **_k):
    """asyncio.sleep 替身（避免真实 1s 等待）。"""
    return None


# ── T5: MC_EVO_ALLOW_GIVE 开关守卫 ────────────────────────────────────────────


async def test_give_branch_disabled_by_default(monkeypatch):
    """默认 MC_EVO_ALLOW_GIVE=False → give 分支永不执行（_rcon 不被调用）。"""
    monkeypatch.setattr(self_evolution, "MC_EVO_ALLOW_GIVE", False)
    calls: list[str] = []
    monkeypatch.setattr(self_evolution, "_rcon", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(asyncio, "sleep", _nosleep)

    # inv 攒到 3/10 ≥ 1/5(2)，原逻辑会 give；但开关关闭 → 不应 give
    fired = await self_evolution._maybe_give_materials(
        _task(["has_oak_log >= 10"]), {"oak_log": 3}
    )

    assert fired is False
    assert calls == []  # 零 _rcon give 调用


async def test_give_branch_enabled_when_flag_on(monkeypatch):
    """显式 MC_EVO_ALLOW_GIVE=True → 保留调试期 give 行为。"""
    monkeypatch.setattr(self_evolution, "MC_EVO_ALLOW_GIVE", True)
    calls: list[str] = []
    monkeypatch.setattr(self_evolution, "_rcon", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(asyncio, "sleep", _nosleep)

    fired = await self_evolution._maybe_give_materials(
        _task(["has_oak_log >= 10"]), {"oak_log": 3}
    )

    assert fired is True
    assert calls == ["give AnimettaBot minecraft:oak_log 7"]


async def test_give_skips_tools_and_below_threshold(monkeypatch):
    """工具类（pickaxe/crafting_table/furnace）与未达 1/5 阈值的 item 不补全。"""
    monkeypatch.setattr(self_evolution, "MC_EVO_ALLOW_GIVE", True)
    calls: list[str] = []
    monkeypatch.setattr(self_evolution, "_rcon", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(asyncio, "sleep", _nosleep)

    # iron_pickaxe 在 _GIVE_SKIP_ITEMS → 跳过；oak_log have=1 < threshold=2 → 不补
    fired = await self_evolution._maybe_give_materials(
        _task(["has_iron_pickaxe >= 1", "has_oak_log >= 10"]),
        {"oak_log": 1},
    )

    assert fired is False
    assert calls == []


# ── T6: evo_state.give_mode 字段 ──────────────────────────────────────────────


def test_evo_state_give_mode_roundtrip(monkeypatch, tmp_path):
    """give_mode 字段正确写入/读取。"""
    state_file = tmp_path / "mc_evo_state.json"
    monkeypatch.setattr(self_evolution, "STATE_FILE", str(state_file))

    self_evolution._save_evo_state(
        {"completed": ["craft wooden pickaxe"], "give_mode": True, "total_rounds": 5}
    )
    loaded = self_evolution._load_evo_state()

    assert loaded["give_mode"] is True
    assert loaded["completed"] == ["craft wooden pickaxe"]
    assert loaded["total_rounds"] == 5


def test_evo_state_default_give_mode_false(monkeypatch, tmp_path):
    """状态文件缺失时，默认 give_mode=False（每个 validated skill 产生环境可审计）。"""
    monkeypatch.setattr(self_evolution, "STATE_FILE", str(tmp_path / "missing.json"))

    loaded = self_evolution._load_evo_state()

    assert loaded.get("give_mode") is False
    assert loaded["completed"] == []


def test_deepseek_llm_defaults_to_v4_pro(monkeypatch):
    """MC evo 独立闭环默认调用 DeepSeek 4 Pro。"""
    calls: list[dict] = []

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(self_evolution, "AsyncOpenAI", FakeAsyncOpenAI)

    llm = self_evolution.DeepSeekLLM()

    assert llm._model == "deepseek-v4-pro"
    assert calls == [
        {"base_url": "https://api.deepseek.com/v1", "api_key": "test-key"}
    ]


def test_gold_goal_reached_by_any_equipment_piece():
    """本轮目标是任意一件金装备，而不是金甲全套。"""
    assert self_evolution._gold_goal_reached({"golden_boots": 1}) is True
    assert self_evolution._gold_goal_reached({"gold_ingot": 24}) is False


async def test_deepseek_llm_preserves_reasoning_content(monkeypatch):
    """DeepSeek wrapper 保留 reasoning_content，供 code_generator 兜底抽取代码。"""

    class FakeMessage:
        content = ""
        reasoning_content = "await collect('gold_ore', 4);"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        async def create(self, **kwargs):
            return type("R", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(self_evolution, "AsyncOpenAI", FakeAsyncOpenAI)

    resp = await self_evolution.DeepSeekLLM().chat([{"role": "user", "content": "x"}])

    assert resp.content == ""
    assert resp.reasoning_content == "await collect('gold_ore', 4);"
