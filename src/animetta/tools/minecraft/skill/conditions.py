"""Precondition expression parsing for Minecraft skills."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

_COND_PATTERN = re.compile(r"^\s*(\w+)\s*(>=|<=|!=|==|>|<)\s*(.+?)\s*$")


def check_preconditions(conditions: list[str], context: dict[str, Any] | None = None) -> bool:
    """Check whether all preconditions are satisfied against context."""
    if not conditions:
        return True

    ctx = context or {}
    for cond in conditions:
        if not _check_single(cond, ctx):
            logger.debug(f"[SkillLibrary] Precondition failed: {cond}")
            return False

    return True


def _check_single(cond: str, ctx: dict[str, Any]) -> bool:  # noqa: C901
    """Evaluate a single condition string against context."""
    match = _COND_PATTERN.match(cond)
    if match:
        key, op, raw_value = match.group(1), match.group(2), match.group(3)

        if key.startswith("has_"):
            item = key[4:]
            inventory = ctx.get("inventory", {})
            actual_count = inventory.get(item, 0)
            try:
                expected_count = float(raw_value)
                actual_num = float(actual_count)
            except (ValueError, TypeError):
                return False

            if op == ">":
                return actual_num > expected_count
            if op == "<":
                return actual_num < expected_count
            if op == ">=":
                return actual_num >= expected_count
            if op == "<=":
                return actual_num <= expected_count
            if op == "==":
                return actual_num == expected_count
            if op == "!=":
                return actual_num != expected_count
            return False

        actual: Any = ctx.get(key)
        try:
            expected_num = float(raw_value)
            if actual is None:
                return False
            actual_num = float(actual)
        except (ValueError, TypeError):
            expected_str: str = raw_value.strip().strip("'\"")
            if actual is None:
                return False
            if op == "==":
                return actual == expected_str
            if op == "!=":
                return actual != expected_str
            return False

        if op == ">":
            return actual_num > expected_num
        if op == "<":
            return actual_num < expected_num
        if op == ">=":
            return actual_num >= expected_num
        if op == "<=":
            return actual_num <= expected_num
        if op == "==":
            return actual_num == expected_num
        if op == "!=":
            return actual_num != expected_num
        return False

    cond = cond.strip()
    if cond.startswith("has_"):
        item = cond[4:]
        inventory = ctx.get("inventory", {})
        count = inventory.get(item, 0)
        return count > 0

    return bool(ctx.get(cond, False))
