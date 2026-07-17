"""Deterministic construction of the anonymous audition matrix."""

from __future__ import annotations

from animetta.acceptance.tts_audition.models import (
    AuditionCandidate,
    AuditionPlan,
    AuditionSample,
    CandidateProvider,
    Emotion,
)

CHARACTER_CONSTRAINT = "整体保持冷静、克制、有教养，不卖萌、不夸张"

_TEXT_BY_EMOTION = {
    Emotion.NEUTRAL: "夜已经很深了。你若愿意，我们可以把这件事慢慢说清楚。",
    Emotion.HAPPY: "事情比预想得顺利。很好，我们终于可以稍微松一口气了。",
    Emotion.SAD: "我记得那些没有说完的话。没关系，今晚先安静地陪你一会儿。",
    Emotion.ANGRY: "这件事越过了边界。我会保持冷静，但绝不会假装它没有发生。",
    Emotion.SURPRISED: "原来答案一直在这里。确实出乎意料，不过现在一切都说得通了。",
    Emotion.THINKING: "让我想一想。关键也许不在结果，而在我们忽略的那个前提。",
}

_CANDIDATES = (
    AuditionCandidate(
        label="A",
        provider=CandidateProvider.COSYVOICE,
        model="cosyvoice-v3.5-flash",
        voice=None,
        price_cny_per_10k_chars=0.8,
        voice_design_prompt=(
            "一位年轻成年女性，普通话自然，音色偏冷、清澈而沉静，中低音稳定。"
            "表达理性克制、受过良好教育，亲近但保持分寸，不甜腻、不幼态。"
        ),
    ),
    AuditionCandidate(
        label="B",
        provider=CandidateProvider.COSYVOICE,
        model="cosyvoice-v3.5-flash",
        voice=None,
        price_cny_per_10k_chars=0.8,
        voice_design_prompt=(
            "一位成年女性，普通话清晰，音色冷静而略带沙质，声音有柔和的距离感。"
            "语气聪慧从容、礼貌坚定，情绪细腻但绝不夸张，不卖萌、不撒娇。"
        ),
    ),
    AuditionCandidate(
        label="C",
        provider=CandidateProvider.QWEN_REALTIME,
        model="qwen3-tts-instruct-flash-realtime",
        voice="Vivian",
        price_cny_per_10k_chars=1.0,
    ),
    AuditionCandidate(
        label="D",
        provider=CandidateProvider.QWEN_REALTIME,
        model="qwen3-tts-instruct-flash-realtime",
        voice="Seren",
        price_cny_per_10k_chars=1.0,
    ),
)


def build_audition_plan() -> AuditionPlan:
    """Return the stable four-candidate by six-emotion audition plan."""

    samples = tuple(
        AuditionSample(
            sample_id=f"{candidate.label}-{emotion.value}",
            candidate_label=candidate.label,
            emotion=emotion,
            text=_TEXT_BY_EMOTION[emotion],
            instruction=f"{CHARACTER_CONSTRAINT}；{emotion.delivery_modifier}。",
        )
        for candidate in _CANDIDATES
        for emotion in Emotion
    )
    return AuditionPlan(candidates=_CANDIDATES, samples=samples)
