## 1. Contracts and model isolation

- [x] 1.1 Add failing tests for strict scene contracts, patch revision behavior, bounded guidance, and stale-patch rejection
- [x] 1.2 Implement scene Pydantic contracts and the single-writer state reducer
- [x] 1.3 Add failing tests for native history-neutral structured calls, unsupported-provider degradation, timeout, and invalid JSON
- [x] 1.4 Move internal-call safety helpers into the LLM layer and implement `SceneModelGateway`

## 2. Scene runtime and guidance

- [x] 2.1 Add failing tests for event evidence, periodic/critical triggers, single-flight coalescing, rate budget, cache timeout, and generation reset
- [x] 2.2 Implement rule evidence extraction, `GuidanceComposer`, injectable technique/meme retrievers, and `SceneRuntime`
- [x] 2.3 Add replay tests for scene stage, meme lifecycle, degraded guidance, and analyzer call reduction

## 3. Runtime integration

- [x] 3.1 Add failing Bilibili tests proving all danmaku are observed, room switches reset scene state, guidance enters turn metadata, and host replies feed back
- [x] 3.2 Inject `SceneRuntime` into `LivestreamSession` and wire Bilibili pre-reply/post-reply integration without blocking admission
- [x] 3.3 Add failing prompt and Humor tests for validated guidance rendering, generic improvisation fallback, malformed guidance containment, and scene-guided Humor bypass
- [x] 3.4 Implement `SceneGuidancePromptSource`, PromptContext metadata validation, and Humor bypass for active scene-guided turns

## 4. Configuration and observability

- [x] 4.1 Add failing config tests for strict `off`/`shadow`/`active` scene settings and effective config projection
- [x] 4.2 Implement additive scene-analysis configuration with shadow deployment defaults and component metrics/logging
- [x] 4.3 Add a dedicated `selftest` runtime profile and lifecycle entrypoint that use persistent local Qwen TTS without changing production defaults

## 5. Verification and rollout evidence

- [x] 5.1 Run focused scene, Bilibili, prompt, Humor, dialogue, LLM, and config tests under Python 3.13
- [x] 5.2 Run impact-aware quality selection and required static checks, recording fresh evidence
- [x] 5.3 Execute the full Docker startup protocol in a sub-agent with the local-Qwen self-test profile and verify readiness, frontend HTTP, Qwen persistence, and both Compose logs
- [x] 5.4 Produce the final test report with requirements, commands, results, latency/call-reduction evidence, and any residual risks
