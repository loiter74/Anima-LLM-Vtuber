## Context

Anima v0.1 is a short, roleplay-oriented persona intended for realtime livestream and danmaku interaction. The persona file exists, but runtime behavior still depends on provider defaults, prompt assembly, memory injection, and conversation history behavior.

DeepSeek V4 exposes Flash and Pro models and supports thinking/non-thinking modes. For Anima's realtime roleplay, thinking mode should be disabled so sampling controls and short roleplay style stay effective. For complex story planning or long-form reasoning, Pro with thinking enabled can still be used, but it must be an explicit route.

The current backend uses the OpenAI-compatible LLM service for DeepSeek. `DeepSeekLLMConfig` currently exposes model and base URL, while OpenAI-compatible calls do not yet consistently pass provider-specific `extra_body` options through non-streaming, streaming, and tool-calling paths. The prompt pipeline change also gives us a natural place to inject a one-turn correction section when Anima starts sounding like a generic assistant.

## Goals / Non-Goals

**Goals:**

- Make DeepSeek thinking mode explicit in config and request transport.
- Default Anima v0.1 realtime roleplay to `deepseek-v4-flash` with thinking disabled.
- Provide a routing policy for complex reasoning tasks that can opt into `deepseek-v4-pro` with thinking enabled.
- Add assistant-flavor drift detection and one-turn correction injection.
- Add concrete dialogue cases and scoring criteria so Anima v0.1 quality can be evaluated repeatably.
- Preserve existing provider interfaces for non-DeepSeek callers.

**Non-Goals:**

- Do not change the persona YAML schema.
- Do not rewrite the prompt pipeline architecture.
- Do not make live API calls in normal unit tests.
- Do not make `deepseek-v4-pro` the default for danmaku or casual chat.
- Do not commit eval outputs containing secrets or raw API keys.

## Decisions

### Decision 1: Provider config owns DeepSeek request extras

Add an explicit DeepSeek thinking config to `DeepSeekLLMConfig`, then pass it into the OpenAI-compatible service as request extras. The service should expose a normalized `extra_body` or request-options dict used by all create calls.

Alternative considered: inject thinking options from prompt text. Rejected because thinking mode is an API transport option, not prompt content.

### Decision 2: Keep roleplay and reasoning as separate runtime modes

Define at least two policy modes:

- `roleplay_realtime`: Flash, thinking disabled
- `complex_reasoning`: Pro, thinking enabled

The routing helper can start simple, using channel/task hints and explicit caller intent. It should log the selected policy as metadata without logging full prompt text.

Alternative considered: always use Pro with thinking enabled. Rejected because realtime roleplay values latency, stable voice, and sampling behavior more than deep reasoning.

### Decision 3: Drift correction is a one-turn prompt section

Assistant-flavor drift detection should scan recent assistant output for banned helper phrases. When triggered, the system injects one short runtime correction section before the next LLM call. The correction must expire after one turn and must not be written into persona YAML or long-term memory.

Alternative considered: permanently append correction text to the persona prompt. Rejected because it makes the persona longer and less reusable, and it hides runtime quality problems inside static config.

### Decision 4: Dialogue cases are the acceptance contract

The roleplay eval should contain explicit user inputs and expected scoring dimensions. Some checks can be deterministic offline, such as forbidden phrase detection, while live model quality checks remain optional and gated by `DEEPSEEK_API_KEY`.

Alternative considered: rely on manual streamer review only. Rejected because regressions in provider options, memory injection, or prompt order need fast automated signals.

### Decision 5: Memory pressure is controlled through prompt pipeline ordering and caps

For realtime roleplay, persona and one-turn correction sections should remain stronger than memory. Memory sections should be capped by count/length and should not contain full worldbuilding documents in the realtime path.

Alternative considered: rely on the 1M context window. Rejected because larger context does not guarantee stronger role adherence; it can dilute the active roleplay instruction.

## Risks / Trade-offs

- Request-extra passthrough breaks OpenAI calls -> Mitigation: only include `extra_body` when configured and test OpenAI default calls remain unchanged.
- Thinking mode silently omitted in one path -> Mitigation: unit tests must cover chat, chat messages, streaming, and tool-calling create kwargs.
- Roleplay guard over-corrects clean output -> Mitigation: detector uses a narrow forbidden phrase list and a one-turn cooldown.
- Eval scoring becomes too subjective -> Mitigation: split deterministic checks from optional live rubric checks.
- Routing picks Pro too often -> Mitigation: default route is Flash non-thinking; Pro requires explicit complex-reasoning signal.

## Migration Plan

1. Add DeepSeek config fields and validation for thinking mode.
2. Add OpenAI-compatible `extra_body` passthrough across non-streaming, streaming, and tool-calling paths.
3. Add runtime policy helper for roleplay vs complex reasoning.
4. Add roleplay guard detector and one-turn correction section.
5. Add Anima v0.1 dialogue eval fixture and deterministic scoring.
6. Add optional live eval script gated by `DEEPSEEK_API_KEY`.
7. Wire development config examples to `anima.v0.1`, Flash, and thinking disabled.
8. Verify with unit tests, prompt pipeline tests, and optional live eval.

Rollback strategy:

- Set persona back to the previous configured persona.
- Disable the roleplay guard feature flag.
- Remove DeepSeek `thinking` config from service YAML.
- Route all calls through the existing configured model path.

## Open Questions

- Whether the DeepSeek base URL should be normalized to `https://api.deepseek.com` or keep the current `/v1` suffix after SDK compatibility tests.
- Whether complex tool planning should use Pro thinking by default or require explicit opt-in.
- Whether roleplay guard code should live inside prompt pipeline sources or a dedicated roleplay guard module consumed by the prompt pipeline.
