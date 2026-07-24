# Refactor Plan — Animetta (2026-07-25)

> Derived from `docs/audit-report.md`. Each task lists files, goal, risk,
> verification, and blast radius. Tasks marked **✅ will do** in this nightly
> pass are bounded to P0 + at most 5 low-risk P1, with no external-interface
> change, no large rename, no new framework.

---

## P0 — Bug / security / data-loss

### P0-1 ✅ WILL DO — Close `desktop.chat_message` probe bypass
- **Files**: `src/animetta/orchestration/server/handlers/live2d_handlers.py`, `tests/orchestration/server/handlers/test_live2d_handlers.py` (new or extend).
- **Goal**: `on_desktop_chat_message` calls `is_probe_message(data)` before `orchestrator.process_text`, and drops probes with a debug log (mirroring `ChatHandlers.on_text_event`). Set `is_inspection` in metadata when the flag is present so Layer-3 graph guards still fire as defense-in-depth.
- **Risk**: Very low. Adds a guard; legitimate desktop chat (which never sets probe flags) is unaffected. No external event name or payload change.
- **Verify**: New unit test — emit a probe-shaped `desktop.chat_message` (`{"text":"ping"}` and `{"is_inspection":True,"text":"x"}`) → assert `orchestrator.process_text` is **not** called; emit a normal message → assert it is called once. Run `tests/orchestration/server/test_routes.py`, `tests/orchestration/server/test_live2d*.py`, and the new test.
- **Impact**: `live2d_handlers.py` only. Desktop clients that today rely on sending `ping`/probe text through this event will be silently dropped (acceptable — that was never a documented feature).

### P0-2 ✅ WILL DO — Remove dead `LangGraphOrchestrator._instances` registry
- **Files**: `src/animetta/orchestration/graph/orchestrator.py`, `tests/orchestration/graph/test_orchestrator.py`.
- **Goal**: Delete `_instances` class attr and the dead `get`/`remove`/`clear_all` classmethods. Keep `create()` returning the instance (callers assign into `SessionManager.orchestrators`).
- **Risk**: Very low. Verified zero callers of the removed methods across `src/ tests/ scripts/`. `create()` behavior unchanged.
- **Verify**: `grep -rn "LangGraphOrchestrator\.\(get\|remove\|clear_all\)\|_instances" src/ tests/ scripts/` returns nothing. Run `tests/orchestration/graph/test_orchestrator.py`, `tests/orchestration/server/test_session.py`, `tests/orchestration/graph/test_identity_propagation.py`.
- **Impact**: `orchestrator.py` only. Removes a memory leak in long-running processes.

---

## P1 — Low-risk structural wins

### P1-1 ✅ WILL DO — Delete unused `BLEED_MARKERS` telemetry surface
- **Files**: `src/animetta/core/message_filter.py`, `tests/core/test_message_filter.py`.
- **Goal**: Remove `BLEED_MARKERS` and its test assertion. It has zero runtime consumers.
- **Risk**: Very low. Only one test references it.
- **Verify**: Run `tests/core/test_message_filter.py`.
- **Impact**: `message_filter.py` + its test. (Alternative chosen over a `TODO` comment because the symbol is genuinely unused.)

### P1-2 ✅ WILL DO — Fix `VibeVoiceTTSConfig` field shadowing
- **Files**: `src/animetta/config/providers/tts/vibe_voice.py`.
- **Goal**: Remove the `model` and `base_url` redeclarations that shadow `TTSBaseConfig`, so the pydantic `UserWarning` disappears. Verify the effective defaults are unchanged (rely on parent or set the same default on a non-shadowed field).
- **Risk**: Low. Need to confirm `TTSBaseConfig` already provides both fields with compatible defaults; if VibeVoice needs a different default, set it via `model_config` or keep only the genuinely-different field.
- **Verify**: New/existing config unit test that constructs `VibeVoiceTTSConfig()` and asserts `.model`, `.base_url` equal the previously-hardcoded values. Run with `-W error::UserWarning` to confirm the warning is gone.
- **Impact**: `vibe_voice.py` + one test. Eliminates log noise on every test run.

