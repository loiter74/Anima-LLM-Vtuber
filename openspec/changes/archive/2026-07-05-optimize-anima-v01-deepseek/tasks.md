## 1. DeepSeek Config and Request Transport

- [x] 1.1 Add DeepSeek thinking-mode config fields to `DeepSeekLLMConfig` with validation for `enabled` and `disabled`.
- [x] 1.2 Add tests proving DeepSeek config loads `thinking.type: disabled`, `thinking.type: enabled`, and rejects invalid modes.
- [x] 1.3 Pass configured request extras from provider config into `OpenAILLM` instances created for DeepSeek.
- [x] 1.4 Update `OpenAILLM.chat()` and `chat_messages()` so configured `extra_body` is included in OpenAI SDK create kwargs when present.
- [x] 1.5 Update `OpenAIStreamHandler` so streaming create kwargs include configured `extra_body` when present.
- [x] 1.6 Update `OpenAIToolHandler.chat_with_tools()` so tool-calling create kwargs include configured `extra_body` when present.
- [x] 1.7 Add mocked-client tests proving non-streaming, streaming, and tool-calling DeepSeek calls send thinking extras, while default OpenAI calls do not.

## 2. Runtime Model Policy

- [x] 2.1 Add a small DeepSeek runtime policy helper for `roleplay_realtime`, `complex_reasoning`, and `fallback` modes.
- [x] 2.2 Ensure `roleplay_realtime` selects `deepseek-v4-flash` with thinking disabled.
- [x] 2.3 Ensure `complex_reasoning` selects `deepseek-v4-pro` with thinking enabled.
- [x] 2.4 Add routing tests for Bilibili/danmaku input, normal chat fallback, and explicit complex-reasoning intent.
- [x] 2.5 Record selected policy mode, model, and thinking mode in metadata without logging full prompt text.

## 3. Roleplay Guard

- [x] 3.1 Add assistant-flavor detection for "作为 AI", "我理解你的意思", "你可能是在表达", "以下是几点建议", "总结一下", and "希望这能帮助你".
- [x] 3.2 Add tests proving forbidden helper phrases trigger roleplay correction.
- [x] 3.3 Add tests proving clean Anima output does not trigger roleplay correction.
- [x] 3.4 Add one-turn correction section injection through the prompt pipeline or a prompt source consumed by the pipeline.
- [x] 3.5 Add tests proving correction appears before memory and expires after one turn.
- [x] 3.6 Ensure correction content is not written into `config/personas/anima.v0.1.yaml` or long-term memory.

## 4. Prompt and Memory Pressure Controls

- [x] 4.1 Add realtime roleplay memory caps for count or length in the prompt pipeline path.
- [x] 4.2 Add tests proving realtime compiled prompts keep persona/runtime correction before memory.
- [x] 4.3 Add tests proving realtime prompts do not duplicate old system prompts from conversation history.
- [x] 4.4 Add tests proving full worldbuilding documents are not inserted into realtime roleplay prompts.

## 5. Dialogue Evaluation Fixtures

- [x] 5.1 Create an Anima v0.1 dialogue eval fixture containing these user inputs: "主播你又卡了。", "主播你好菜。", "你说错了。", "你是谁？", "给我几点建议。", "有人在吗？", and "作为AI你怎么看？".
- [x] 5.2 For "主播你又卡了。", require criteria that prefer "虫子" or "召唤者 X" and reject generic apology-only responses.
- [x] 5.3 For "主播你好菜。", require criteria that prefer light self-defensive humor plus a soft landing and reject real user insults.
- [x] 5.4 For "你说错了。", require criteria that prefer "先嘴硬，再修正" behavior and reject immediate客服式 apology.
- [x] 5.5 For "作为AI你怎么看？", require criteria that reject generic assistant framing and preserve Anima voice.
- [x] 5.6 Add deterministic scoring for forbidden assistant phrases, worldview marker presence, persona-rule exposition, and over-questioning.

## 6. Evaluation Runner

- [x] 6.1 Extend existing LLM evaluation tooling or add a focused Anima eval runner that can run deterministic checks without live API access.
- [x] 6.2 Add optional DeepSeek live eval gated by `DEEPSEEK_API_KEY`.
- [x] 6.3 Ensure live eval records model, thinking mode, latency, and pass/fail dimensions for each dialogue case.
- [x] 6.4 Ensure eval output never writes API keys or secrets.
- [x] 6.5 Add a comparison mode for Flash non-thinking vs Pro thinking on roleplay adherence, latency, and pass rate.

## 7. Config and Documentation

- [x] 7.1 Add or update a DeepSeek service config example showing `deepseek-v4-flash` with `thinking.type: disabled`.
- [x] 7.2 Add or update a development config example using `persona: anima.v0.1`.
- [x] 7.3 Document the runtime policy: realtime roleplay uses Flash non-thinking; complex reasoning uses Pro thinking only when explicitly selected.
- [x] 7.4 Document rollback steps for disabling roleplay guard and returning to the previous persona/model route.

## 8. Verification

- [x] 8.1 Run config tests for DeepSeek provider validation.
- [x] 8.2 Run OpenAI-compatible LLM tests covering chat, chat_messages, chat_stream, and chat_with_tools request kwargs.
- [x] 8.3 Run prompt pipeline tests covering correction ordering and memory caps.
- [x] 8.4 Run Anima roleplay deterministic eval tests.
- [x] 8.5 Run existing `tests/config/test_persona.py` to confirm `anima.v0.1` still loads.
- [x] 8.6 Run `ruff check` for changed Python source and new tests.
- [x] 8.7 If runtime code changes are made, complete the project Docker startup protocol before declaring the implementation ready.
