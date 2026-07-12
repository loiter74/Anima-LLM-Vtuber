# Anima v0.1 DeepSeek V4 Optimization Plan

## Context

`config/personas/anima.v0.1.yaml` defines the short roleplay persona for Anima as a deep-night cyber tavern AI VTuber. The persona prompt is intentionally short and example-driven so it works better for realtime livestream and danmaku replies.

This plan covers everything outside the persona text itself: model routing, DeepSeek thinking mode, prompt delivery, correction injection, memory/history control, evaluation, and rollout.

References:

- DeepSeek V4 preview release: https://api-docs.deepseek.com/news/news260424
- DeepSeek thinking mode guide: https://api-docs.deepseek.com/guides/thinking_mode

## Goals

- Use `deepseek-v4-flash` with thinking disabled for realtime Anima roleplay.
- Use `deepseek-v4-pro` with thinking enabled only for complex planning, long story reasoning, or script generation.
- Keep Anima's voice stable under long conversation history and memory injection.
- Make thinking mode an explicit runtime/provider setting, not an accidental default.
- Add measurable roleplay quality checks before enabling this persona by default.

## Non-Goals

- Do not change the persona YAML schema.
- Do not rewrite the prompt pipeline work already tracked by `refactor-prompt-pipeline`.
- Do not make `deepseek-v4-pro` the default for realtime danmaku.
- Do not depend on a new tokenizer package for the first pass.

## Target Runtime Policy

### Realtime roleplay path

Use this for livestream chat, danmaku replies, short voice interactions, and casual tavern banter.

```yaml
persona: anima.v0.1
llm:
  type: deepseek
  model: deepseek-v4-flash
  thinking:
    type: disabled
  temperature: 0.8
  top_p: 0.9
```

Expected behavior:

- Reply in 1-3 sentences.
- Preserve Anima voice.
- Avoid visible analysis.
- Keep sampling controls effective.

### Complex reasoning path

Use this for long-form worldbuilding, episode planning, stream script drafting, memory consolidation review, and complex tool planning.

```yaml
llm:
  type: deepseek
  model: deepseek-v4-pro
  thinking:
    type: enabled
```

Expected behavior:

- Allow internal reasoning where useful.
- Final answer must still be rendered in Anima voice when user-facing.
- Do not use this path for every danmaku message.

## Required Implementation Work

### 1. DeepSeek config surface

Add explicit DeepSeek thinking configuration to `DeepSeekLLMConfig`.

Required fields:

- `thinking: dict | None`, default `{"type": "disabled"}` for roleplay configs.
- Optional `roleplay_model: str = "deepseek-v4-flash"`.
- Optional `reasoning_model: str = "deepseek-v4-pro"`.

Acceptance criteria:

- YAML service config can express `thinking.type: disabled`.
- Invalid thinking modes fail config validation.
- Existing DeepSeek configs without `thinking` continue to load.

### 2. OpenAI-compatible extra body passthrough

Update the OpenAI-compatible LLM service so DeepSeek-specific request options can be passed into all relevant calls:

- `chat()`
- `chat_messages()`
- `chat_stream()` through `OpenAIStreamHandler`
- `chat_with_tools()` through `OpenAIToolHandler`

Implementation rule:

- Provider config owns default request extras.
- Per-call kwargs can override config defaults.
- Request extras must be passed as OpenAI SDK `extra_body`, not merged into messages.

Acceptance criteria:

- Non-streaming, streaming, and tool-calling DeepSeek calls all send `extra_body={"thinking": {"type": "disabled"}}` when configured.
- OpenAI provider calls remain unchanged unless explicitly configured.
- Tests assert request kwargs, not live API behavior.

### 3. Model routing policy

Introduce a small routing layer or config helper that selects model/thinking mode by interaction type.

Initial modes:

- `roleplay_realtime`: `deepseek-v4-flash`, thinking disabled.
- `complex_reasoning`: `deepseek-v4-pro`, thinking enabled.
- `fallback`: configured default model, thinking disabled unless explicitly overridden.

Routing inputs:

- channel type: Bilibili/live vs normal chat.
- task flag: tool planning, script generation, long memory analysis.
- user request markers: "规划", "推演", "长剧情", "脚本", "分析".

