"""End-to-end test: text input → LLM → mc tool call → bot execution."""

import asyncio
from typing import Any

import socketio

SERVER = "http://localhost:12394"

events_log: list[tuple[str, Any]] = []


def log(evt: str, data: Any) -> None:
    msg = f"[EVENT] {evt}: {str(data)[:200]}"
    print(msg)
    events_log.append((evt, data))


async def main() -> None:
    sio = socketio.AsyncClient()

    @sio.event
    async def connect():
        print("[CONNECTED]")

    @sio.on("minecraft:status")
    async def on_mc_status(data: Any) -> None:
        log("minecraft:status", data)

    @sio.on("minecraft:bot_state")
    async def on_bot_state(data: Any) -> None:
        log("minecraft:bot_state", data)

    @sio.on("minecraft:command_result")
    async def on_cmd(data: Any) -> None:
        log("minecraft:command_result", data)

    @sio.on("minecraft:viewer_status")
    async def on_viewer(data: Any) -> None:
        log("minecraft:viewer_status", data)

    @sio.on("chat:sentence")
    async def on_sentence(data: Any) -> None:
        log("chat:sentence", data)

    @sio.on("chat:control")
    async def on_control(data: Any) -> None:
        log("chat:control", data)

    @sio.on("chat:expression")
    async def on_expression(data: Any) -> None:
        log("chat:expression", data)

    @sio.on("chat:transcript")
    async def on_transcript(data: Any) -> None:
        log("chat:transcript", data)

    print(f"[1] Connecting to {SERVER} ...")
    await sio.connect(SERVER, transports=["websocket"])
    await asyncio.sleep(1)

    print("\n[2] Emitting minecraft:start ...")
    await sio.emit("minecraft:start", {})
    print("    waiting for bot to login (up to 30s) ...")

    # Wait for minecraft:status connected=true
    bot_ok = False
    for _ in range(30):
        await asyncio.sleep(1)
        for evt, data in events_log:
            if evt == "minecraft:status" and isinstance(data, dict) and data.get("connected"):
                bot_ok = True
                break
        if bot_ok:
            break

    if not bot_ok:
        print("[FAIL] Bot did not connect within 30s")
        print("\nEvents seen:", [e for e, _ in events_log])
        await sio.disconnect()
        return

    print("\n[3] Bot connected! Sending text instruction ...")
    # Send a text that should trigger an mc_* tool call
    await sio.emit(
        "chat:text", {"text": "帮我看看周围有什么方块，然后挖1个橡木", "from_name": "测试员"}
    )

    print("    waiting for LLM response + tool call (up to 60s) ...")
    # Collect events for 60s
    await asyncio.sleep(60)

    print("\n[4] Events summary:")
    seen = set(e for e, _ in events_log)
    print(f"    event types: {seen}")

    text_chunks = [
        d.get("text", "") for e, d in events_log if e == "chat:sentence" and isinstance(d, dict)
    ]
    full_text = "".join(text_chunks)
    print(f"\n[LLM 文本回复]:\n{full_text[:1500]}")

    cmd_results = [d for e, d in events_log if e == "minecraft:command_result"]
    print(f"\n[bot 命令结果] ({len(cmd_results)} 条):")
    for r in cmd_results[:5]:
        print(f"  {str(r)[:200]}")

    await sio.disconnect()
    print("\n[DONE]")


asyncio.run(main())
