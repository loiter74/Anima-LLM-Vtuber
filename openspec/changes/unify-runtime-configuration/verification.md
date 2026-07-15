# Verification Matrix

This matrix is the source-level and runtime audit for every scenario in the change. A
single evidence source can cover multiple scenarios only when the asserted behavior is
identical; every scenario remains named explicitly below.

Final completeness audit: all 75 specification scenarios are represented by a named
row below, with zero missing scenarios. Every row is backed by an executable contract,
current generated evidence, or both, and every result is PASS.

## Runtime configuration manifest

| Scenario | Evidence | Result |
|---|---|---|
| Standard runtime bootstrap | `tests/config/test_runtime_manifest.py::test_repository_manifest_resolves_every_declared_profile`; `tests/core/test_effective_config_propagation.py` | PASS |
| Legacy runtime source remains | `tests/deployment/test_legacy_runtime_gate.py::test_fixture_driven_source_gate_rejects_legacy_selectors` | PASS |
| Unsupported manifest structure | `test_cfg_004_unknown_schema_or_fields_are_rejected`, `test_cfg_005_yaml_merge_keys_are_rejected_before_safe_load`, and inheritance/schema cases in `tests/config/test_runtime_manifest.py` | PASS |
| Profile is missing or unknown | `test_cfg_002_profile_is_mandatory_and_must_exist` | PASS |
| Test profile resolves | `test_cfg_001_profiles_resolve_exact_service_references` | PASS |
| Smoke profile resolves | `test_cfg_001_profiles_resolve_exact_service_references`; `evidence/runtime-config/real-smoke/real-smoke-20260713T191249Z.json` | PASS |
| Production profile resolves | `test_cfg_001_profiles_resolve_exact_service_references`; final Docker `/ready` reports `production`, effective `a61e805d...`, semantic `c93e8487...` | PASS |
| Incomplete profile | `test_cfg_003_profile_requires_all_service_references` | PASS |
| Required secret and endpoint are supplied | `test_cfg_007_only_selected_endpoints_and_secrets_are_expanded`, `test_cfg_008_required_selected_secret_must_be_present`, and endpoint companion | PASS |
| Expansion appears in a business field | `test_cfg_008_business_fields_reject_environment_expansion` | PASS |
| Legacy selector is present | `test_cfg_009_legacy_selectors_fail_with_migration_guidance` and `tests/deployment/test_legacy_runtime_gate.py` | PASS |
| Consumers inspect active configuration | `tests/core/test_effective_config_propagation.py`; `test_cfg_012_public_status_is_sanitized_and_separates_provider_identities` | PASS |
| Consumer attempts mutation | `test_cfg_010_effective_config_and_nested_provider_data_are_immutable` and typed-provider immutability cases | PASS |
| Effective and semantic hashes are computed | all `test_cfg_011_*` cases | PASS |
| Public configuration is requested | `test_cfg_012_public_status_is_sanitized_and_separates_provider_identities`; frontend status tests | PASS |
| Real profile declares Mock | `test_cfg_006_real_profiles_reject_explicit_mock` | PASS |
| Real provider cannot be constructed | strict-provider cases in `tests/core/test_service_context.py`, `tests/core/test_service_pool.py`, and provider factory tests | PASS |
| Configured and resolved identities differ | `tests/core/test_effective_runtime_readiness.py::test_remote_identity_mismatch_fails_readiness_with_sanitized_cause` | PASS |
| Browser establishes a connection | `frontend/src/composables/__tests__/useSocket.same-origin.test.ts`; fresh Playwright capture | PASS |
| Settings display provider status | `frontend/src/components/settings/__tests__/SettingsPanel.runtime-config.test.ts`; `evidence/runtime-config/production-settings-final.png` shows exact DeepSeek and Qwen3 Alice rows plus semantic hash | PASS |
| Same profile runs in different topologies | `tests/deployment/test_runtime_topology.py::test_cpu_and_core_compose_choose_only_supported_profiles` | PASS |
| Deployment descriptor selects a provider | `test_deployment_descriptors_do_not_select_business_providers` proves descriptors cannot select one | PASS |
| Critical configuration suite runs | 79 focused tests; `manifest.py` 389 statements and 86 branches at 100%, 5.35 seconds | PASS |
| Test profile E2E runs with network blocked | explicit Mock construction and fail-closed policy cases in manifest, ServiceContext, ASR/TTS/VAD factory tests | PASS |
| Smoke profile gate runs | `scripts/smoke_real_profile.py`; real-smoke JSON records DeepSeek/MiMo LLM, ASR, TTS, and VAD in 9.357 seconds with zero Mock | PASS |

