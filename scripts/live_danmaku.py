#!/usr/bin/env python
"""B站直播间弹幕实时采集 - 自动重连版"""

import asyncio
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from bilibili_api import live

ROOM_ID = 1931022824
OUTPUT_DIR = Path(__file__).parent / "danmaku_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ts_start = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILE = OUTPUT_DIR / f"danmaku_{ROOM_ID}_{ts_start}.csv"
JSONL_FILE = OUTPUT_DIR / f"danmaku_{ROOM_ID}_{ts_start}.jsonl"
LOG_FILE = OUTPUT_DIR / f"collector_{ROOM_ID}.log"

total_count = 0
start_time = time.time()
# Long-lived file handle for the whole run; closed in the __main__ finally.
csv_fp = open(CSV_FILE, "a", encoding="utf-8-sig", newline="")  # noqa: SIM115
csv_w = csv.writer(csv_fp)
csv_w.writerow(["timestamp", "datetime", "uid", "username", "message", "msg_type"])


def log(msg: object) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_msg(uid: object, username: object, text: object, msg_type: str) -> None:
    global total_count
    now = datetime.now()
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
    csv_w.writerow([now.timestamp(), ts_str, uid, username, text, msg_type])
    csv_fp.flush()
    with open(JSONL_FILE, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": now.timestamp(),
                    "time": ts_str,
                    "uid": uid,
                    "user": username,
                    "text": text,
                    "type": msg_type,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    total_count += 1
    log(f"[{msg_type}] {username}: {text}")


def make_room() -> live.LiveDanmaku:
    room = live.LiveDanmaku(ROOM_ID)

    @room.on("DANMU_MSG")
    async def _danmu(event: dict[str, list]) -> None:
        try:
            info = event.get("info", [])
            text = info[1] if len(info) > 1 else ""
            ui = info[2] if len(info) > 2 else []
            uid = str(ui[0].get("uid", "")) if ui else ""
            uname = ui[0].get("uname", "") if ui else ""
            save_msg(uid, uname, text, "danmaku")
        except Exception as e:
            log(f"ERR: {e}")

    @room.on("SEND_GIFT")
    async def _gift(event: dict[str, dict]) -> None:
        try:
            d = event.get("data", {})
            save_msg(
                str(d.get("uid", "")),
                d.get("uname", ""),
                f"[礼物] {d.get('giftName', '?')} x{d.get('num', 1)}",
                "gift",
            )
        except Exception as e:
            log(f"ERR: {e}")

    @room.on("SUPER_CHAT_MESSAGE")
    async def _sc(event: dict[str, dict]) -> None:
        try:
            d = event.get("data", {})
            save_msg(
                str(d.get("uid", "")),
                d.get("user", {}).get("uname", ""),
                f"[SC¥{d.get('price', '?')}] {d.get('message', '')}",
                "sc",
            )
        except Exception as e:
            log(f"ERR: {e}")

    return room


async def run_forever() -> None:
    attempt = 0
    while True:
        attempt += 1
        log(f"连接直播间 {ROOM_ID} (第{attempt}次)")
        room = make_room()
        try:
            await room.connect()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log(f"断开: {e}")
        # 重连
        wait = min(3 * attempt, 30)
        log(f"{wait}秒后重连 (已采集{total_count}条)")
        await asyncio.sleep(wait)


if __name__ == "__main__":
    log(f"=== 采集启动 | 房间:{ROOM_ID} ===")
    log(f"CSV: {CSV_FILE}")
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass
    finally:
        csv_fp.close()
        elapsed = time.time() - start_time
        log(f"=== 结束 | 总弹幕:{total_count} | 时长:{elapsed:.0f}秒 ===")
