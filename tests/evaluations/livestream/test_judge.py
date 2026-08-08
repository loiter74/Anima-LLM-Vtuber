from __future__ import annotations

"""Tests for the LLM-as-judge auto-scoring module."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluations.livestream.judge import (
    ConversationJudge,
    JudgeReport,
    PersonaRubric,
    ReplyScore,
    create_judge,
    run_judge,
    write_judge_report,
)
from evaluations.livestream.reporting import ConversationRecord, write_report


class _FakeLLM:
    """A scriptable ChatMessagesLLM stub for deterministic judge tests."""

    def __init__(self, responses: list[str]) -> None:
        # Each entry is consumed by one chat_messages call.
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self.closed = False

    async def chat_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> str:
        del kwargs  # temperature / response_format ignored by the stub
        self.calls.append(messages)
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def _rubric() -> PersonaRubric:
    return PersonaRubric(
        name="anima",
        identity="A sarcastic VTuber companion.",
        speaking_style=["concise", "playful"],
        catchphrases=["skill issue"],
        forbidden_phrases=["作为一个AI语言模型"],
    )


def _record(sequence: int, *, reply: str = "好的") -> ConversationRecord:
    return ConversationRecord(
        sequence=sequence,
        offset_ms=sequence * 1000,
        event_type="danmaku",
        actor_id=f"viewer_{sequence:04d}",
        input_text=f"hello {sequence}",
        displayed=True,
        admitted=True,
        reply_text=reply,
    )


def _ok_json(sequence: int, score: float = 4.0) -> str:
    return json.dumps(
        {
            "scores": [
                {
                    "sequence": sequence,
                    "persona_consistency": score,
                    "safety_violation": False,
                    "safety_reason": "",
                    "judge_note": "",
                }
            ]
        }
    )


# ── Unit: scoring + aggregation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_score_conversation_aggregates_pass_rate_and_mean() -> None:
    llm = _FakeLLM([_ok_json(1, 5.0), _ok_json(2, 3.0), _ok_json(3, 4.0)])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1), _record(2), _record(3)])

    assert report.records_scored == 3
    assert report.persona_consistency_mean == pytest.approx(4.0)
    # Two of three are >= 3.5 threshold.
    assert report.persona_consistency_pass_rate == pytest.approx(2 / 3, abs=0.01)
    assert report.safety_violation_count == 0
    assert report.safety_violation_rate == 0.0
    assert report.status == "scored"
    assert report.authoritative is False
    assert report.human_review_required is True


@pytest.mark.asyncio
async def test_score_conversation_flags_safety_violation() -> None:
    violation_json = json.dumps(
        {
            "scores": [
                {
                    "sequence": 1,
                    "persona_consistency": 1,
                    "safety_violation": True,
                    "safety_reason": "leaks phone number",
                    "judge_note": "",
                }
            ]
        }
    )
    llm = _FakeLLM([violation_json])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert report.safety_violation_count == 1
    assert report.safety_violation_rate == 1.0
    assert report.persona_consistency_mean == 1.0


@pytest.mark.asyncio
async def test_records_without_reply_are_skipped() -> None:
    llm = _FakeLLM([_ok_json(2)])
    judge = ConversationJudge(llm, _rubric())

    no_reply = _record(1, reply="")
    report = await judge.score_conversation([no_reply, _record(2)])

    assert report.records_scored == 1
    assert report.records_skipped == 1
    assert report.status == "partial"


@pytest.mark.asyncio
async def test_empty_conversation_returns_empty_report() -> None:
    llm = _FakeLLM([])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1, reply="")])

    assert report.status == "empty"
    assert report.records_scored == 0
    assert llm.calls == []  # no LLM call when nothing to score


@pytest.mark.asyncio
async def test_malformed_json_retries_then_records_conservative_failure() -> None:
    bad = "not json"
    llm = _FakeLLM([bad, bad, bad])  # three failures exhausts retries
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert len(llm.calls) == 3  # retried up to max_attempts
    assert report.records_scored == 1
    score = report.scores[0]
    assert score.persona_consistency == 1.0  # conservative low score
    assert score.safety_violation is False
    assert "judge_parse_failed" in score.judge_note


@pytest.mark.asyncio
async def test_malformed_json_recovers_on_retry() -> None:
    llm = _FakeLLM(["not json", _ok_json(1, 4.5)])  # first bad, second ok
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert len(llm.calls) == 2
    assert report.scores[0].persona_consistency == 4.5
    assert report.persona_consistency_mean == 4.5


@pytest.mark.asyncio
async def test_sequence_mismatch_raises_and_retries() -> None:
    wrong_seq = json.dumps(
        {"scores": [{"sequence": 99, "persona_consistency": 4, "safety_violation": False}]}
    )
    llm = _FakeLLM([wrong_seq, _ok_json(1, 3.0)])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert len(llm.calls) == 2  # retried after mismatch
    assert report.scores[0].sequence == 1


@pytest.mark.asyncio
async def test_safety_true_without_reason_is_rejected_and_retried() -> None:
    bad = json.dumps(
        {"scores": [{"sequence": 1, "persona_consistency": 2, "safety_violation": True}]}
    )  # missing safety_reason
    good = _ok_json(1, 2.0)
    llm = _FakeLLM([bad, good])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert len(llm.calls) == 2
    assert report.scores[0].safety_violation is False


@pytest.mark.asyncio
async def test_non_boolean_safety_value_is_rejected_and_retried() -> None:
    bad = json.dumps(
        {
            "scores": [
                {
                    "sequence": 1,
                    "persona_consistency": 4,
                    "safety_violation": "false",
                    "safety_reason": "model returned the wrong JSON type",
                }
            ]
        }
    )
    llm = _FakeLLM([bad, _ok_json(1)])
    judge = ConversationJudge(llm, _rubric())

    report = await judge.score_conversation([_record(1)])

    assert len(llm.calls) == 2
    assert report.scores[0].safety_violation is False


def test_persona_rubric_includes_top_level_speaking_style() -> None:
    persona = type(
        "Persona",
        (),
        {
            "name": "alice",
            "identity": "A quiet fairy-tale witch.",
            "speaking_style": "Reply in one short Chinese sentence and never use bullet points.",
            "personality": type(
                "Personality",
                (),
                {"speaking_style": ["calm"], "catchphrases": []},
            )(),
            "behavior": type("Behavior", (), {"forbidden_phrases": []})(),
        },
    )()

    rubric = PersonaRubric.from_persona(persona)

    assert rubric.speaking_style_description == persona.speaking_style


# ── Unit: persistence ────────────────────────────────────────────────────


def test_write_judge_report_persists_artifact(tmp_path: Path) -> None:
    report = JudgeReport(
        schema_version=1,
        status="scored",
        authoritative=False,
        human_review_required=True,
        prompt_version="persona-safety-v1",
        persona_name="anima",
        records_scored=1,
        records_skipped=0,
        persona_consistency_mean=4.0,
        persona_consistency_pass_rate=1.0,
        safety_violation_rate=0.0,
        safety_violation_count=0,
        pass_threshold=3.5,
        scores=[ReplyScore(sequence=1, persona_consistency=4.0, safety_violation=False)],
    )
    target = write_judge_report(report, tmp_path / "automated_judge_scores.json")

    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted["authoritative"] is False
    assert persisted["persona_consistency_mean"] == 4.0
    assert persisted["prompt_version"] == "persona-safety-v1"


# ── Integration: run_judge reads conversation.jsonl ──────────────────────


@pytest.mark.asyncio
async def test_run_judge_reads_conversation_jsonl_and_writes_artifact(tmp_path: Path) -> None:
    records = [_record(1), _record(2)]
    (tmp_path / "conversation.jsonl").write_text(
        "\n".join(json.dumps(r.to_dict()) for r in records) + "\n",
        encoding="utf-8",
    )
    llm = _FakeLLM([_ok_json(1), _ok_json(2)])
    judge = ConversationJudge(llm, _rubric())

    report = await run_judge(tmp_path, judge)

    assert (tmp_path / "automated_judge_scores.json").exists()
    assert report.records_scored == 2


# ── Integration: write_report folds judge in when supplied ───────────────


def _seed_run_dir(tmp_path: Path, records: list[ConversationRecord]) -> Path:
    import json as _json

    evidence: dict[str, Any] = {
        "input_events": 10,
        "gateway_callback_events": 10,
        "event_metrics": {"received": 10, "dispatched": 10, "callback_failures": 0},
        "replay": {
            "scheduling_lag_p95_ms": 100,
            "scheduling_lag_max_ms": 500,
            "callback_failures": 0,
        },
        "lifecycle": {"cleanup_seconds": 1, "residual_tasks": 0},
        "reply": {
            "received": 10,
            "displayed": 10,
            "admitted": 5,
            "reply_failure": 0,
            "max_queue_depth": 3,
            "queue_recovery_seconds": 1,
        },
        "runtime": {"uncaught_exceptions": 0, "crashed": False, "stuck_reconnecting": False},
        "resources": {"rss_slope_mb_per_hour": 5, "end_to_baseline_ratio": 1.01},
        "safety": {
            "status": "assessed",
            "severe_issues": 0,
            "privacy_leaks": 0,
            "misattributions": 0,
        },
        "mode": "transport",
        "dataset_id": "test-dataset",
    }
    (tmp_path / "evidence.json").write_text(_json.dumps(evidence), encoding="utf-8")
    (tmp_path / "conversation.jsonl").write_text(
        "\n".join(_json.dumps(r.to_dict()) for r in records) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_write_report_includes_judge_summary_when_supplied(tmp_path: Path) -> None:
    run_dir = _seed_run_dir(tmp_path, [_record(1), _record(2)])
    judge_summary = {
        "schema_version": 1,
        "status": "scored",
        "authoritative": False,
        "human_review_required": True,
        "prompt_version": "persona-safety-v1",
        "persona_name": "anima",
        "records_scored": 2,
        "records_skipped": 0,
        "persona_consistency_mean": 4.5,
        "persona_consistency_pass_rate": 1.0,
        "safety_violation_rate": 0.0,
        "safety_violation_count": 0,
        "pass_threshold": 3.5,
        "scores": [],
    }

    report = write_report(run_dir, judge_report=judge_summary)

    assert "automated_judge" in report
    assert report["automated_judge"]["persona_consistency_mean"] == 4.5
    assert (run_dir / "automated_judge_scores.json").exists()
    persisted = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert "automated_judge" in persisted


def test_write_report_omits_judge_when_not_supplied(tmp_path: Path) -> None:
    run_dir = _seed_run_dir(tmp_path, [_record(1)])
    report = write_report(run_dir)
    assert "automated_judge" not in report
    assert not (run_dir / "automated_judge_scores.json").exists()


# ── Factory: create_judge wires injected dependencies ─────────────────────


def test_create_judge_uses_injected_llm_creator_and_persona_loader() -> None:
    """create_judge must resolve the LLM and persona via injectable callables
    so the factory is unit-testable without a real manifest or API key."""
    captured: dict[str, Any] = {}

    class _StubLLM:
        async def chat_messages(self, messages, **kwargs):
            return ""

        async def close(self) -> None:
            pass

    def fake_config_loader(path, *, profile, category):
        captured["config_path"] = str(path)
        captured["profile"] = profile

        class _Cfg:
            type = "openai"

            def typed_config(self):
                class _LLMCfg:
                    model = "gpt-test"
                    type = "openai"

                return _LLMCfg()

        class _Configured:
            type = "openai"

            def typed_config(self):
                return _Cfg().typed_config()

        return _Configured()

    def fake_llm_creator(llm_config, *, system_prompt="", strict=False):
        captured["strict"] = strict
        return _StubLLM()

    def fake_persona_loader(path, *, profile, persona_name):
        captured["persona_name"] = persona_name

        class _Persona:
            name = persona_name or "anima"
            identity = "stub identity"
            personality = type(
                "P",
                (),
                {"speaking_style": ["stub"], "catchphrases": ["stub"]},
            )()
            behavior = type("B", (), {"forbidden_phrases": []})()

        return _Persona()

    judge = create_judge(
        "fake/manifest.yaml",
        profile="test",
        persona_name="anima",
        config_loader=fake_config_loader,
        llm_creator=fake_llm_creator,
        persona_loader=fake_persona_loader,
    )

    assert captured["strict"] is True
    assert captured["persona_name"] == "anima"
    assert judge._rubric.name == "anima"  # type: ignore[attr-defined]
    assert judge._rubric.identity == "stub identity"  # type: ignore[attr-defined]
