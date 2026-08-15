from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from animetta.config.providers.llm.pricing import ModelPricingV1
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.services.llm.stream_handler import OpenAIStreamHandler
from animetta.services.llm.usage import usage_from_response


def _pricing(*, verified_on: date | None = None) -> ModelPricingV1:
    return ModelPricingV1(
        cached_input_per_million=0.0028,
        input_per_million=0.14,
        output_per_million=0.28,
        verified_on=verified_on or date.today(),
        source="https://api-docs.deepseek.com/quick_start/pricing/",
    )


def test_usage_math_prices_cached_and_uncached_input_separately() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=2_000_000,
            completion_tokens=500_000,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            prompt_cache_hit_tokens=1_500_000,
        )
    )

    usage = usage_from_response(
        response,
        provider="deepseek",
        model="deepseek-v4-flash",
        pricing=_pricing(),
    )

    assert usage is not None
    assert usage.cached_input_cost_usd == pytest.approx(0.0042)
    assert usage.input_cost_usd == pytest.approx(0.07)
    assert usage.output_cost_usd == pytest.approx(0.14)
    assert usage.total_cost_usd == pytest.approx(0.2142)
    assert usage.estimated is False


def test_pricing_becomes_stale_after_ninety_days() -> None:
    pricing = _pricing(verified_on=date.today() - timedelta(days=91))

    assert pricing.is_stale() is True


def test_pricing_rejects_non_usd_or_unattributed_sources() -> None:
    with pytest.raises(ValidationError):
        ModelPricingV1(
            currency="EUR",
            cached_input_per_million=0,
            input_per_million=1,
            output_per_million=1,
            verified_on=date.today(),
            source="not-a-url",
        )


@pytest.mark.asyncio
async def test_usage_buffer_is_task_local() -> None:
    llm = OpenAILLM.__new__(OpenAILLM)
    llm._provider_identity = "deepseek"
    llm.model = "model"
    llm.pricing = _pricing()
    llm._last_usage = ContextVar("test_usage", default=None)

    async def record(tokens: int) -> int:
        response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=tokens, completion_tokens=1))
        llm._record_usage(response, 0)
        await asyncio.sleep(0)
        usage = llm.consume_usage()
        assert usage is not None
        return usage.input_tokens

    assert await asyncio.gather(record(11), record(22)) == [11, 22]


@pytest.mark.asyncio
async def test_stream_preserves_provider_cache_usage() -> None:
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.model = "deepseek-v4-flash"
    llm.temperature = 0.7
    llm.top_p = 0.9
    llm.max_tokens = 100
    llm.extra_body = {}
    llm.pricing = _pricing()
    llm._provider_identity = "deepseek"
    llm._last_usage = ContextVar("stream_usage", default=None)
    llm.history = []
    llm.max_history_messages = 20
    llm._build_messages = lambda text, **_: [{"role": "user", "content": text}]

    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=10,
                prompt_cache_hit_tokens=80,
            ),
        ),
    ]

    async def response():
        for chunk in chunks:
            yield chunk

    async def create_completion(**_):
        return response()

    llm.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_completion),
        )
    )
    output = [chunk async for chunk in OpenAIStreamHandler(llm).stream("hello")]

    usage = llm.consume_usage()
    assert output == ["ok"]
    assert usage is not None
    assert usage.cached_input_tokens == 80
    assert usage.estimated is False
