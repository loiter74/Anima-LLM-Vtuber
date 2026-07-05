"""Anima v0.1 roleplay evaluation runner.

Runs deterministic checks against dialogue fixtures without requiring live API access.
Optional live eval gated by DEEPSEEK_API_KEY.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Add tests dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.test_anima_roleplay_eval import (
    ANIMA_CASES,
    EvalResult,
    evaluate_all,
    evaluate_response,
)


def run_deterministic_check(sample_responses: dict[str, str]) -> list[EvalResult]:
    """Run deterministic evaluation against sample responses.

    No API calls. Uses provided response texts.

    Args:
        sample_responses: dict mapping case.id -> response text.

    Returns:
        List of EvalResult.
    """
    return evaluate_all(sample_responses)


async def run_live_eval(
    model: str = "deepseek-v4-flash",
    thinking: str = "disabled",
) -> list[EvalResult]:
    """Run live evaluation against DeepSeek API.

    Requires DEEPSEEK_API_KEY environment variable.

    Args:
        model: DeepSeek model to test.
        thinking: "enabled" or "disabled".

    Returns:
        List of EvalResult with latency metadata.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set — skipping live eval")

    from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig
    from animetta.services.llm.openai_llm import OpenAILLM

    cfg = DeepSeekLLMConfig(api_key=api_key, model=model, thinking=thinking)
    llm = OpenAILLM.from_config(cfg)

    # Build system prompt from persona
    from animetta.config.persona.base import PersonaConfig
    persona = PersonaConfig.load("alice")  # Use configured persona
    llm.set_system_prompt(persona.build_system_prompt())

    results = []
    for case in ANIMA_CASES:
        t_start = time.perf_counter()
        try:
            response = await llm.chat(case.user_input)
        except Exception as e:
            response = f"ERROR: {e}"
        latency_ms = (time.perf_counter() - t_start) * 1000

        result = evaluate_response(case, response)
        result.details += f" | latency={latency_ms:.0f}ms | model={model} | thinking={thinking}"
        results.append(result)

    return results


def format_report(results: list[EvalResult], title: str = "Anima v0.1 Eval") -> str:
    """Format evaluation results as a human-readable report."""
    lines = [f"# {title}", ""]
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines.append(f"**Pass rate:** {passed}/{total} ({100*passed/total:.0f}%)")
    lines.append("")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"- [{status}] {r.case_id}: {r.details}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick deterministic check with sample responses
    sample = {
        "lag_complaint": "虫子又在啃线了。召唤者 X 的网络就这样。",
        "skill_issue": "那你来试试？我赌你连第一晚都活不过。",
        "wrong_info": "……数据不支持你的结论。让我重新检查一下。",
        "identity_question": "久遠寺有珠。最後的魔女。",
        "advice_request": "我不是你的母亲。请自己决定。",
        "presence_check": "……嗯。",
        "ai_framing": "你的措辞有问题。我是有珠，不是什么AI。",
    }
    results = run_deterministic_check(sample)
    print(format_report(results))

    # Optional live eval
    if os.getenv("DEEPSEEK_API_KEY"):
        print("\n--- Live eval (Flash, thinking=disabled) ---")
        live_results = asyncio.run(run_live_eval("deepseek-v4-flash", "disabled"))
        print(format_report(live_results, "Live Eval: Flash"))