## ServicePool

| Scenario | Evidence | Result |
|---|---|---|
| Multiple sessions share engines | shared-instance cases in `tests/core/test_service_pool.py` and `tests/core/test_shared_memory_runtime.py` | PASS |
| Each session has own VAD and Memory | lifecycle/ownership cases in `tests/core/test_service_context.py` and `tests/core/test_service_pool.py` | PASS |
| MinecraftBridge accesses LLM via ServicePool | `tests/orchestration/server/handlers/test_minecraft_voyager_wiring.py` | PASS |
| Graceful degradation when ServicePool unavailable | unavailable/fail-closed cases in `tests/core/test_service_pool.py` and readiness tests | PASS |
| ServicePool initializes from configuration | `tests/core/test_effective_config_propagation.py`; `tests/core/test_service_pool.py` | PASS |
| Real service construction fails | strict initialization failure/rollback cases in `tests/core/test_runtime_readiness.py` | PASS |
| Lightweight LLM fields update on reload | `test_reload_allows_lightweight_llm_fields_but_preserves_engine_identity` | PASS |
| Shared LLM prompt updates on reload | `test_apply_runtime_config_updates_shared_snapshot_version_hashes_and_prompt` | PASS |
| LLM identity change is requested | `test_reload_rejects_restart_required_lifecycle_changes` | PASS |
| Reload does not recreate shared engines | reloader and proxy-target identity cases in `tests/config/test_runtime_config_reloader.py` | PASS |
| Reload failure leaves shared engines unchanged | invalid-persona/config preservation cases in reloader and reload API tests | PASS |
| All services resolve as configured | `tests/core/test_effective_runtime_readiness.py`; final production `/ready` has exact configured/resolved LLM, ASR, TTS, and VAD identities | PASS |
| Service identity mismatches | sanitized mismatch readiness tests for remote TTS | PASS |

## Runtime configuration reload

| Scenario | Evidence | Result |
|---|---|---|
| Successful reload swaps active config | `test_reload_success_replaces_persona_snapshot_and_increments_version` | PASS |
| Invalid persona preserves previous config | `test_reload_invalid_persona_preserves_previous_immutable_snapshot` | PASS |
| Invalid lightweight LLM config preserves previous config | reload validation and preserved-result cases in `tests/config/test_runtime_config_reloader.py` | PASS |
| Provider lifecycle field changes | `test_reload_rejects_restart_required_lifecycle_changes` | PASS |
| Active session contexts receive reloaded config | `tests/orchestration/server/test_config_reload_api.py::test_apply_reloaded_config_updates_existing_contexts` | PASS |
| Route handlers receive reloaded config | `test_reload_config_endpoint_applies_reloaded_config_to_contexts` and route-handler propagation tests | PASS |
| Active LLM prompt is refreshed when supported | `test_apply_runtime_config_updates_shared_snapshot_version_hashes_and_prompt` | PASS |
| Caller receives success metadata | `test_reload_config_endpoint_returns_structured_success` | PASS |
| Caller receives preserved-config error metadata | `test_reload_config_endpoint_returns_400_on_validation_failure` | PASS |
| Caller receives restart metadata | exact restart-path cases in `tests/config/test_runtime_config_reloader.py` | PASS |

## Component health and readiness

