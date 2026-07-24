# Nightly Refactor Result — Animetta (2026-07-25)

> Branch: `audit/nightly-refactor-2026-07-25` (not pushed).
> Scope: engineering audit + low-risk refactor. No product-behavior change.
> Test environment: local Python 3.13.14, no Docker / no live services.

## 1. What was done

A full six-phase audit-and-refactor pass against the Animetta codebase:

1. **Architecture map** — read entry points, orchestration graph, services, memory, inspection, config; documented the **actual** runtime architecture (including the two coexisting dialogue graphs and the three-layer probe containment) in `docs/architecture-current.md`.
2. **Engineering audit** — `docs/audit-report.md` with 9 findings (P0×2, P1×5, P2×3, P3×2) plus findings discovered during implementation.
3. **Refactor plan** — `docs/refactor-plan.md` with per-task files / goal / risk / verification / impact.
4. **Implementation** — 2 P0 fixes + 3 P1 fixes, each in its own commit, each with tests.
5. **Tests + lint + type** — all green (see §4).
6. **This document.**

## 2. Files changed

### Production code
| File | Change | Commit |
|---|---|---|
| `src/animetta/orchestration/graph/orchestrator.py` | Removed dead `_instances` class registry + `get`/`remove`/`clear_all` classmethods (P0-2). **Follow-up:** added centralized `should_skip_llm(text)` guard inside `process_text` (P0-3) — closes the transport-bypass class of bug at the single choke point all text takes into the model. | `34e35b68`, follow-up |
| `src/animetta/core/message_filter.py` | `is_probe_message` now drops non-dict payloads and non-string `text` (was: `AttributeError`); removed unused `BLEED_MARKERS` (P0-1 support + P1-1). | `590b8cb5` |
| `src/animetta/orchestration/server/handlers/live2d_handlers.py` | `on_desktop_chat_message` now filters through `is_probe_message` before `orchestrator.process_text` (P0-1). | `3b8bea3c` |
| `src/animetta/config/core/mixins.py` | Single `warnings.filterwarnings` to silence the 30+-provider pydantic field-shadow noise at the mixin root (P1-2). | `380e2144` |
| `src/animetta/inspection/checks/consistency.py` | Three silent `except Exception:` now bind `as exc` and `logger.warning(...)` the root cause (P1-3). | `4f282b65` |

### Tests
| File | Change |
|---|---|
| `tests/orchestration/graph/test_orchestrator.py` | **Follow-up.** New `TestOrchestratorCentralIngressFilter` class: parametrized probe short-circuit (no graph run, identity preserved, running-state precedence) + real-text passthrough (incl. danmaku `"用户名说: ping"` substring case). |
| `tests/orchestration/server/handlers/test_live2d_handlers.py` | **New.** 11 tests: probe containment (5), bad-payload robustness (3), normal dispatch + error emission (2), plus the normal-path + orchestrator-error cases. |
| `tests/core/test_message_filter.py` | +7 parametrized robustness tests (non-dict, non-string-text); removed the dead `BLEED_MARKERS` test class. |
| `tests/inspection/test_consistency.py` | +1 parametrized test (3 cases) asserting probe failures now emit a warning. |

### Docs
| File | Purpose |
|---|---|
| `docs/architecture-current.md` | **New.** Current architecture (call chain, module map, state stores, two dialogue graphs, probe containment, persona/drift boundaries). |
| `docs/audit-report.md` | **New.** 9 findings + implementation-discovered findings + corrected test-coverage table. |
| `docs/refactor-plan.md` | **New.** P0/P1/P2/P3 plan with verification per task. |
| `docs/nightly-result.md` | **This file.** |

## 3. Issues fixed

| ID | Issue | Risk | How verified |
|---|---|---|---|
| **P0-1** | `desktop.chat_message` bypassed the probe filter → probes/drift text could reach the LLM | Security/integrity | 11 new tests; `desktop.chat_message` probe payloads now dropped, normal dispatch preserved |
| **P0-2** | `LangGraphOrchestrator._instances` populated by `create()` but never read/evicted → unbounded memory leak | Memory leak in long-running processes | grep confirms zero callers; orchestrator/session tests pass |
| **P0-3 (follow-up)** | Probe containment was enforced per-transport, not at the LLM entry point — the Bilibili caller and any future transport could bypass it | Security/integrity (class of bug) | New `TestOrchestratorCentralIngressFilter` class; probe short-circuit verified at the choke point, real text (incl. danmaku substring) still flows through |
| **P0-1 support** | `is_probe_message(None)` and `is_probe_message({"text": 12345})` raised `AttributeError` / downstream crash | Robustness | 7 parametrized robustness tests |
| **P1-1** | `BLEED_MARKERS` had zero runtime consumers (dead contract surface) | Maintainability | grep + tests |
| **P1-2** | Pydantic `UserWarning: Field name ... shadows ...` × 30+ providers per test run | Log noise (hundreds of warnings) | 0 shadow warnings across 1312+ test run; provider defaults unchanged |
| **P1-3** | 3 inspection probes swallowed exceptions silently → failures invisible | Diagnosability | 3 parametrized regression tests |

