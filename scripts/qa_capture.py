#!/usr/bin/env python3
"""QA 页面捕获测试 — playwright + Socket.IO 双路验证。

按 AGENTS.md 要求：每次测试前必须重新获取数据，禁止使用缓存结果。

测试矩阵：
  1. UI 截图捕获（playwright）—— 首页、发弹幕后、收到回复后
  2. Socket.IO 功能验证：
     A. 普通弹幕 → 收到回复，无 [affinity:N] 泄漏
     B. 【debug】弹幕 → 收到回复，含 [affinity:N]（可见）
     C. 无意义弹幕（"哦哦哦..."）→ 无动作描写违规
     D. inspection 探针 → 不触发 LLM
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import socketio
except ImportError:
    print("ERROR: pip install python-socketio[client]")
    sys.exit(2)

# ── 配置 ────────────────────────────────────────────────────────────

BACKEND_HTTP = os.environ.get("ANIMA_FRONTEND_URL", "http://localhost")
SOCKETIO_URL = os.environ.get("ANIMA_BACKEND_URL", "http://localhost")
PER_TURN_WAIT = 18.0
SCREENSHOTS_DIR = Path("evidence/frontend") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=False)


# ── Socket.IO 功能测试 ──────────────────────────────────────────────


async def send_danmaku(text: str, label: str, expect_marker_visible: bool | None = None) -> dict:
    """发一条弹幕，收完整回复，返回 {reply, expressions, marker_visible, marker_value}。"""
    sio = socketio.AsyncClient()
    reply_parts: list[str] = []
    expressions: list[str] = []

    @sio.on("*")
    async def catch(event: str, data: Any) -> None:
        if event in {"chat:reply", "chat:sentence"}:
            if isinstance(data, dict) and data.get("text"):
                reply_parts.append(data["text"])
        elif event == "chat:expression" and isinstance(data, dict):
            expressions.append(data.get("emotion", ""))

    await sio.connect(SOCKETIO_URL, transports=["websocket"])
    print(f"\n[{label}]")
    print(f"  旅人 → {text}")
    task_id = str(uuid4())
    await sio.emit("chat:text", {
        "text": text, "message_id": str(uuid4()), "conversation_id": str(uuid4()),
        "task_id": task_id, "turn_id": task_id, "source": "text",
        "is_inspection": False, "is_acceptance": True,
    })
    await asyncio.sleep(PER_TURN_WAIT)
    await sio.disconnect()

    reply = "".join(reply_parts).strip()
    print(f"  Anima → {reply[:120]}{'...' if len(reply) > 120 else ''}")

    m = re.search(r"\[affinity:(\d+)\]", reply)
    result = {
        "reply": reply,
        "expressions": expressions,
        "marker_visible": m is not None,
        "marker_value": int(m.group(1)) if m else None,
    }

    # 自动判定（如果传了期望值）
    if expect_marker_visible is not None:
        if result["marker_visible"] == expect_marker_visible:
            print(f"  ✅ marker 可见性符合预期（visible={result['marker_visible']}）")
        else:
            print(f"  ❌ marker 可见性不符：期望 {expect_marker_visible}，实际 {result['marker_visible']}")

    return result


def check_action_description_violation(reply: str) -> bool:
    """检测是否含违规的动作描写括号。返回 True = 违规。"""
    # 以括号开头
    if reply.startswith(("（", "(")):
        return True
    # 文中含明显的动作括号
    return bool(re.search(
        r"[（(](?:从|抬|低|笑|摇|皱|叹|喝|拿|放|看|眨|伸|缩|转|歪|挑|抿|轻笑|微笑|苦笑|耸肩|点头|摇头|挥|拍|指|扶|靠|坐|站|走|跑)",
        reply,
    ))


async def run_socketio_tests() -> dict:
    """运行所有 Socket.IO 功能测试。"""
    print("\n" + "═" * 70)
    print("Socket.IO 功能验证（全新会话，无缓存）")
    print("═" * 70)

    results = {}

    # A. 普通弹幕 — marker 应该被剥除
    results["A_normal"] = await send_danmaku(
        "主播，今晚推荐什么特调？",
        "A. 普通弹幕（marker 应被剥除）",
        expect_marker_visible=False,
    )
    await asyncio.sleep(1.5)

    # B. debug-like prompt — runtime markers must remain hidden
    results["B_debug"] = await send_danmaku(
        "【debug】主播你对我印象怎么样",
        "B. debug 弹幕（marker 仍应隐藏）",
        expect_marker_visible=False,
    )
    await asyncio.sleep(1.5)

    # C. 无意义弹幕 — 不应有动作描写
    results["C_meaningless"] = await send_danmaku(
        "哦哦哦...",
        "C. 无意义弹幕（不应有动作描写）",
    )
    reply_c = results["C_meaningless"]["reply"]
    if check_action_description_violation(reply_c):
        print("  ❌ 检测到动作描写违规！")
    else:
        print("  ✅ 无动作描写违规")
    results["C_meaningless"]["violation"] = check_action_description_violation(reply_c)
    await asyncio.sleep(1.5)

    # D. inspection 探针 — 不应触发 LLM
    print("\n[D. inspection 探针（不应触发 LLM）]")
    sio = socketio.AsyncClient()
    got_sentence = False
    @sio.on("*")
    async def catch_d(event: str, data: Any) -> None:
        nonlocal got_sentence
        if event in {"chat:reply", "chat:sentence"} and isinstance(data, dict) and data.get("text"):
            got_sentence = True
    await sio.connect(SOCKETIO_URL, transports=["websocket"])
    probe_task = str(uuid4())
    await sio.emit("chat:text", {
        "text": "[inspection] ping", "message_id": str(uuid4()),
        "conversation_id": str(uuid4()), "task_id": probe_task, "turn_id": probe_task,
        "source": "text", "is_inspection": True, "is_acceptance": False,
    })
    await asyncio.sleep(8)
    await sio.disconnect()
    results["D_inspection"] = {"llm_triggered": got_sentence}
    if got_sentence:
        print("  ❌ 探针触发了 LLM（收到 sentence 事件）")
    else:
        print("  ✅ 探针被正确过滤，未触发 LLM")

    return results


# ── Playwright UI 截图捕获 ──────────────────────────────────────────


async def capture_ui_screenshots() -> list[str]:
    """用 playwright 捕获前端 UI 截图。"""
    from playwright.async_api import async_playwright

    screenshots = []
    interaction_passed = False
    print("\n" + "═" * 70)
    print("Playwright UI 截图捕获（全新浏览器，无缓存）")
    print("═" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # 1. 首页加载
        print("\n[1] 捕获首页...")
        await page.goto(BACKEND_HTTP, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        shot1 = str(SCREENSHOTS_DIR / "01_home.png")
        await page.screenshot(path=shot1, full_page=True)
        screenshots.append(shot1)
        print(f"    → {shot1}")

        start_button = page.get_by_role("button", name="开始对话")
        if await start_button.count():
            await start_button.click()
            await page.wait_for_timeout(300)

        # 2. 找到输入框，发一条弹幕
        print("\n[2] 发送弹幕「主播好」...")
        try:
            # 尝试多种选择器找输入框
            textarea = await page.query_selector("textarea")
            if textarea:
                await textarea.fill("主播好，今天有什么好玩的")
                await page.wait_for_timeout(500)

                # 截图：输入后
                shot2 = str(SCREENSHOTS_DIR / "02_after_input.png")
                await page.screenshot(path=shot2, full_page=True)
                screenshots.append(shot2)
                print(f"    → {shot2}")

                # 找发送按钮（在 input-bar 内的 button）
                send_buttons = page.locator('[data-testid="chat-input-bar"] button')
                if await send_buttons.count():
                    await send_buttons.last.click()
                    print("    已点击发送按钮")
                else:
                    # 用回车发送
                    await textarea.press("Enter")
                    print("    已按回车发送")

                message_list = page.locator('[data-testid="message-list"]')
                await message_list.get_by_text("主播好，今天有什么好玩的", exact=True).wait_for(
                    timeout=5000
                )
                await page.wait_for_function(
                    """() => document.querySelectorAll(
                        '[data-testid="message-list"] > div.flex'
                    ).length >= 2""",
                    timeout=30000,
                )
                interaction_passed = True

                # 截图：收到回复后
                shot3 = str(SCREENSHOTS_DIR / "03_after_reply.png")
                await page.screenshot(path=shot3, full_page=True)
                screenshots.append(shot3)
                print(f"    → {shot3}")
            else:
                print("    ⚠️  没找到 textarea，跳过交互测试")
                shot2 = str(SCREENSHOTS_DIR / "02_no_textarea.png")
                await page.screenshot(path=shot2, full_page=True)
                screenshots.append(shot2)
        except Exception as exc:
            print(f"    ⚠️  交互异常: {exc!r}")
            shot_err = str(SCREENSHOTS_DIR / "error_state.png")
            await page.screenshot(path=shot_err, full_page=True)
            screenshots.append(shot_err)

        # 4. 捕获页面文本内容（验证消息真的渲染了）
        print("\n[3] 捕获页面文本内容...")
        body_text = await page.inner_text("body")
        text_file = SCREENSHOTS_DIR / "page_text.txt"
        text_file.write_text(body_text, encoding="utf-8")
        print(f"    → {text_file} ({len(body_text)} chars)")

        await browser.close()

    if not interaction_passed:
        raise RuntimeError("UI chat interaction did not render a complete user/assistant exchange")
    return screenshots


# ── 主流程 ──────────────────────────────────────────────────────────


async def main() -> int:
    print("═" * 70)
    print("Anima QA 测试 — 页面捕获 + 功能验证")
    print(f"前端: {BACKEND_HTTP}")
    print(f"Socket.IO: {SOCKETIO_URL}")
    print(f"截图目录: {SCREENSHOTS_DIR.absolute()}")
    print("═" * 70)

    # Step 1: UI 截图
    try:
        screenshots = await capture_ui_screenshots()
    except Exception as exc:
        print(f"\n[UI 截图失败] {exc!r}")
        screenshots = []

    # Step 2: Socket.IO 功能测试
    sio_results = await run_socketio_tests()

    # Step 3: 总结
    print("\n" + "═" * 70)
    print("测试总结")
    print("═" * 70)
    print(f"\n📸 UI 截图: {len(screenshots)} 张")
    for s in screenshots:
        print(f"   - {s}")

    print("\n🔌 Socket.IO 功能验证:")
    a = sio_results.get("A_normal", {})
    b = sio_results.get("B_debug", {})
    c = sio_results.get("C_meaningless", {})
    d = sio_results.get("D_inspection", {})

    a_pass = bool(a.get("reply")) and a.get("marker_visible") is False
    b_pass = bool(b.get("reply")) and b.get("marker_visible") is False
    c_pass = bool(c.get("reply")) and c.get("violation") is False
    d_pass = d.get("llm_triggered") is False

    print(f"   {'✅' if a_pass else '❌'} A. 普通弹幕 marker 剥除: marker_visible={a.get('marker_visible')}")
    print(f"   {'✅' if b_pass else '❌'} B. debug 弹幕 marker 隐藏: marker_visible={b.get('marker_visible')}")
    print(f"   {'✅' if c_pass else '❌'} C. 无意义弹幕无动作描写: violation={c.get('violation')}")
    print(f"   {'✅' if d_pass else '❌'} D. inspection 探针过滤: llm_triggered={d.get('llm_triggered')}")

    all_pass = len(screenshots) >= 3 and all([a_pass, b_pass, c_pass, d_pass])
    print(f"\n{'✅ 全部通过' if all_pass else '❌ 有失败项'}")
    print("═" * 70)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