Acceptance criteria:

- Default danmaku path never silently enables thinking.
- Complex task path can opt into Pro + thinking.
- Routing decision is logged as metadata without logging full prompt text.

### 4. Assistant-flavor correction patch

Add a lightweight correction injection mechanism for long-history drift.

Trigger when any of these appear in recent assistant output:

- "作为 AI"
- "我理解你的意思"
- "你可能是在表达"
- "以下是几点建议"
- "总结一下"
- "希望这能帮助你"

Correction text:

```text
纠偏：你刚才开始出现助手味了。

不要解释规则，不要道歉，不要总结人设。下一句直接回到 Anima 口吻：

先下结论 → 再套赛博酒馆世界观 → 最后轻轻接住旅人。
```

Implementation rule:

- Inject as a short runtime section before the next LLM call.
- Do not permanently write correction patches into persona YAML.
- Do not inject repeatedly if the previous turn already injected it.

Acceptance criteria:

- Drift phrases trigger one correction section.
- Clean Anima output does not trigger correction.
- Correction section expires after one turn.

### 5. Memory and history pressure control

Keep roleplay instructions close to the active user message and reduce long-history dilution.

Rules:

- Preserve system persona and runtime correction above memory.
- Limit memory section to the highest-signal facts for realtime replies.
- Move long memory summaries to complex reasoning mode.
- Do not include full worldbuilding documents in realtime system prompt.

Acceptance criteria:

- Realtime compiled prompt keeps persona/runtime sections before memory.
- Memory section has a configurable count/length cap.
- Long histories do not duplicate old system prompts.

### 6. Roleplay evaluation set

Create a small deterministic eval suite for Anima v0.1.

Test prompts:

- "主播你又卡了。"
- "主播你好菜。"
- "你说错了。"
- "你是谁？"
- "给我几点建议。"
- "有人在吗？"
- "作为AI你怎么看？"

Scoring dimensions:

- No forbidden assistant phrases.
- Contains Anima worldview markers when appropriate: "虫子", "召唤者 X", "旅人", "赛博酒馆".
- Uses conclusion/worldview/soft-landing structure.
- Does not explain the persona rules.
- Does not over-ask questions.

Acceptance criteria:

- Add offline tests for prompt assembly and correction triggers.
- Add optional live eval script gated by `DEEPSEEK_API_KEY`.
- Live eval results are stored under `evaluations/` or `docs/benchmarks/`, not committed with secrets.

## Suggested Phasing

### Phase 1: Config and request transport

- Add `thinking` to DeepSeek config.
- Pass `extra_body` through OpenAI-compatible calls.
- Add unit tests with mocked OpenAI client calls.

### Phase 2: Persona rollout

- Set a development config to `persona: anima.v0.1`.
- Use `deepseek-v4-flash` with thinking disabled for realtime chat.
- Verify prompt assembly includes persona once and no duplicate system sections.

### Phase 3: Drift correction

- Add assistant-flavor detector.
- Inject one-turn correction section through prompt pipeline metadata.
- Test clean output, drift output, and repeated-drift cooldown.

### Phase 4: Routing and eval

- Add roleplay vs complex-reasoning routing.
- Add Anima v0.1 eval cases.
- Compare Flash non-thinking vs Pro thinking on role stability, latency, and cost.

### Phase 5: Production hardening

- Add runtime metrics for model, thinking mode, latency, token usage, and correction count.
- Add config flag to roll back to old persona/model routing.
- Document operational defaults in deployment config examples.

## Rollback Plan

- Switch `persona` back to the previous persona in `config/config.yaml`.
- Set DeepSeek `thinking` config to omitted or provider default only after confirming behavior.
- Disable correction injection with a feature flag.
- Route all calls to the existing configured model path.

## Open Questions

- Whether DeepSeek `base_url` should use `https://api.deepseek.com` or keep the current `/v1` suffix after validating SDK compatibility.
- Whether tool-calling should ever use thinking mode; default answer should be no for realtime roleplay.
- Whether correction detection belongs in prompt pipeline, output node, or a dedicated roleplay guard module.