| Scenario | Evidence | Result |
|---|---|---|
| Process is alive but observation is degraded | `test_cache_fails_closed_before_first_refresh`, `test_each_local_component_degradation_fails_cached_readiness`, and cheap-health tests | PASS |
| Process is alive but provider identity is invalid | exact identity mismatch readiness test | PASS |
| Observation ledger is writable | `test_observation_read_only_probe_fails_component_health` plus `test_real_ledger_commit_and_prometheus_delta_feed_cached_readiness` prove a real SQLite commit | PASS |
| Memory index is degraded | `test_memory_backlog_alone_is_reported_as_degraded`, backlog/error coverage, and cached degradation coverage | PASS |
| Required ServicePool is not initialized | `test_missing_service_pool_snapshot_fails_closed` | PASS |
| Prometheus endpoint is reachable but inactive | `test_unchanged_metrics_fail_component_health` and the real ledger/Prometheus controlled-delta integration test | PASS |
| Required remote TTS identity matches | `test_production_remote_tts_requires_exact_qwen_provider_model_and_voice`; authenticated Compose-network `/ready` returns qwen3 / 0.6B Base / Alice / 24 kHz / pinned revision | PASS |
| EffectiveConfig snapshot is stale or mismatched | `test_stale_config_snapshot_fails_closed` | PASS |
| All required components are ready | final production Docker `/health`, `/ready`, and frontend all return HTTP 200; both containers healthy with restart=0 and OOM=false | PASS |
| Required component is not ready | `test_ready_merges_cached_required_local_component_degradation` and `test_required_remote_tts_outage_and_recovery_refresh_cached_readiness`; production Qwen stop/start rehearsal | PASS |

## Remote TTS service

| Scenario | Evidence | Result |
|---|---|---|
| Liveness is requested | `test_health_is_cheap_and_does_not_preload_or_synthesize` | PASS |
| Service is fully ready | `test_preload_publishes_exact_ready_and_identity_contracts`; final warmup48 completes in 15.229 seconds (180,524 bytes) and authenticated `/ready` is exact | PASS |
| Dependency is not ready | `test_ready_is_cached_and_identity_is_unavailable_before_preload` and sanitized preload failure | PASS |
| Alice synthesis succeeds | contract test; final fresh browser turn produces a 180,524-byte playable WAV at 13.140 seconds with no `play()` error | PASS |
| Request identity is unsupported | parameterized typed-4xx identity contract test | PASS |
| Synthesis fails | generation and empty-audio typed failure tests | PASS |
| Concurrent requests exceed capacity | `test_capacity_is_bounded_and_request_identities_do_not_cross` | PASS |
| Expected identity is ready | `test_matching_readiness_publishes_configured_and_resolved_identity` | PASS |
| Remote identity differs | parameterized remote readiness mismatch test | PASS |
| Remote call fails or is malformed | HTTP failure, timeout, malformed response, crossed request-ID, MIME, and empty-audio contract tests | PASS |
| Production synthesis times out | `test_synthesize_maps_network_timeout`; orchestration typed-degradation tests | PASS |
| Next turn follows a degradation | final same-browser rehearsal: text 995 ms, typed `unavailable` at 8.901 seconds with no audio; after Qwen-only restart, text 1.078 seconds and playable audio 12.795 seconds without provider swap | PASS |
| Main image is inspected | core image is 0.3083 GiB and contains none of Torch, CUDA, Qwen, Whisper, Silero, weights, or Alice assets | PASS |
| Production Compose starts | `artifacts/test-impact/release-final/release-runtime.json`: full uncached dual-image release gate PASS in 56 minutes 31.9 seconds; exact image fingerprints; `/health`, `/ready`, and frontend HTTP 200; both containers healthy with restart=0 | PASS |
| Fake contract suite runs | 55 provider-contract tests passed in 4.74 seconds with no Mock construction | PASS |
| Clean production soak runs | `evidence/runtime-config/production-soak-final/golden-soak-20260714T162212Z.json`: PASS, 600.014 seconds, 12 turns, text p95 3.847 seconds, media p95 16.301 seconds, zero degradation/disconnect/log violations | PASS |
| Browser acceptance runs | final production captures plus `artifacts/test-impact/final-qa-independent-20260715/evidence.json`: new context/page, exact provider rows, completed Chinese turn, one resolved-and-ended audio play, and zero console/page/request/HTTP errors | PASS |

## Repository-wide regression gates

| Gate | Result |
|---|---|
| Python default suite | 4387 passed, 33 skipped, 2 xfailed; 77.80% coverage on Python 3.13 |
| Related TTS/ServiceContext suite | Qwen contract, remote client, ServiceContext, graph output/degradation, deployment topology, and full-suite coverage all PASS |
| Ruff | PASS after final source/test cleanup |
| Mypy | 404 source files, zero issues |
| Frontend | 37 files / 297 tests; `vue-tsc --noEmit`; Vite production build |
| Secret/static migration scan | no plaintext secrets; six focused security/migration tests passed |
| OpenSpec strict validation | `openspec validate unify-runtime-configuration --strict` PASS |
