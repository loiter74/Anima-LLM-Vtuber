# Engineering Audit Report — Animetta (2026-07-25)

> Branch: `audit/nightly-refactor-2026-07-25`. Method: source reading +
> targeted sub-agent exploration + test runs. No runtime/Docker verification
> (test environment is local-only per task rules).
>
> This report focuses on **new** findings beyond what
> `docs/architecture/duplication-audit.md` (2026-07-06) already fixed. Each
> finding is tagged with risk level and whether it is safe to auto-fix.

Risk levels: **P0** (bug / security / data-loss), **P1** (low-risk structural),
**P2** (needs design decision), **P3** (leave for now).

---

## P0-1 — `desktop.chat_message` bypasses the probe/ingress filter

| | |
|---|---|
| **Problem** | The `desktop.chat_message` Socket.IO event calls `orchestrator.process_text` directly, skipping `is_probe_message`, `normalize_chat_command`, and never sets `is_inspection`/`is_probe` metadata. Any Socket.IO client that emits `desktop.chat_message` can send probe-shaped (`"ping"`, `"[inspection] ..."`) or drift-inducing text straight into the LLM. The in-graph Layer-3 guards (`dialogue_nodes.py:46,154`) do **not** fire because the metadata flag is absent. |
| **File locations** | `src/animetta/orchestration/server/handlers/live2d_handlers.py:99-117` (`on_desktop_chat_message`); registered at `src/animetta/orchestration/server/routes.py:438`. Compare the protected path at `chat_handlers.py:121-125`. |
| **Risk** | **P0** — breaks the "probes never reach the LLM" invariant that `message_filter.py` is designed to enforce. The inspection subsystem relies on this invariant for its containment assertion. Also lets unfiltered text skip the chat-contract error-delivery contract, so desktop clients get ad-hoc `system:error` instead of structured `ChatErrorPayload`. |
| **Root cause** | The desktop transport predates `is_probe_message` (introduced with `chat_contracts`). When the canonical `chat:text` route was hardened, the legacy desktop handler was not updated. |
| **Recommended fix** | Route `on_desktop_chat_message` through the same `is_probe_message` + `normalize_chat_command` path as `on_text_event`, OR at minimum call `is_probe_message(data)` before `orchestrator.process_text` and set `is_inspection` in metadata when it fires. |
| **Auto-fixable?** | **Yes** — small, localized, adds a guard rather than changing behavior. Add a regression test that emits a probe via `desktop.chat_message` and asserts the orchestrator is never called. |

---

## P0-2 — `LangGraphOrchestrator._instances` is an unbounded memory leak