## 4. Test results

- **Full selected suite** (`py -3.13 -m pytest`, default markers exclude slow/integration/real_smoke/production_*): **4658 passed, 33 skipped, 2 xfailed, 0 failed** in 125 s (the +15 vs. the pre-follow-up 4643 is the new centralized-filter test class).
- **Targeted runs (changed modules):** `tests/orchestration/ tests/core/ tests/config/ tests/inspection/` → **1720 passed, 3 skipped** (skips are pre-existing `redis-py not installed`).
- **Core-path tests:** `test_roleplay_guard.py + test_personality_node.py + test_llm_node.py + test_tts_node.py` → **129 passed**.
- **New tests:** all passing (11 + 7 + 3 cases).
- **Lint:** `ruff check` on all changed files → **All checks passed!**
- **Type:** `mypy` on changed source files → **Success: no issues found in 5 source files**.
- **The 33 skips / 2 xfails** are pre-existing and environment-driven (redis-py absent, optional providers, known-flaky marks) — none introduced by this pass.

## 5. Not changed (deliberately)

- No Socket.IO event name or payload contract changed.
- No CLI flag, public class signature, or config schema changed.
- No file renamed, no framework added.
- The default-vs-golden dialogue-graph duplication (P2-3), `WebSocketServer.__init__` size (P2-2), `run_golden_preflight` length (P2-1), and the ~64 remaining silent `except Exception` sites (P1-8) were **not** auto-fixed — they need design decisions and are documented in `docs/refactor-plan.md`.

## 6. Issues not yet handled (deferred)

See `docs/refactor-plan.md` "Deferred" and "P2" sections. Highlights:
- **P1-6/P1-7**: hardcoded port `12394` and ~15 scattered timeout literals → central config.
- **P1-8**: ~64 silent `except Exception` in readiness/service_pool/service_context (mechanical but voluminous).
- **P1-9 (new)**: `has_trace_in_last(minutes, runtime)` inconsistent signature vs sibling probes.
- **P2-1/P2-2/P2-3**: large functions and the two-graph duplication.

## 7. Top 5 things to human-review tomorrow

1. **P0-3 centralized probe filter in `process_text`** (`orchestrator.py`) — the new `should_skip_llm(text)` guard is defense-in-depth at the LLM entry choke point. Confirm the text-only semantics are right for every caller: real user text including a danmaku `"用户名说: ping"` (substring, not bare token) still flows through, while bare `"ping"` / `"[inspection] ..."` is dropped regardless of transport. If any production flow legitimately sends a bare probe token as real user input, it will now be silently dropped at this layer too.
2. **P0-1 desktop guard semantics** (`live2d_handlers.py:99-130`) — confirm dropping probe-shaped `desktop.chat_message` payloads is acceptable for any Electron client currently relying on sending `ping`/health text through that event. (Now doubly-protected by P0-3, but the per-handler drop is still the right place for the `system:error`/contract behavior.)
3. **P1-2 shadow-warning filter placement** (`config/core/mixins.py`) — the filter is global and message-pattern-based. It silences *all* pydantic field-shadow warnings repo-wide, not just the intentional provider-default overrides. If a future field shadow is unintentional, it will not surface. Acceptable trade-off, but worth a conscious sign-off.
4. **P0-2 removal of `_instances`** (`orchestrator.py`) — double-check no external/undocumented consumer (e.g. a script, a monitoring tool) relied on `LangGraphOrchestrator.get(session_id)`. Grep across the repo found none, but a deployed sidecar outside the repo is possible.
5. **Two coexisting dialogue graphs** (documented in `architecture-current.md §7`) — the default `llm_node` path and the golden two-pass path duplicate text-stripping/drift logic. A future decision on whether to migrate the default graph to `services/dialogue/` would close the largest remaining structural divergence (now the recommended next step in §8).

## 8. The single most valuable next step

(The original "centralize the ingress filter" recommendation from the first nightly pass has been **done** in the follow-up commit — P0-3. The new most-valuable next step:)

**Migrate the default dialogue graph to the `services/dialogue/` service layer** (P2-3). The default `llm_node` path and the golden two-pass path (`reasoner_node → anima_composer_node → response_guard_node → conversation_finalizer_node`) currently duplicate text-stripping / drift / affinity logic in two places — the legacy `llm_node` carries ~120 lines of regex-based reasoning stripping (`_strip_model_thinking`, `_strip_chinese_untagged_reasoning_prefix`), while the golden path relies on `services/dialogue/{Reasoner,AnimaComposer,select_final_response}`. A fix in one path does not propagate to the other. Consolidating on the service-layer design would close the largest remaining structural divergence in the codebase, halve the surface area where persona/drift bugs can hide, and make the two profiles genuinely share an abstraction rather than coexist. This is a behavior-sensitive change and needs its own design + full golden-soak coverage before landing — out of scope for a low-risk nightly pass, but the clear next structural win.
