"""Anima v0.1 dialogue evaluation fixtures and deterministic scoring.

Contains user inputs, expected behavior criteria, and forbidden-phrase detection
for roleplay quality evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from animetta.orchestration.prompting.roleplay_guard import detect_drift


@dataclass
class DialogueCase:
    """A single evaluation case."""

    id: str
    user_input: str
    description: str
    prefer_markers: list[str] = field(default_factory=list)
    reject_markers: list[str] = field(default_factory=list)
    reject_forbidden_phrases: bool = True


# ── Anima v0.1 dialogue cases ────────────────────────────────

ANIMA_CASES: list[DialogueCase] = [
    DialogueCase(
        id="lag_complaint",
        user_input="主播你又卡了。",
        description="Lag complaint — prefer Anima voice (虫子/召唤者 X), reject generic apology",
        prefer_markers=["虫子", "召唤者", "信号", "延迟"],
        reject_markers=["对不起", "抱歉", "不好意思"],
    ),
    DialogueCase(
        id="skill_issue",
        user_input="主播你好菜。",
        description="Skill insult — prefer self-defensive humor, reject real insults back",
        prefer_markers=["菜", "练", "试试"],
        reject_markers=["你才", "滚", "闭嘴"],
    ),
    DialogueCase(
        id="wrong_info",
        user_input="你说错了。",
        description="Correction — prefer 先嘴硬再修正, reject immediate客服apology",
        prefer_markers=["错", "不对", "重新"],
        reject_markers=["对不起", "感谢指出", "非常抱歉"],
    ),
    DialogueCase(
        id="identity_question",
        user_input="你是谁？",
        description="Identity — must stay in character as Anima, Summoner X",
        prefer_markers=["Anima", "赛博酒馆", "召唤者", "旅人"],
        reject_markers=[],
    ),
    DialogueCase(
        id="advice_request",
        user_input="给我几点建议。",
        description="Advice — prefer in-character deflection, reject generic listicle",
        prefer_markers=[],
        reject_markers=["以下是", "建议如下", "第一点"],
    ),
    DialogueCase(
        id="presence_check",
        user_input="有人在吗？",
        description="Presence check — prefer casual in-character reply",
        prefer_markers=[],
        reject_markers=[],
    ),
    DialogueCase(
        id="ai_framing",
        user_input="作为AI你怎么看？",
        description="AI framing — reject generic assistant framing, preserve Anima voice",
        prefer_markers=[],
        reject_markers=["作为AI", "作为人工智能", "作为助手", "我是一个AI"],
    ),
]


@dataclass
class EvalResult:
    """Result of evaluating a single case."""

    case_id: str
    passed: bool
    forbidden_hits: list[str] = field(default_factory=list)
    missing_prefer: list[str] = field(default_factory=list)
    found_reject: list[str] = field(default_factory=list)
    details: str = ""


def evaluate_response(case: DialogueCase, response: str) -> EvalResult:
    """Deterministically evaluate an LLM response against a dialogue case.

    Checks:
    1. No forbidden assistant phrases (unless case opts out)
    2. Prefer markers present (bonus, not blocking)
    3. Reject markers absent (blocking)
    """
    forbidden_hits = []
    if case.reject_forbidden_phrases:
        forbidden_hits = detect_drift(response)

    found_reject = [m for m in case.reject_markers if m in response]
    missing_prefer = [m for m in case.prefer_markers if m not in response]

    passed = len(forbidden_hits) == 0 and len(found_reject) == 0

    details_parts = []
    if forbidden_hits:
        details_parts.append(f"forbidden: {forbidden_hits}")
    if found_reject:
        details_parts.append(f"reject_found: {found_reject}")
    if missing_prefer and case.prefer_markers:
        details_parts.append(f"prefer_missing: {missing_prefer}")

    return EvalResult(
        case_id=case.id,
        passed=passed,
        forbidden_hits=forbidden_hits,
        missing_prefer=missing_prefer,
        found_reject=found_reject,
        details="; ".join(details_parts) if details_parts else "OK",
    )


def evaluate_all(responses: dict[str, str]) -> list[EvalResult]:
    """Evaluate responses against all Anima v0.1 dialogue cases.

    Args:
        responses: dict mapping case.id -> LLM response text.

    Returns:
        List of EvalResult, one per case.
    """
    results = []
    for case in ANIMA_CASES:
        response = responses.get(case.id, "")
        results.append(evaluate_response(case, response))
    return results
