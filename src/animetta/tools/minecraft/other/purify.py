"""历史净化（mc-evo-purity T3/T4）。

`self_evolution` 的 Voyager 循环曾在 verifier 前用 `/give` 补全 inventory，使「真实
环境下会失败的 code-body skill」被误标 ``validated=True`` 入库（假技能）。本模块对库中
已存 ``validated=True`` 的 code-body skill 跑「**无 give + 正常采集**」复验，恢复
「``validated`` skill = 可靠可复用」的信任契约。

复验流程（每个 skill）：
  ① 强制 ``MC_EVO_ALLOW_GIVE=False``（env + self_evolution 模块属性）
  ② 重放其 code-body（``bridge.send_command("eval_code", ...)``）—— 正常采集环境，无 give
  ③ 真实 ``verify()`` 判定
  ④ passed  → 保留 ``validated=True``
     failed → 降级 ``validated=False``；连续失败（fail_count 达阈值）直接 ``remove_skill`` 淘汰
  ⑤ 异常/断连 → 跳过、记日志、下次复验，不中断整体

以 ``python -m animetta.tools.minecraft.other.purify`` 运行，**不阻塞主循环**；
产出净化报告（保留/降级/淘汰/跳过计数）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING, Any

from loguru import logger

from animetta.tools.minecraft.skill.verifier import verify

if TYPE_CHECKING:
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.skill.catalog import SkillLibrary

# 连续失败淘汰阈值：跨多次 purify 累积 fail_count 达此值 → 直接 remove_skill。
# （SkillLibrary.cleanup() 只清 is_learned 的低质技能；voyager code-body skill 默认
#  is_learned=False，故由本阈值直接淘汰，cleanup() 另作通用清扫。）
_EVICT_FAIL_THRESHOLD = 3


async def purify_validated_skills(
    bridge: MinecraftBridge,
    lib: SkillLibrary,
    *,
    llm: Any = None,
    fail_threshold: int = _EVICT_FAIL_THRESHOLD,
    get_state_fn: Any = None,
) -> dict[str, Any]:
    """复验库中 ``validated=True`` 的 code-body skill。

    Args:
        bridge: 已连接的 MinecraftBridge（用于重放 eval_code）。
        lib: SkillLibrary（复验对象 + 降级/淘汰写入）。
        llm: 可选 LLM（模糊任务的 verify 闸2；inventory 型后置条件无需）。
        fail_threshold: 连续失败淘汰阈值（fail_count ≥ 此值 → remove_skill）。
        get_state_fn: ``bridge -> (state, inv)`` 快照函数，默认复用
            ``self_evolution.get_state``；测试可注入 mock。

    Returns:
        净化报告 ``{total, kept, demoted, evicted, skipped, details}``。
    """
    # ① 强制无 give：env + self_evolution 模块属性（运行时全局动态查找生效）。
    os.environ["MC_EVO_ALLOW_GIVE"] = "0"
    try:
        from animetta.tools.minecraft.other import self_evolution

        self_evolution.MC_EVO_ALLOW_GIVE = False
    except Exception as e:  # pragma: no cover — 防御性：self_evolution 不可用也能跑
        logger.warning(f"[purify] 无法强制 self_evolution.MC_EVO_ALLOW_GIVE=False: {e}")

    if get_state_fn is None:
        from animetta.tools.minecraft.other.self_evolution import get_state as get_state_fn

    report: dict[str, Any] = {
        "total": 0,
        "kept": 0,
        "demoted": 0,
        "evicted": 0,
        "skipped": 0,
        "details": [],
    }

    # 仅复验 code-body skill（voyager 产出、可能被 give 污染）；predefined step-based
    # 种子技能不在范围内（trusted bootstrap，不重放、不降级）。
    candidates = [
        s
        for s in await lib.get_all_skills()
        if s.validated and s.body.get("type") == "code" and s.body.get("code")
    ]
    report["total"] = len(candidates)
    logger.info(
        f"[purify] 待复验 validated code-body skill: {len(candidates)} 个（give 已强制关闭）"
    )

    for skill in candidates:
        # ⑤ 断连：bridge 未运行 → 跳过（不中断）
        if not getattr(bridge, "is_running", True):
            logger.warning(f"[purify] bridge 未运行，跳过 skill {skill.id}")
            report["skipped"] += 1
            report["details"].append(
                {"id": skill.id, "outcome": "skipped", "reason": "bridge not running"}
            )
            continue

        try:
            code = skill.body.get("code", "")
            res = await bridge.send_command(
                "eval_code", {"code": code, "timeout": 180_000}, timeout=200.0
            )
            # 重放本身失败（代码跑不通）→ 视为假技能，降级（非断连）
            if not (isinstance(res, dict) and res.get("status") == "success"):
                err = str(res.get("result", "replay error") if isinstance(res, dict) else res)[:160]
                logger.warning(f"[purify] skill {skill.id} 重放失败 → 降级: {err}")
                skill.validated = False
                await lib.save_skill(skill)
                await lib.update_failure(skill.id)
                if skill.fail_count >= fail_threshold:
                    await lib.remove_skill(skill.id)
                    report["evicted"] += 1
                    report["details"].append(
                        {
                            "id": skill.id,
                            "outcome": "evicted",
                            "reason": f"replay fail x{skill.fail_count}",
                        }
                    )
                else:
                    report["demoted"] += 1
                    report["details"].append(
                        {"id": skill.id, "outcome": "demoted", "reason": f"replay fail: {err}"}
                    )
                continue

            # ②③ 正常采集快照 + 真实 verify
            state, inv = await get_state_fn(bridge)
            snapshot = {
                "inventory": inv,
                "position": state.get("position"),
                "health": state.get("health"),
                "food": state.get("food"),
            }
            vr = await verify(skill, skill.postconditions, snapshot, llm=llm)

            if vr.passed:
                # ④ passed → 保留
                logger.success(f"[purify] skill {skill.id} 复验通过 (gate={vr.gate}) → 保留")
                await lib.update_success(skill.id)
                report["kept"] += 1
                report["details"].append({"id": skill.id, "outcome": "kept", "gate": vr.gate})
            else:
                # ④ failed → 降级；连续失败达阈值 → 淘汰
                logger.warning(
                    f"[purify] skill {skill.id} 复验失败 (gate={vr.gate}) → 降级: {vr.reason}"
                )
                skill.validated = False
                await lib.save_skill(skill)
                await lib.update_failure(skill.id)
                if skill.fail_count >= fail_threshold:
                    await lib.remove_skill(skill.id)
                    report["evicted"] += 1
                    report["details"].append(
                        {
                            "id": skill.id,
                            "outcome": "evicted",
                            "reason": f"verify fail x{skill.fail_count}",
                        }
                    )
                else:
                    report["demoted"] += 1
                    report["details"].append(
                        {
                            "id": skill.id,
                            "outcome": "demoted",
                            "reason": f"verify fail: {vr.reason[:120]}",
                        }
                    )
        except Exception as e:
            # ⑤ 异常 → 跳过、记日志，不中断整体复验
            logger.warning(f"[purify] skill {skill.id} 复验异常，跳过: {e}")
            report["skipped"] += 1
            report["details"].append(
                {"id": skill.id, "outcome": "skipped", "reason": f"exception: {e}"}
            )

    # 通用清扫：cleanup() 清低质 is_learned 技能（与 code-body 阈值淘汰互补）。
    try:
        cleanup_removed = await lib.cleanup()
        report["evicted"] += cleanup_removed
    except Exception as e:  # pragma: no cover
        logger.warning(f"[purify] SkillLibrary.cleanup() 异常: {e}")

    logger.info(
        f"[purify] DONE | total={report['total']} kept={report['kept']} "
        f"demoted={report['demoted']} evicted={report['evicted']} skipped={report['skipped']}"
    )
    return report


async def _run_cli() -> int:
    """命令行入口：起 bridge + lib，跑一次性净化，打印报告。"""
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.core.config import (
        MinecraftBotConfig,
        MinecraftConfig,
        MinecraftMode,
        MinecraftViewerConfig,
    )
    from animetta.tools.minecraft.other.self_evolution import DeepSeekLLM
    from animetta.tools.minecraft.skill.catalog import SkillLibrary
    from animetta.tools.minecraft.skill.code_seeds import get_code_seeds
    from animetta.tools.minecraft.skill.predefined import get_predefined_skills

    logger.info("[purify] 启动历史净化（MC_EVO_ALLOW_GIVE 强制 False）")
    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    if not await bridge.start():
        logger.error("[purify] bridge start failed")
        return 2
    await asyncio.sleep(10)

    lib = SkillLibrary()
    for s in get_predefined_skills() + get_code_seeds():
        await lib.save_skill(s)

    llm = DeepSeekLLM()
    report = await purify_validated_skills(bridge, lib, llm=llm)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    await asyncio.sleep(5)
    await bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_cli()))
