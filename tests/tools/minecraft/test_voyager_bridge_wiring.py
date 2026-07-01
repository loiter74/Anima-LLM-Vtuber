"""T9: bridge Voyager 学习闭环接线 (mc-bot-voyager-learning)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.other import self_evolution


def _bridge(*, running=False, llm=None) -> MinecraftBridge:
    pool = MagicMock()
    pool._llm = llm
    bridge = MinecraftBridge(MagicMock(), autonomous=False, service_pool=pool)
    bridge._running = running
    return bridge


# ── _launch_learning_loop ────────────────────────────────────────────────────


async def test_launch_learning_loop_creates_task_and_invokes_run_loop(monkeypatch):
    """_launch_learning_loop 后台创建 task 跑 run_learning_loop（复用 self_evolution 核心）。"""
    fake_run = AsyncMock(return_value={"completed": 0, "failed": 0})
    monkeypatch.setattr(self_evolution, "run_learning_loop", fake_run)

    bridge = _bridge()
    lib = MagicMock()
    lib.save_skill = AsyncMock()

    await bridge._launch_learning_loop(lib, "the-llm")

    assert bridge._learning_task is not None
    await asyncio.sleep(0.05)  # 让 task 跑起来
    fake_run.assert_awaited_once()
    args = fake_run.await_args.args
    assert args[0] is bridge and args[1] is lib and args[2] == "the-llm"
    bridge._learning_task.cancel()


# ── set_voyager_mode 启停 ────────────────────────────────────────────────────


async def test_set_mode_learn_launches_loop_when_running(monkeypatch):
    """bridge 已运行时切 learn → 拉起学习闭环。"""
    llm = object()
    bridge = _bridge(running=True, llm=llm)
    lib = MagicMock()
    bridge._skill_library = lib
    launch = AsyncMock()
    monkeypatch.setattr(bridge, "_launch_learning_loop", launch)

    out = await bridge.set_voyager_mode("learn")

    assert out["voyager_mode"] == "learn"
    assert bridge._voyager_mode == "learn"
    launch.assert_awaited_once_with(lib, llm)


async def test_set_mode_learn_does_not_launch_when_not_running(monkeypatch):
    """bridge 未运行时切 learn → 仅记录模式，不拉起。"""
    bridge = _bridge(running=False, llm=object())
    launch = AsyncMock()
    monkeypatch.setattr(bridge, "_launch_learning_loop", launch)

    await bridge.set_voyager_mode("learn")

    assert bridge._voyager_mode == "learn"
    launch.assert_not_awaited()


async def test_set_mode_live_cancels_learning_task():
    """切离 learn → 取消学习 task。"""
    bridge = _bridge()
    bridge._learning_task = asyncio.create_task(asyncio.sleep(100))

    await bridge.set_voyager_mode("live")

    assert bridge._learning_task is None
    assert bridge._voyager_mode == "live"


async def test_set_mode_learn_skips_when_task_already_running(monkeypatch):
    """已在学习时再切 learn → 不重复拉起。"""
    bridge = _bridge(running=True, llm=object())
    bridge._skill_library = MagicMock()
    bridge._learning_task = asyncio.create_task(asyncio.sleep(100))  # 已在学
    launch = AsyncMock()
    monkeypatch.setattr(bridge, "_launch_learning_loop", launch)

    await bridge.set_voyager_mode("learn")

    launch.assert_not_awaited()
    bridge._learning_task.cancel()
