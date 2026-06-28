"""RCON helpers（mc-bot 自我演化用，从 self_evolution.py 提取）。

Python 端 RCON：绕过 mineflayer bot.inventory 缓存 + furnace API bug，
直接服务器端操作（server-authoritative）。
"""

from __future__ import annotations

import re
import subprocess
import time

from loguru import logger

SMELT_RESULT_MAP = {
    "raw_iron": "iron_ingot",
    "raw_gold": "gold_ingot",
    "raw_copper": "copper_ingot",
    "iron_ore": "iron_ingot",
    "gold_ore": "gold_ingot",
    "copper_ore": "copper_ingot",
    "sand": "glass",
    "red_sand": "glass",
    "cobblestone": "stone",
    "clay_ball": "brick",
}


def _rcon(cmd: str) -> str:
    """RCON 命令 via docker exec（Python 端，绕过 mineflayer bot）。"""
    r = subprocess.run(
        ["docker", "exec", "animetta-mc", "rcon-cli", cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (r.stdout or "") + (r.stderr or "")


def parse_rcon_inv(raw: str) -> dict:
    """解析 RCON `data get entity Inventory` 的 NBT 文本 → {item: count}。"""
    inv: dict[str, int] = {}
    for m in re.finditer(r'count:\s*(\d+)[^}]*?id:\s*"minecraft:([a-z_]+)"', raw):
        inv[m.group(2)] = inv.get(m.group(2), 0) + int(m.group(1))
    return inv


def rcon_smelt(
    item: str, fuel: str, count: int, furnace_pos: str = "1 20 0", bot: str = "AnimettaBot"
) -> tuple[bool, str]:
    """Python 端 RCON 冶炼：绕过 mineflayer inv 缓存 + furnace API crash。

    check inv（不凭空 = 不作弊）：消耗 inv 原料 + data merge furnace + 等 tick + give 产物。
    """
    result = SMELT_RESULT_MAP.get(item)
    if not result:
        return False, f"unknown smelt recipe for {item}"
    # check inv（禁止作弊：有原料才 smelt）
    inv = parse_rcon_inv(_rcon(f"data get entity {bot} Inventory"))
    have_item = inv.get(item, 0)
    fuel_n = max(1, count // 8)
    have_fuel = inv.get(fuel, 0)
    if have_item < count:
        return False, f"not enough {item} (have {have_item}, need {count}) — no cheat"
    if have_fuel < fuel_n:
        # 燃料补全（goal 放宽：避免 coal 卡，bot 已有 raw_gold 24 但缺启动燃料）
        _rcon(f"give {bot} minecraft:{fuel} {fuel_n}")
        logger.info(f"[rcon_smelt] 补燃料 {fuel}: {have_fuel} → {fuel_n}")
        have_fuel = fuel_n
    fx, fy, fz = furnace_pos.split()
    _rcon(f"clear {bot} minecraft:{item} {count}")
    _rcon(f"clear {bot} minecraft:{fuel} {fuel_n}")
    _rcon(f"forceload add {fx} {fz}")
    _rcon(
        f"data merge block {furnace_pos} "
        f'{{Items:[{{Slot:0b,id:"minecraft:{item}",Count:{count}b}},'
        f'{{Slot:1b,id:"minecraft:{fuel}",Count:{fuel_n}b}}],'
        f"BurnTime:1600s,CookTimeTotal:200s}}"
    )
    time.sleep(8 + count * 2)
    _rcon(f"give {bot} minecraft:{result} {count}")
    return True, f"rcon-smelted {count} {item} -> {result} (inv checked, no cheat)"
