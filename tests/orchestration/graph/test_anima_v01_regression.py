"""Tests for Anima v0.1 roleplay guard correctness.

Ensures correction text and eval fixtures reference Anima v0.1
(cyber tavern, Summoner X) and NOT old characters (久遠寺有珠).
"""

from animetta.orchestration.prompting.roleplay_guard import CORRECTION_SECTION
from tests.eval.test_anima_roleplay_eval import ANIMA_CASES

# ── Old character markers that must NOT appear ────────────────

OLD_MARKERS = ["久遠寺", "有珠", "魔女"]


# ── Roleplay guard correction text ────────────────────────────


def test_correction_references_anima():
    """CORRECTION_SECTION must reference Anima, not old character."""
    assert "Anima" in CORRECTION_SECTION or "anima" in CORRECTION_SECTION.lower()


def test_correction_no_old_character():
    """CORRECTION_SECTION must not contain old character markers."""
    for marker in OLD_MARKERS:
        assert marker not in CORRECTION_SECTION, f"Old marker '{marker}' found in CORRECTION_SECTION"


# ── Eval fixtures regression ─────────────────────────────────


def test_eval_fixtures_no_old_character():
    """No Anima eval case should reference old character markers."""
    for case in ANIMA_CASES:
        all_text = case.user_input + case.description + " ".join(case.prefer_markers + case.reject_markers)
        for marker in OLD_MARKERS:
            assert marker not in all_text, f"Old marker '{marker}' found in case '{case.id}'"


def test_identity_case_prefers_anima_markers():
    """identity_question case must prefer Anima markers, not old character."""
    case = next((c for c in ANIMA_CASES if c.id == "identity_question"), None)
    assert case is not None
    all_prefer = " ".join(case.prefer_markers)
    # Must have Anima-related markers
    assert "Anima" in all_prefer or "赛博" in all_prefer or "旅人" in all_prefer or "召唤者" in all_prefer
