# Verification Evidence — 2026-07-12

## Automated gates

- Focused observability, inspection, output, and readiness tests: 213 passed, 1 skipped.
- Audio and VAD regression tests after the provider-model fix: 111 passed.
- Backend suite excluding the unrelated README-alignment failure: 3936 passed, 40 skipped, 103 deselected, 2 xfailed.
- Frontend: 31 files and 279 tests passed; `vue-tsc --noEmit` and production build passed.
- Mypy: 391 source files passed. Changed Python files pass Ruff except the pre-existing `scripts/bench.py` findings outside this change's diff.
- `openspec validate unify-local-observability-ledger --strict`: valid.
- Merge resolution regression after preserving observation-aware ASR/TTS fallback and both ASGI startup paths: 52 passed.

## Clean local runtime

- Backend `/health`, `/ready`, and `/metrics`: HTTP 200.
- Frontend `http://127.0.0.1:3000`: HTTP 200.
- Clean-start log prefix: `data/local-verify5-*`; startup and verified turns contain zero application ERROR-level records, `Traceback`, or `str object is not callable` entries.
- Docker Desktop emitted two unstructured Linux-engine `_ping` 500 messages while external tool discovery ran; these match the separately recorded Docker-engine blocker, not an Animetta request failure.
- MiMo VAD's optional ASR confirmation used its separately configured key, received a 401 warning, and followed its documented fail-open path. The canonical MiMo ASR node then succeeded and committed `asr.transcribe` with provider/model evidence.
- Startup inspection text trace: `0e486599-1fd8-4cda-b97e-d34c875c5a17`, outcome `success`, all critical operations finished.
- Real WAV voice trace/task: `1fec47fc-9695-4ea6-8619-bc2b80981fb1`, message `0a5b3b51-97b8-4069-93db-71f8ebf9c6da`, conversation `764cef7b-5c52-4370-9c3b-6506589a478e`.
- Voice client received final ASR transcript, sentence completion, and `conversation-end`.

## Canonical data-flow correlation

Raw `data/observations.db`, the versioned stats API, and Prometheus agree on the voice workflow:

`asr -> personality -> llm -> humor_rewrite -> humor_validation -> tts -> emotion -> output`

Service children are attached to their real parents:

- `asr.transcribe`: MiMo `mimo-v2.5-asr`
- `memory.recall`: child of `llm`
- `llm.chat_with_tools`: DeepSeek `deepseek-v4-flash`, child of `llm`
- `tts.synthesize`: MiMo `mimo-v2.5-tts`, child of `tts`
- `llm.chat_messages`: non-critical post-turn child of `output`

Integrity queries returned:

- orphan operations without a trace: 0
- orphan child operations without a parent: 0
- invalid event identities: 0
- unfinished critical operations on both correlated text and voice traces: 0

The API reported schema/API version 2, 3 persisted traces, 3 successes, no degraded or failed traces, and a 100% success rate. The voice trace contains 13/13 successful operations, all required delivery events, and post-turn state `1 completed / 0 pending / 0 failed`.

Prometheus committed-record counters include:

- `anima_trace_outcomes_total{outcome="success"} 2`
- each standard workflow node at 2 successful commits after the clean restart
- `asr` at 1 successful commit for the real voice turn
- one successful MiMo ASR service commit and two successful MiMo TTS service commits

## Fresh browser capture

The in-app browser was freshly navigated to `/dashboard` after the voice turn. It displayed trace `1fec47fc-9695-4ea6-8619-bc2b80981fb1` as `OK`, 4.35 seconds, 13/13 nodes, and `1 done / 0 pending / 0 failed` background work. The rendered flow included the actual ASR, LLM, memory, TTS, emotion, output, provider service, and non-critical post-turn operations listed above.

A second fresh reload on the continuation turn reproduced that state with no browser console errors. Navigating through the dashboard's own trace controls also displayed text trace `0e486599-1fd8-4cda-b97e-d34c875c5a17` as `OK`, 5.18 seconds, 11/11 operations, development-visible input text, and `1 done / 0 pending / 0 failed` post-turn work. No previous browser snapshot was reused as verification data.

The repository-local `qa-testing-playwright` skill was installed and followed. A fresh deterministic Playwright network-boundary scenario rendered the exact golden topology, a redacted detail (`已脱敏 · 18 chars`), a degraded `response_guard`, and post-turn `2 done · 1 pending · 0 failed`; all assertions passed with zero browser errors. Screenshot: `C:/Users/30262/AppData/Local/Temp/animetta-qa-golden-degraded.png`.

After the final Docker deployment, a new independent Playwright browser context loaded `http://127.0.0.1/dashboard` with HTTP 200 and zero console/page errors. It rendered real trace `3bab6ba7-6baa-46c1-9793-b7440ea87aef` as `OK`, 11/11 operations, the workflow/service/memory hierarchy, and `1 done · 0 pending · 0 failed`. Screenshot: `C:/Users/30262/AppData/Local/Temp/animetta-qa-docker-dashboard.png`.

## Docker release gate

- The authorized conflicting container remains stopped and was not removed.
- Two timed-out build clients initially left orphaned `docker -> compose -> buildx` process chains. After verifying their command lines, only those six client processes were stopped. BuildKit queries recovered from `RST_STREAM/CANCEL`; Docker Desktop and unrelated containers were not restarted.
- The controlled rebuild then completed successfully in 948.5 seconds (layers 573.7 seconds, unpack 371.7 seconds), producing image `sha256:dfe164e275c974366774f83fd2ef8d3caae6830dca2024a8e90f24eb81a0a3f8`.
- CPU Compose `down` and `up -d` succeeded. `/health` returned HTTP 200 with `status=ok`, `/ready` returned HTTP 200 with `ready=true`, `/metrics` returned HTTP 200 with Prometheus HELP/TYPE records, frontend port 80 returned HTTP 200, and `anima-animetta-1` reported healthy.
- Full Compose logs contained zero ERROR-level records, zero uppercase `ERROR` occurrences, and zero `Traceback` occurrences. No build client processes remained; the verified container was left running.
- OTLP is intentionally disabled by default, so no optional collector evidence was required for the local-first gate.

## Final requirement audit

Fresh completion checks confirmed the OpenSpec change is strict-valid, `git diff --check` exits successfully, and Git reports zero unresolved conflicts. Independent runtime probes returned `health.status=ok`, `ready=true`, HTTP 200 for metrics and frontend, Prometheus HELP/TYPE records, Compose state `running` with health `healthy`, and zero `ERROR`/`Traceback` matches in the complete current Compose logs. Together with the automated, correlated data-flow, privacy, golden topology, real voice/text, deterministic QA, and Docker evidence above, every requirement and all 71 implementation tasks have recorded evidence.
