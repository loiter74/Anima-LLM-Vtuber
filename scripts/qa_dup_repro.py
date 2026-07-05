"""复现重复消息 bug — playwright 真实浏览器，数实际渲染的 AI 气泡数。"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://localhost"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # 收集控制台日志
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))

        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 找输入框发消息
        textarea = await page.query_selector("textarea")
        if not textarea:
            print("[FAIL] 没找到 textarea")
            return

        await textarea.fill("测试重复消息")
        await page.wait_for_timeout(300)

        # 发送
        send_btn = await page.query_selector('[data-testid="chat-input-bar"] button')
        if send_btn:
            await send_btn.click()
        else:
            await textarea.press("Enter")

        print("[1] 已发送「测试重复消息」，等待回复...")
        await page.wait_for_timeout(20000)

        # 截图
        await page.screenshot(path="qa_screenshots/dup_repro.png", full_page=True)

        # 数 AI 气泡 — MessageBubble 用 role 区分，AI 有头像「安」
        # 直接查所有 message bubble 的文本
        messages = await page.query_selector_all(".flex.items-end.gap-2")
        print(f"\n[2] 渲染的消息气泡总数: {len(messages)}")

        ai_replies = []
        user_msgs = []
        for i, m in enumerate(messages):
            text = await m.inner_text()
            # AI 气泡含「安」头像
            has_avatar = await m.query_selector("div:text('安')")
            if has_avatar:
                ai_replies.append(text.strip())
            else:
                user_msgs.append(text.strip())

        print(f"  用户消息: {len(user_msgs)}")
        for i, t in enumerate(user_msgs[-3:]):
            print(f"    [{i}] {t[:60]}")

        print(f"  AI 回复: {len(ai_replies)}")
        for i, t in enumerate(ai_replies[-5:]):
            print(f"    [{i}] {t[:80]}")

        # 检查最后几条 AI 回复是否有重复
        if len(ai_replies) >= 2:
            last = ai_replies[-1]
            second_last = ai_replies[-2]
            if last == second_last:
                print(f"\n[❌ 确认重复] 最后两条 AI 回复完全相同:")
                print(f"  倒数第2: {second_last[:100]}")
                print(f"  倒数第1: {last[:100]}")
            else:
                print(f"\n[ℹ️  最后两条不同] 可能是历史消息")

        # 打印 socket 监听器相关日志
        print(f"\n[3] 控制台日志（最后 20 条）:")
        for log in logs[-20:]:
            print(f"  {log}")

        await browser.close()


asyncio.run(main())