### P1-3 ✅ WILL DO — Add logging to silent `except Exception` in `inspection/checks/consistency.py`
- **Files**: `src/animetta/inspection/checks/consistency.py`.
- **Goal**: The three consecutive `except Exception:` blocks (`:18,28,38`) swallow errors and return degraded values with no log. Bind `as exc` and `logger.warning(...)`. Narrowest mechanical change in the P1-5 family.
- **Risk**: Very low. Only adds log output; return values unchanged.
- **Verify**: Run `tests/inspection/test_consistency.py`; add one test that injects a failing dependency and asserts a warning is logged.
- **Impact**: `consistency.py` + its test. Improves diagnosability of inspection failures.

### P1-4 ✅ WILL DO — Add `roleplay_guard` drift-injection unit test (test-coverage gap)
- **Files**: `tests/orchestration/graph/test_personality_node.py` (extend or new).
- **Goal**: Cover the `personality_node._detect_previous_turn_drift` → `metadata.roleplay_correction` loop that has no unit test today. Assert: (a) when the last AIMessage contains a forbidden phrase, `roleplay_correction == CORRECTION_SECTION`; (b) when clean, it is `""`; (c) first turn (no prior AIMessage) → `""`.
- **Risk**: Test-only. No production change.
- **Verify**: Run the new test.
- **Impact**: Adds coverage to a core persona-integrity path.

### P1-5 ✅ WILL DO — Add `desktop.chat_message` empty/non-dict payload test
- **Files**: `tests/orchestration/server/handlers/test_live2d_handlers.py` (extend the one added in P0-1).
- **Goal**: Cover the bad-payload path required by task §5.2: empty `text`, missing `text`, non-dict payload. Assert the handler does not raise and does not call the orchestrator on empty input.
- **Risk**: Test-only.
- **Verify**: Run the new test.
- **Impact**: Closes the "empty/invalid payload" test-gap for the desktop transport.

---

## P1 — Deferred (not auto-fixing this pass)

| ID | Finding | Why deferred |
|---|---|---|
| P1-6 | Hardcoded port `12394` in 3 inspection/env sites | Needs config-injection at each site; verify deployed port source. Medium touch. |
| P1-7 | 15+ scattered HTTP timeout literals | Needs a `config/timeouts.py` design + per-site validation. Too broad for one nightly pass. |
| P1-8 | ~64 silent `except Exception:` across readiness/service_pool/service_context | Mechanical but voluminous; do in a focused PR with a lint rule. |

---

## P2 — Needs design decision (do not auto-fix)

| ID | Finding | Note |
|---|---|---|
| P2-1 | `run_golden_preflight` 303-line function | Decompose into staged helpers with full preflight coverage first. |
| P2-2 | `WebSocketServer.__init__` (192 lines) mixes concerns | Extract `ServerBootstrap` (config/tracing/logging/checkpointer/warmup). Carried from `duplication-audit.md`. |
| P2-3 | Default vs golden dialogue graph duplicate text-stripping logic | Migrating default graph to `services/dialogue/` is large + behavior-sensitive. Document only. |
| P2-4 | `ServiceContext` (784 lines), `ServicePool` (470), `WebSocketServer` (506) oversized classes | Split after designing the service-container boundary. |
| P2-5 | `output_node` 239-line function | Split into delivery/memory/observability helpers. |

---

## P3 — Leave for now

| ID | Finding |
|---|---|
| P3-1 | 2 existing TODOs (action_queue interrupt notify; openai_llm history persistence) — informational. |
| P3-2 | `BLEED_MARKERS` alternative (chose delete in P1-1). |

---

## Execution order for tonight

1. P0-2 (delete `_instances`) — pure deletion, fastest to verify.
2. P0-1 (desktop probe guard) — add guard + test.
3. P1-1 (delete `BLEED_MARKERS`).
4. P1-2 (VibeVoice shadowing).
5. P1-3 (consistency.py logging).
6. P1-4 + P1-5 (test-coverage additions).
7. Run full selected test set + ruff + mypy on changed files.
8. Commit each logical change separately with a clear message.

Each step is independently revertable. No step changes a Socket.IO event name, payload contract, CLI flag, or public class signature.
