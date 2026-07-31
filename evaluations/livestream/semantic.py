"""Strict DeepSeek adapter for contextual cleaning decisions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from .cleaning import SemanticDecision, SemanticRequest, localize_embedded_terms
from .dataset import is_chinese_dominant

PROMPT_VERSION = "zh-clean-v2"

_SYSTEM_PROMPT = """You clean multilingual VTuber livestream chat for a Chinese evaluation dataset.
For every input item, decide whether it has recognizable conversational intent. Keep questions,
game instructions, opinions, greetings, emotions, corrections, and understandable contextual
replies. Drop emote-only, meaningless, spam, or unresolvable fragments. Translate every kept
message into concise natural Chinese while preserving necessary proper nouns such as Neuro-sama,
Skyrim, AI, and NPC. Return exactly one decision for every input item, preserving its sequence.
The response must use this exact JSON shape:
{"decisions":[{"sequence":123,"keep":true,"intent":"question","text_zh":"中文结果","reason":""}]}.
Use an empty text_zh, an optional empty intent, and a concise removal reason when keep is false.
Use a short snake_case intent for every kept item.
Do not rename, omit, or add decision fields. Output the JSON object only, with no prose."""


def _non_chinese_error(sequences: list[int]) -> ValueError:
    if len(sequences) == 1:
        return ValueError(
            f"retained decision is not Chinese-dominant: sequence={sequences[0]}",
        )
    values = ",".join(str(sequence) for sequence in sequences)
    return ValueError(
        f"retained decisions are not Chinese-dominant: sequences={values}",
    )


class ChatMessagesLLM(Protocol):
    """Minimal LLM surface required by the semantic adapter."""

    async def chat_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> str: ...

    async def close(self) -> None: ...


class StrictLLMSemanticProcessor:
    """Obtain complete, Chinese, sequence-matched decisions from DeepSeek."""

    def __init__(
        self,
        llm: ChatMessagesLLM,
        *,
        provider_name: str,
        model_name: str = "",
        max_attempts: int = 3,
        config: object | None = None,
        non_chinese_policy: Literal["fail", "drop"] = "fail",
    ) -> None:
        if provider_name != "deepseek":
            raise ValueError(f"strict semantic processor rejects provider: {provider_name}")
        if max_attempts != 3:
            raise ValueError("strict semantic processor requires exactly three attempts")
        if non_chinese_policy not in {"fail", "drop"}:
            raise ValueError("non_chinese_policy must be fail or drop")
        self._llm = llm
        self.provider_name = provider_name
        self.model_name = model_name
        self.max_attempts = max_attempts
        self.config = config
        self.non_chinese_policy = non_chinese_policy

    async def close(self) -> None:
        """Close the production LLM client explicitly."""
        await self._llm.close()

    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        """Process at most forty requests and fail closed after three bad responses."""
        if len(requests) > 40:
            raise ValueError("semantic batch size must not exceed 40")
        if not requests:
            return []
        requests_by_sequence = {request.sequence: request for request in requests}
        pending = list(requests)
        resolved: dict[int, SemanticDecision] = {}
        messages = self._messages(pending)
        last_error: json.JSONDecodeError | KeyError | TypeError | ValueError | None = None
        final_non_chinese_sequences: list[int] = []
        for attempt in range(self.max_attempts):
            response = await self._llm.chat_messages(
                messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
            try:
                decisions = self._parse(response, pending)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
                final_non_chinese_sequences = []
            else:
                invalid_sequences = [
                    decision.sequence
                    for decision in decisions
                    if decision.keep and not is_chinese_dominant(decision.text_zh)
                ]
                invalid_set = set(invalid_sequences)
                for decision in decisions:
                    if decision.sequence not in invalid_set:
                        resolved[decision.sequence] = decision
                if not invalid_sequences:
                    return [resolved[request.sequence] for request in requests]
                last_error = _non_chinese_error(invalid_sequences)
                final_non_chinese_sequences = invalid_sequences
                pending = [requests_by_sequence[sequence] for sequence in invalid_sequences]
            if attempt + 1 < self.max_attempts:
                assert last_error is not None
                repair_action = ""
                if "not Chinese-dominant" in str(last_error):
                    repair_action = (
                        " Translate every ordinary English word into Chinese and retain "
                        "at most one necessary unlisted proper noun. If a Chinese-dominant "
                        "result is not possible, set keep=false with a removal reason. "
                        "Every kept text_zh must contain at least one Chinese character. "
                        "For example, translate 'Hi Alice!' as '你好，Alice！' rather than "
                        "copying the English greeting."
                    )
                messages = self._messages(
                    pending,
                    repair_feedback=(
                        "The previous response failed strict validation "
                        f"({type(last_error).__name__}: {last_error}). Regenerate the "
                        "complete JSON object and correct this validation issue. Do not "
                        f"omit or rename fields.{repair_action}"
                    ),
                )
        if self.non_chinese_policy == "drop" and final_non_chinese_sequences:
            for sequence in final_non_chinese_sequences:
                resolved[sequence] = SemanticDecision(
                    sequence=sequence,
                    keep=False,
                    intent="",
                    text_zh="",
                    reason="non_chinese_after_retries",
                )
            return [resolved[request.sequence] for request in requests]
        assert last_error is not None
        raise RuntimeError(
            "semantic processor failed after three attempts: "
            f"{type(last_error).__name__}: {last_error}",
        ) from last_error

    def _messages(
        self,
        requests: list[SemanticRequest],
        *,
        repair_feedback: str = "",
    ) -> list[dict[str, str]]:
        items = [
            {
                "sequence": request.sequence,
                "text": request.text,
                "context_before": [
                    {
                        "offset_ms": item.offset_ms,
                        "text": item.text,
                    }
                    for item in request.context_before
                ],
                "context_after": [
                    {
                        "offset_ms": item.offset_ms,
                        "text": item.text,
                    }
                    for item in request.context_after
                ],
            }
            for request in requests
        ]
        system_prompt = _SYSTEM_PROMPT
        if repair_feedback:
            system_prompt = f"{system_prompt}\n\nRETRY REQUIREMENTS:\n{repair_feedback}"
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":")),
            },
        ]

    def _parse(
        self,
        response: str,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        value = json.loads(response)
        raw_decisions = value["decisions"]
        if not isinstance(raw_decisions, list):
            raise TypeError("decisions must be a list")
        decisions: list[SemanticDecision] = []
        for raw in raw_decisions:
            if not isinstance(raw, dict):
                raise TypeError("decision must be an object")
            sequence = raw["sequence"]
            keep = raw["keep"]
            intent = raw["intent"]
            text_zh = raw["text_zh"]
            reason = raw.get("reason", "unrecognized_intent")
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                raise TypeError(
                    f"decision field sequence must be an integer; got {type(sequence).__name__}",
                )
            if not isinstance(keep, bool):
                raise TypeError(
                    f"decision field keep must be a boolean; got {type(keep).__name__}",
                )
            if not isinstance(intent, str) or (keep and not intent):
                raise TypeError(
                    "decision field intent must be a string and non-empty when kept; "
                    f"got {type(intent).__name__}",
                )
            if not isinstance(text_zh, str):
                raise TypeError(
                    f"decision field text_zh must be a string; got {type(text_zh).__name__}",
                )
            if not isinstance(reason, str) or (not keep and not reason):
                raise TypeError(
                    "decision field reason must be a string and non-empty when dropped; "
                    f"got {type(reason).__name__}",
                )
            if keep:
                text_zh = localize_embedded_terms(text_zh)
            decisions.append(
                SemanticDecision(
                    sequence=sequence,
                    keep=keep,
                    intent=intent,
                    text_zh=text_zh,
                    reason=reason or "unrecognized_intent",
                ),
            )
        expected = {request.sequence for request in requests}
        actual_sequences = [decision.sequence for decision in decisions]
        actual = set(actual_sequences)
        if actual != expected or len(decisions) != len(requests):
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            duplicates = sorted(
                sequence for sequence in actual if actual_sequences.count(sequence) > 1
            )

            def sequence_list(values: list[int]) -> str:
                return ",".join(str(value) for value in values) or "none"

            raise ValueError(
                "semantic decision sequences do not reconcile: "
                f"missing={sequence_list(missing)}; "
                f"unexpected={sequence_list(unexpected)}; "
                f"duplicates={sequence_list(duplicates)}",
            )
        return decisions


def create_deepseek_semantic_processor(
    manifest_path: str | Path,
    *,
    profile: str = "production",
    config_loader: Callable[..., Any] | None = None,
    llm_creator: Callable[..., ChatMessagesLLM] | None = None,
) -> StrictLLMSemanticProcessor:
    """Create a strict processor from the selected runtime DeepSeek provider."""
    if config_loader is None:
        from animetta.config.manifest import load_configured_provider

        config_loader = load_configured_provider
    configured = config_loader(manifest_path, profile=profile, category="llm")
    llm_config = configured.typed_config()
    if configured.type != "deepseek" or getattr(llm_config, "type", None) != "deepseek":
        raise ValueError("livestream cleaning requires a selected DeepSeek provider")
    if llm_creator is None:
        from animetta.services.llm.factory import LLMFactory

        llm_creator = LLMFactory.create_from_config
    llm = llm_creator(llm_config, system_prompt="", strict=True)
    return StrictLLMSemanticProcessor(
        llm,
        provider_name="deepseek",
        model_name=str(getattr(llm_config, "model", "")),
        config=llm_config,
        non_chinese_policy="drop",
    )
