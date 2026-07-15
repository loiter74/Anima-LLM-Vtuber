#!/usr/bin/env python3
"""多轮真实对话测试 — 验证好感度动态变化 + 【debug】开关。

设定（来自 anima.v0.1.yaml）：
  - 真实层：Anima 是 B 站 AI VTuber 主播，在直播间里
  - 角色扮演层：「深夜赛博酒馆」是她的直播人设，她扮演酒馆老板
  - 「旅人」= 直播间观众/弹幕，不是物理走进酒馆的人

本脚本模拟一个观众从首次进直播间到成为常客的过程：
  1. 首次进直播间，发个打招呼弹幕
  2. 发【debug】，看 Anima 对自己的初始好感度
  3. 真诚互动（夸她的直播内容），好感度应该上升
  4. 再发【debug】，验证好感度确实涨了
  5. 日常闲聊弹幕

用法:
    python scripts/smoke_test_conversation.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import Any

try:
    import socketio
except ImportError:
    print("ERROR: pip install python-socketio[client]")
    sys.exit(2)

URL = os.environ.get("ANIMA_BACKEND_URL", "http://localhost:12394")
PER_TURN_WAIT = 18.0  # DeepSeek 需要时间思考
SETTLE = 1.5


def _sentence_text(data: Any) -> str:
    """从 chat:sentence 事件里提取文本（跳过 stream-end marker）。"""
    if not isinstance(data, dict):
        return ""
    text = data.get("text", "")
    return text or ""


async def send_one(payload: dict, label: str) -> dict:
    """发一条弹幕，收完整回复。"""
    sio = socketio.AsyncClient()
    reply_parts: list[str] = []
    expressions: list[str] = []

    @sio.on("*")
    async def catch(event: str, data: Any) -> None:
        if event == "chat:sentence":
            t = _sentence_text(data)
            if t:
                reply_parts.append(t)
        elif event == "chat:expression":
            if isinstance(data, dict):
                expressions.append(data.get("emotion", ""))

    await sio.connect(URL, transports=["websocket"])
    print(f"\n{'=' * 70}")
    print(f"【{label}】")
    print(f"  弹幕 → {payload['text']}")
    await sio.emit("chat:text", payload)
    await asyncio.sleep(PER_TURN_WAIT)
    await sio.disconnect()

    reply = "".join(reply_parts).strip()
    print(f"  Anima → {reply}")
    if expressions:
        print(f"  [表情] {expressions[-1]}")

    # 检查 marker 可见性
    marker_match = re.search(r"\[affinity:(\d+)\]", reply)
    return {
        "reply": reply,
        "expressions": expressions,
        "marker_visible": marker_match is not None,
        "marker_value": int(marker_match.group(1)) if marker_match else None,
    }


async def main() -> int:
    print("═" * 70)
    print("多轮对话测试 — 好感度动态变化 + 【debug】可见性")
    print(f"Backend: {URL}")
    print("设定：Anima 是 B 站 AI 主播，「深夜赛博酒馆」是她的直播人设")
    print("═" * 70)

    # ── 弹幕设计（直播间观众视角）──
    turns = [
        (
            "第1轮·首次进直播间",
            {"text": "第一次刷到这个直播间，主播这角色扮演挺有意思的", "mode": "text"},
        ),
        ("第2轮·debug查看", {"text": "【debug】主播你对我这个新观众印象怎么样", "mode": "text"}),
        (
            "第3轮·真诚互动",
            {
                "text": "看了你几期录播，那种毒舌里带温柔的风格真的很治愈，工作一天下来听你说话特别放松",
                "mode": "text",
            },
        ),
        ("第4轮·再次debug", {"text": "【debug】我现在想知道你对我的好感度变了没", "mode": "text"}),
        (
            "第5轮·日常弹幕",
            {"text": "今天加班到现在，外面的雨下得贼大，通勤人的痛谁知道", "mode": "text"},
        ),
    ]

    results = []
    for label, payload in turns:
        try:
            res = await send_one(payload, label)
        except Exception as exc:
            print(f"  [ERROR] {exc!r}")
            res = {"reply": "", "error": str(exc), "marker_visible": False}
        results.append((label, res))
        await asyncio.sleep(SETTLE)

    # ── 复盘 ──
    print("\n" + "═" * 70)
    print("对话复盘")
    print("═" * 70)

    # 用 turn 列表的原始 payload 判断 debug（label 字符串不含全角括号）
    debug_values = []
    leak_found = False
    for i, (label, res) in enumerate(results):
        is_debug_turn = "【debug】" in turns[i][1]["text"]
        if is_debug_turn and res.get("marker_visible"):
            debug_values.append((label, res["marker_value"]))
            print(f"  ✅ {label}: 看到 [affinity:{res['marker_value']}]（debug 正常可见）")
        elif is_debug_turn and not res.get("marker_visible"):
            print(f"  ⚠️  {label}: debug 轮但没看到 marker（LLM 可能没输出）")
        elif not is_debug_turn and res.get("marker_visible"):
            print(f"  ❌ {label}: 非 debug 轮泄漏了 marker！")
            leak_found = True
        # 非 debug 轮无 marker = 正常，不打 log

    if not leak_found:
        print(f"  ✅ 所有非 debug 轮次都没有泄漏 marker")

    if len(debug_values) >= 2:
        v1 = debug_values[0][1]
        v2 = debug_values[1][1]
        delta = v2 - v1 if v1 is not None and v2 is not None else None
        print(f"\n  好感度变化: 第2轮 {v1} → 第4轮 {v2}（Δ = {delta:+d}）")
        if delta is not None and delta > 0:
            print(f"  ✅ 真诚互动后好感度上升（符合预期）")
        elif delta == 0:
            print(f"  ℹ️  好感度未变（LLM 可能判定互动不够积极）")

    print("\n" + "═" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
