"""Deterministic final response selection; this module never calls an LLM."""

from __future__ import annotations

from animetta.orchestration.prompting.roleplay_guard import has_drift

from .contracts import ComposerResult, ReasonerResult
from .models import FinalResponseSelection


def select_final_response(
    reasoner: ReasonerResult,
    composer: ComposerResult | None,
    *,
    rejection_code: str | None = None,
) -> FinalResponseSelection:
    if composer is not None and not has_drift(composer.final_response):
        return FinalResponseSelection(text=composer.final_response, source="composer")
    reason = rejection_code or ("roleplay_drift" if composer is not None else "composer_failed")
    return FinalResponseSelection(
        text=reasoner.normal_response,
        source="composer_fallback",
        rejection_code=reason,
    )
