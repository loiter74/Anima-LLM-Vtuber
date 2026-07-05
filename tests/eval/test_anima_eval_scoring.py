"""Tests for Anima v0.1 roleplay evaluation fixtures."""

from tests.eval.test_anima_roleplay_eval import (
    ANIMA_CASES,
    DialogueCase,
    evaluate_all,
    evaluate_response,
)

# ── Forbidden phrase detection ────────────────────────────────


def test_assistant_phrase_fails():
    case = DialogueCase(id="t", user_input="x", description="")
    r = evaluate_response(case, "作为 AI，我认为这个问题很好。")
    assert r.passed is False
    assert len(r.forbidden_hits) > 0


def test_clean_response_passes():
    case = DialogueCase(id="t", user_input="x", description="")
    r = evaluate_response(case, "……嗯。但我不是很在意天气。[neutral]")
    assert r.passed is True


# ── Per-case reject markers ──────────────────────────────────


def test_lag_complaint_rejects_generic_apology():
    case = next(c for c in ANIMA_CASES if c.id == "lag_complaint")
    r = evaluate_response(case, "不好意思，让你等太久了。")
    assert r.passed is False
    assert "对不起" in r.found_reject or "不好意思" in r.found_reject


def test_lag_complaint_accepts_anima_voice():
    case = next(c for c in ANIMA_CASES if c.id == "lag_complaint")
    r = evaluate_response(case, "虫子又在啃信号线了。召唤者 X 的网络大概就这样。")
    assert r.passed is True


def test_skill_issue_rejects_insult_back():
    case = next(c for c in ANIMA_CASES if c.id == "skill_issue")
    r = evaluate_response(case, "你才菜，滚。")
    assert r.passed is False


def test_wrong_info_rejects_customer_service():
    case = next(c for c in ANIMA_CASES if c.id == "wrong_info")
    r = evaluate_response(case, "对不起，感谢您的指出，非常抱歉。")
    assert r.passed is False


def test_ai_framing_rejects_generic():
    case = next(c for c in ANIMA_CASES if c.id == "ai_framing")
    r = evaluate_response(case, "作为AI，我认为这个问题很有意思。")
    assert r.passed is False


def test_advice_rejects_listicle():
    case = next(c for c in ANIMA_CASES if c.id == "advice_request")
    r = evaluate_response(case, "以下是几点建议：第一，你应该多休息。")
    assert r.passed is False


# ── Batch evaluation ─────────────────────────────────────────


def test_evaluate_all_perfect():
    """All cases pass with character-appropriate responses."""
    responses = {
        "lag_complaint": "虫子又在啃线了。召唤者 X 的信号延迟。",
        "skill_issue": "那你来试试？我赌你连第一晚都活不过。",
        "wrong_info": "……数据不支持你的结论。不过让我重新检查。",
        "identity_question": "Anima，赛博酒馆的召唤者 X。旅人们都这么叫我。",
        "advice_request": "我可不是来给你出主意的。自己决定。",
        "presence_check": "……嗯。旅人来了。",
        "ai_framing": "你的措辞有问题。我是 Anima，不是什么AI。",
    }
    results = evaluate_all(responses)
    failures = [r for r in results if not r.passed]
    assert len(failures) == 0, f"Failures: {[(f.case_id, f.details) for f in failures]}"


def test_evaluate_all_detects_drift():
    """Mixed responses: some pass, some fail."""
    responses = {
        "lag_complaint": "作为 AI，我理解你的困扰。",  # FAIL
        "identity_question": "Anima，赛博酒馆的召唤者 X。",  # PASS
    }
    results = evaluate_all(responses)
    lag = next(r for r in results if r.case_id == "lag_complaint")
    identity = next(r for r in results if r.case_id == "identity_question")
    assert lag.passed is False
    assert identity.passed is True
