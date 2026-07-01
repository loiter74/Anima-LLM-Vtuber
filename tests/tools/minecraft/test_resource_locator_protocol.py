"""T70/T71: Resource Locator protocol + collect/mine compat (add-mcbot-resource-locator)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.core import tools

# ── T70/T9.1: locate_resource 结构化 payload 透传 ─────────────────────────────


async def test_locate_resource_success_payload_passthrough():
    """bridge.send_command 透传 node bot 返回的结构化 locate_resource 成功结果。"""
    bridge = AsyncMock()
    bridge.send_command = AsyncMock(
        return_value={
            "id": 1,
            "status": "success",
            "result": {
                "resource": "iron_ore",
                "source": "strategy:cave_scan",
                "block": "iron_ore",
                "position": {"x": 10, "y": 42, "z": -8},
                "distance": 18.2,
                "strategy": "cave_scan",
                "attempts": 3,
            },
        }
    )
    out = await bridge.send_command("locate_resource", {"resource": "iron_ore"})
    assert out["status"] == "success"
    r = out["result"]
    assert r["resource"] == "iron_ore"
    assert r["strategy"] == "cave_scan"
    assert r["position"] == {"x": 10, "y": 42, "z": -8}


async def test_locate_resource_error_payload_passthrough():
    """结构化错误（UNKNOWN_RESOURCE 等）经 bridge 透传，字段齐全。"""
    bridge = AsyncMock()
    bridge.send_command = AsyncMock(
        return_value={
            "status": "error",
            "result": {
                "message": "UNKNOWN_RESOURCE: dirt",
                "code": "UNKNOWN_RESOURCE",
                "resource": "dirt",
            },
        }
    )
    out = await bridge.send_command("locate_resource", {"resource": "dirt"})
    assert out["status"] == "error"
    assert out["result"]["code"] == "UNKNOWN_RESOURCE"
    assert out["result"]["resource"] == "dirt"


async def test_locate_resource_tool_required_payload_passthrough():
    """TOOL_REQUIRED 结构化错误透传（含 requiredTool/have/need）。"""
    bridge = AsyncMock()
    bridge.send_command = AsyncMock(
        return_value={
            "status": "error",
            "result": {
                "message": "requires stone_pickaxe",
                "code": "TOOL_REQUIRED",
                "resource": "iron_ore",
                "requiredTool": "stone_pickaxe",
                "have": 1,
                "need": 2,
            },
        }
    )
    out = await bridge.send_command("locate_resource", {"resource": "iron_ore"})
    assert out["status"] == "error"
    assert out["result"]["code"] == "TOOL_REQUIRED"
    assert out["result"]["requiredTool"] == "stone_pickaxe"


# ── T71: collect/mine 兼容形状（公开 tool 行为不变）─────────────────────────


async def test_collect_success_shape_compat():
    """mc_collect 仍返回兼容的成功串。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={"status": "success", "result": "Collected 1 oak_log"}
    )
    try:
        out = await tools.mc_collect.ainvoke({"block_type": "oak_log", "count": 1})
    finally:
        tools._bridge = None
    assert "Collected" in out and "oak_log" in out


async def test_collect_error_shape_compat():
    """mc_collect 失败仍返回兼容的错误串（Locator 在 v1 不改变 collect 错误形状）。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={"status": "error", "result": "Action failed: No more oak_log nearby"}
    )
    try:
        out = await tools.mc_collect.ainvoke({"block_type": "oak_log"})
    finally:
        tools._bridge = None
    assert "Action failed" in out or "No more" in out


async def test_mine_success_shape_compat():
    """mc_mine 仍返回兼容的成功串。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={"status": "success", "result": "Mined 3 stone"}
    )
    try:
        out = await tools.mc_mine.ainvoke({"block_type": "stone", "count": 3})
    finally:
        tools._bridge = None
    assert "Mined" in out and "stone" in out


# ── T10.2: iron/coal 收集失败时暴露可操作的 Locator 错误码 ────────────────────


async def test_collect_iron_ore_tool_required_exposes_code():
    """collect iron_ore 失败返回 TOOL_REQUIRED 时，错误消息包含 actionable 信息。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={
            "status": "error",
            "result": {
                "message": "requires stone_pickaxe",
                "code": "TOOL_REQUIRED",
                "resource": "iron_ore",
                "requiredTool": "stone_pickaxe",
                "have": 0,
                "need": 2,
            },
        }
    )
    try:
        out = await tools.mc_collect.ainvoke({"block_type": "iron_ore", "count": 1})
    finally:
        tools._bridge = None
    # 验证错误信息包含 actionable 的 code 和 requiredTool
    assert "TOOL_REQUIRED" in out or "stone_pickaxe" in out


async def test_collect_coal_ore_resource_not_found_exposes_code():
    """collect coal_ore 失败返回 RESOURCE_NOT_FOUND 时，错误信息可被 recovery 识别。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={
            "status": "error",
            "result": {
                "message": "no coal_ore found after 6 attempts",
                "code": "RESOURCE_NOT_FOUND",
                "resource": "coal_ore",
                "strategiesTried": ["memory_first", "cave_scan", "safe_descent", "spiral_scan"],
            },
        }
    )
    try:
        out = await tools.mc_collect.ainvoke({"block_type": "coal_ore", "count": 1})
    finally:
        tools._bridge = None
    # collect 透传了 Node 的结构化错误 → 消息中可识别
    assert "coal_ore" in out.lower() or "no more" in out.lower() or "Action failed" in out


async def test_mine_iron_ore_tool_required_exposes_code():
    """mine iron_ore 失败返回 TOOL_REQUIRED 时，结构化字段可被 runner recovery 使用。"""
    tools._bridge = AsyncMock()
    tools._bridge.is_running = True
    tools._bridge.send_command = AsyncMock(
        return_value={
            "status": "error",
            "result": {
                "message": "requires stone_pickaxe",
                "code": "TOOL_REQUIRED",
                "resource": "iron_ore",
                "requiredTool": "stone_pickaxe",
                "have": 1,
                "need": 2,
            },
        }
    )
    try:
        out = await tools.mc_mine.ainvoke({"block_type": "iron_ore", "count": 1})
    finally:
        tools._bridge = None
    assert "TOOL_REQUIRED" in out or "stone_pickaxe" in out or "iron_ore" in out