| | |
|---|---|
| **Problem** | `LangGraphOrchestrator.create()` (`orchestrator.py:436`) writes `cls._instances[session_id] = orchestrator`, but **nothing ever reads or evicts it**. The real per-session registry is `SessionManager.orchestrators` (`session.py:60,191`), which is correctly cleaned up in `cleanup_session`. So `_instances` grows by one entry per session for the lifetime of the process. Over a long-running production process this is a slow memory + reference leak (each entry holds a `ServiceContext`, LLM engine references, observability callbacks, etc.). |
| **File locations** | `src/animetta/orchestration/graph/orchestrator.py:33` (`_instances: dict = {}`), `:436` (write in `create`), `:439-453` (dead `get`/`remove`/`clear_all` methods). Verified: `grep` for `.get(` / `.remove(` / `.clear_all(` across `src/ tests/ scripts/` returns **zero** callers of these classmethods. |
| **Risk** | **P0** — silent resource leak in long-running deployments; misleading API (looks like a registry, isn't). |
| **Root cause** | Leftover from an earlier design where the orchestrator tracked its own instances; superseded by `SessionManager` but the dead code was never removed. |
| **Recommended fix** | Remove `_instances` and the three dead classmethods `get`/`remove`/`clear_all`. Keep `create()` returning the instance (callers already assign it into `SessionManager.orchestrators`). |
| **Auto-fixable?** | **Yes** — pure deletion of unreferenced code. Verify with `grep` + run the orchestrator test suite. |

---

## P1-1 — Dead `BLEED_MARKERS` telemetry surface has zero consumers

| | |
|---|---|
| **Problem** | `BLEED_MARKERS` (`message_filter.py:47-53`) is exported and documented as a telemetry surface, but grep confirms it has **no runtime consumers** — only one test references it (`tests/core/test_message_filter.py:13,169`). It is effectively dead contract surface. |
| **File locations** | `src/animetta/core/message_filter.py:47-53`. |
| **Risk** | **P1** — mild confusion; future maintainers may wire telemetry to it assuming it is live. |
| **Root cause** | Designed ahead of demand; never wired up. |
| **Recommended fix** | Either (a) delete it and its test assertion, or (b) add a `TODO(telemetry)` comment marking it as an available-but-unused surface. Option (a) is cleaner. |
| **Auto-fixable?** | **Yes** with option (b) (comment only — zero risk). Option (a) needs the test updated. |

---

## P1-2 — Hardcoded port `12394` duplicated across 3 unrelated sites

| | |
|---|---|
| **Problem** | The canonical backend port `12394` (`config/system.py:14`) is duplicated as a literal in: `src/animetta/inspection/checks/metrics.py:19` (`METRICS_ENDPOINT = "http://localhost:12394/metrics"`), `src/animetta/inspection/checks/pipeline.py:29` (`BACKEND_URL = "http://localhost:12394"`), and `src/animetta/utils/env_helper.py:215` (`"ANIMETTA_PORT": "12394"`). If the deployed port changes, these will silently point at the wrong host. |
| **File locations** | as above. |
| **Risk** | **P1** — latent wrong-host bug in inspection probes; today they happen to match the default. |
| **Root cause** | Inspection checks were written when the port was fixed; not refactored when the config-driven port was introduced. |
| **Recommended fix** | Read the port from `EffectiveConfig.system.port` (or env `ANIMETTA_PORT`) at probe construction time. |
| **Auto-fixable?** | **Partial** — straightforward but each site needs its config-injection point verified. Medium-risk; defer unless touching inspection. |

---

## P1-3 — `VibeVoiceTTSConfig` shadows parent fields (`model`, `base_url`)

| | |
|---|---|
| **Problem** | `VibeVoiceTTSConfig` redeclares `model` and `base_url`, which already exist on `TTSBaseConfig`. Pydantic V2 emits a `UserWarning` on every import (visible in test output: *"Field name 'model' in 'VibeVoiceTTSConfig' shadows an attribute in parent 'TTSBaseConfig'"*). This is a real config-modeling smell: the shadowed parent defaults may not apply, and IDE/typing is misleading. |
| **File locations** | `src/animetta/config/providers/tts/vibe_voice.py:12` (and the `model`/`base_url` field declarations below). |
| **Risk** | **P1** — noisy logs (every test run), possible default-value drift between parent and child. |
| **Root cause** | Contrib provider added its own field definitions without checking the base config. |
| **Recommended fix** | Drop the redeclarations and rely on the parent fields; if VibeVoice needs different defaults, override via `model_config` or `Field(default_factory=...)` on the same field name only when the parent truly lacks it. |
| **Auto-fixable?** | **Yes** but needs careful check that removing the redeclaration does not change the effective default — verify with a config unit test. |

---

## P1-4 — Scattered HTTP/operation timeouts with no central policy

| | |
|---|---|
| **Problem** | 15+ hardcoded timeout literals across the codebase with no shared default: `inspection/scheduler.py:67` (`30.0`), `inspection/checks/pipeline.py:269` (`60.0`), `notifier/{email,discord,feishu}.py` (`15`/`10`), `orchestration/graph/output_node.py:280` (`1.0`), `core/redis_checkpoint.py:41` (`5`/`5`), `observability/mirrors/otel.py:86` (`10`), etc. Operationally these are invisible and inconsistent. |
| **File locations** | see above (full list in sub-agent report). |
| **Risk** | **P1** — no single knob to tune external-call aggressiveness; some paths (notifier) may hang much longer than others. |
| **Root cause** | Each module picked a number; no `config/timeouts.py` exists. |
| **Recommended fix** | Introduce `config/timeouts.py` (or extend `config/system.py`) with named defaults (`LLM_API_TIMEOUT`, `TTS_STREAM_TIMEOUT`, `NOTIFIER_HTTP_TIMEOUT`, `INSPECTION_PROBE_TIMEOUT`) and have each site read from it. |
| **Auto-fixable?** | **No** for the full sweep (too many sites, each needs validation). A first slice (inspection + notifier) is feasible. |

---

## P1-5 — Blind `except Exception:` swallows root cause in ~10 readiness/service-pool sites

| | |
|---|---|
| **Problem** | `except Exception:` without binding or logging appears at ~64 sites (333 total BLE001 violations per ruff). The most concerning are: `core/service_pool.py:182` (LLM connectivity failure silently turned into `{"state":"failed"}` — root exception lost); `core/service_pool.py:446` (`runtime_profile` lookup returns `"development"` on any error, should be `AttributeError`); `core/readiness.py` lines 206/272/285/518/570/578/600/653/677/698 (10 sites, each returns a default string with no log); `core/service_context.py:683,728,796`; `inspection/checks/consistency.py:18,28,38`. |
| **File locations** | as above. |
| **Risk** | **P1** — readiness/probe failures are invisible; debugging production outages becomes guesswork. |
| **Root cause** | Defensive coding pattern copied across readiness code; "return a safe default" prioritized over diagnostics. |
| **Recommended fix** | At minimum add `as exc:` + `logger.warning(...)` to the ~64 silent sites. Narrow exception types where the failure mode is known (e.g. `AttributeError` for config attr lookups). |
| **Auto-fixable?** | **Yes** for the "add logging" slice (mechanical). Narrowing types needs per-site judgement — defer. |

---

## P2-1 — `run_golden_preflight` is a 303-line function

| | |
|---|---|
| **Problem** | `core/golden_preflight.py:856-1158` — single 303-line function `run_golden_preflight`. Also `_runtime_engine_evidence` (143 lines, `:704-846`). Hard to test, hard to extend. |
| **File locations** | `src/animetta/core/golden_preflight.py`. |
| **Risk** | **P2** — maintainability; no behavior bug. |
| **Root cause** | Organic growth of the preflight evidence pipeline. |
| **Recommended fix** | Decompose into staged helpers (config snapshot → engine evidence → memory check → trace check → report). Each stage already has a natural boundary. |
| **Auto-fixable?** | **No** — needs design + full preflight test coverage to refactor safely. |

---

## P2-2 — `WebSocketServer.__init__` (192 lines) mixes too many concerns

| | |
|---|---|
| **Problem** | `orchestration/server/websocket.py:62-253` — constructor owns sio setup, route registration, stats_api mount, /metrics, /health, lifecycle, desktop/live2d managers, tracing bootstrap, observation wiring. |
| **File locations** | `src/animetta/orchestration/server/websocket.py`. |
| **Risk** | **P2** — already flagged in `duplication-audit.md` "Left for Later"; needs a bootstrap object. |
| **Recommended fix** | Extract a `ServerBootstrap` that owns config/tracing/logging/checkpointer/warmup, leaving `WebSocketServer` as the ASGI/routes container. |
| **Auto-fixable?** | **No** — touches startup behavior; needs integration coverage. |

---

## P2-3 — Two coexisting dialogue graphs share state but not abstractions

| | |
|---|---|
| **Problem** | The default graph (`llm_node`) and the golden two-pass graph (`reasoner_node → anima_composer_node → response_guard_node → conversation_finalizer_node`) duplicate "strip thinking blocks / emotion tags / affinity parsing" logic in different places. The default `llm_node` has elaborate regex-based reasoning stripping (`_strip_model_thinking`, `_strip_chinese_untagged_reasoning_prefix`); the golden path relies on `services/dialogue/` instead. |
| **File locations** | `orchestration/graph/llm_node.py:29-151` (regex helpers) vs `services/dialogue/{reasoner,composer}.py`. |
| **Risk** | **P2** — drift between the two paths; a fix in one may not propagate. |
| **Root cause** | The golden path is newer and intentionally uses a cleaner service layer; the legacy `llm_node` was never migrated. |
| **Recommended fix** | Defer — migrating the default graph to the dialogue service layer is a large behavior-sensitive change and out of scope for a low-risk refactor. Document the divergence (done in `architecture-current.md`). |
| **Auto-fixable?** | **No.** |

---

## P3-1 — Only 2 `TODO`s, no `FIXME/HACK/XXX`

| | |
|---|---|
| **Problem** | Minimal: `services/live2d/action_queue.py:179` ("TODO: Notify client to interrupt current action"), `services/llm/openai_llm.py:345` ("TODO: Implement loading history from persistent storage"). No `FIXME/HACK/XXX/DEPRECATED` markers. |
| **Risk** | **P3** — informational only. |
| **Auto-fixable?** | N/A. |

---

## Test-coverage gaps on core paths

Verified by inspecting `tests/` (corrected during implementation):

| Required path (task §5.2) | Existing coverage | Status |
|---|---|---|
| Normal chat message | `tests/orchestration/server/test_chat_handler_contract.py`, `test_routes.py` | ✅ covered |
| Inspection ping | `tests/core/test_message_filter.py`, `tests/inspection/test_pipeline.py`, `tests/scripts/test_probe_release_turn.py` | ✅ filter covered; `desktop.chat_message` probe path now covered by the new `test_live2d_handlers.py` (P0-1) |
| Healthcheck | `tests/orchestration/server/test_stats_api.py` (covers `/health` 200/503/500) | ✅ covered |
| Empty / invalid payload | `test_chat_handler_contract.py` + new `test_live2d_handlers.py` + new `is_probe_message` robustness tests in `test_message_filter.py` | ✅ covered (this pass added the missing non-dict / non-string-text cases) |
| LLM call failure | `tests/orchestration/graph/test_llm_node.py` (timeout → fallback, `chat_with_tools` failure → streaming fallback) | ✅ covered |
| TTS call failure | `tests/orchestration/graph/test_tts_node.py` (`RemoteTTSError`, interrupt cleanup, streaming fallback) | ✅ covered |
| Persona drift detection | `tests/orchestration/graph/test_roleplay_guard.py` — **already comprehensive**: `TestPersonalityNodeDriftWiring` (lines 125-223) covers `_detect_previous_turn_drift` → `metadata.roleplay_correction` → compiled-prompt injection end-to-end, including the `ConversationSessionState.commit` path and the "clean turn → no correction" regression. | ✅ **already covered** (initial audit gap claim was wrong; no new test needed) |

---

## Findings discovered during implementation

| ID | Finding | Note |
|---|---|---|
| **P1-9 (new)** | `inspection/checks/consistency.py:has_trace_in_last(minutes, runtime)` has a different signature from its two sibling probes `observation_ledger_responds(runtime)` and `chroma_responds(runtime)` — the leading `minutes` arg is also immediately discarded (`del minutes`, the probe always reads the most-recent trace). Discovered while writing the P1-3 regression test (the parametrized caller had to special-case this probe). Cosmetic + slightly error-prone API; safe to normalize to `(runtime=None)` in a follow-up. Not auto-fixed because the only caller `check_data_consistency` passes `(60, runtime)` positionally and the `minutes` semantics may be intended for a future time-windowed variant. |
| **Correction to the initial audit** | The initial audit listed "persona drift injection loop has no unit test" as a coverage gap. This was **wrong**: `tests/orchestration/graph/test_roleplay_guard.py::TestPersonalityNodeDriftWiring` (lines 125-223) already covers `_detect_previous_turn_drift` → `metadata.roleplay_correction` → compiled-prompt injection comprehensively, including the `ConversationSessionState.commit` path and the clean-turn regression. No new test was needed for P1-4. |
| **P1-2 broadened** | The initial audit scoped the pydantic field-shadow warning to `VibeVoiceTTSConfig` only. Investigation showed it is a **systematic pattern** across 30+ provider configs (LLM/ASR/TTS) that intentionally override `model`/`base_url`/`temperature`/`top_p` with provider-specific defaults. The fix was therefore applied once at the mixin root (`config/core/mixins.py`) rather than per-provider. |

---

## Non-findings (verified clean)

- **No unused imports** (`ruff --select=F401` → all clean).
- **No bare `except:`** (zero in `src/animetta/`).
- **Socket event names** all route through `EVENTS`/`resolve_socket_event`/`event_name` — no string-literal drift.
- **`/health` status codes** are correct (200/503/500) — fixed in prior audit.
- **Inspection scheduler** never imports the orchestrator; probes go via Socket.IO and are filtered.
- **`config/system.py`** is the single source for port/host; `.env` holds only profile + keys.
- **Secrets** are not committed; `.env.example` is a template; config-expansion logs redact values (verified in prior audit).
