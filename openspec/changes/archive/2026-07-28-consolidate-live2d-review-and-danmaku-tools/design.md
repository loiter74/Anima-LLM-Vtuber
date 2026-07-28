## Context

The accepted Hiyori performance path currently exposes seven semantic bases and five accents in public TypeScript types while both backend and renderer normalize execution to three bases and no accent. Compatibility mappings are duplicated, unreachable profile offsets remain, and production and review stages construct similar model adapters independently. The TTS review lease also combines process lifecycle, HTTP access, evidence persistence, and feature catalogs. Three experimental live-room collectors bypass the existing normalized Bilibili gateway.

The workspace is intentionally dirty and contains the accepted three-expression behavior. This change must preserve those edits in place, the 60 ms mouth sampling, the three emotion-specific review speeches, and the frozen `text-boundaries` and `sparse` review fixtures.

## Goals / Non-Goals

**Goals:**

- Establish one canonical performance vocabulary on each side of the wire and a narrow deterministic compatibility boundary.
- Separate renderer state, model parameter resolution, transport adaptation, and review orchestration.
- Preserve historical evidence and existing single-artifact consumers while recording all named performance samples.
- Restore the historical-video collector and provide one maintainable live-room collector over the production gateway.
- Make impact-aware verification select focused coverage for the affected areas.

**Non-Goals:**

- Change Hiyori expression values, idle motion, mouth timing, TTS routing, voice, or performance thresholds.
- Build dynamic model discovery or a generic expression registry.
- Add a production fault-injection API or a new Bilibili transport.
- Rewrite unrelated dirty-worktree changes or frozen live-review scenes.

## Decisions

1. **Canonical values are distinct from compatibility inputs.** Backend and frontend expose only `calm`, `annoyed`, and `surprised`; the only accent is `none`. Older bases and accents remain private inputs to one normalizer per runtime. This prevents wire types and downstream profiles from inheriting deprecated values while retaining deterministic legacy behavior.

2. **The controller depends on a minimal profile contract.** The controller owns state transitions and timing. A profile resolves a canonical plan into bounded model offsets, and a model adapter owns parameter reads/writes. This is sufficient for another model without introducing a registry before a second profile exists.

3. **Named review samples extend, rather than replace, evidence.** `audioWav` and `backendReport` continue to reference the calm sample. An optional named sample map records every prepared WAV/report pair and is ignored by historical readers that do not know it.

4. **Review instrumentation is non-visual.** The Live2D performance review keeps its datasets and audio element in a hidden host so Playwright can validate the sequence without adding semantic labels or status chrome to the production-shaped OBS frame.

4. **The harness is split by responsibility.** A lease owns the process and secret. A client owns authenticated requests, validation, and downloads. Plugins supply typed scene descriptors and assemble page parameters, assertions, and observations. Assertions are derived from validated response data.

5. **Live collection reuses `DanmakuServiceGateway` directly.** The CLI does not need `LivestreamSession` admission and switching policies; it needs the existing normalized messages, status callback, reconnect behavior, and start/stop lifecycle. A separate writer owns CSV and JSONL persistence and is injected for tests.

6. **Generated danmaku files are local artifacts.** The output directory is ignored and current experimental output is removed. Credentials are read only from `BILIBILI_SESSDATA`, never persisted or accepted as an argv value.

## Risks / Trade-offs

- **[Compatibility mappings drift between Python and TypeScript]** → Mirror the same canonical/legacy cases with contract tests and keep each mapping in one module per runtime.
- **[Evidence consumers assume one audio file]** → Preserve existing fields and schema version while adding only an optional sample map.
- **[Gateway callbacks arrive from a worker thread]** → Keep the writer synchronous, lock-protected, bounded to append operations, and close it only after the gateway stops.
- **[Refactor changes accepted visuals]** → Reuse current parameter values verbatim and require a fresh three-expression OBS replay before archival.
- **[Dirty workspace overlap]** → Patch only reviewed hunks, inspect diffs after each batch, and never reset or bulk-format unrelated files.

## Migration Plan

1. Add canonical contract tests and compatibility tests before moving implementation.
2. Introduce the profile/model adapter seam, move accepted values unchanged, then remove dead branches.
3. Add named evidence compatibility tests before splitting the harness.
4. Restore the historical collector from its current base semantics, add and test the separate live collector, then remove superseded experiments and generated output.
5. Run focused and impact-aware validation, collect fresh OBS evidence, obtain operator acceptance, and only then complete and archive this change.

Rollback is file-level: the public event shape remains version 1 and old evidence fields remain intact, so each subsystem can be reverted independently without data migration.

## Open Questions

None. The canonical vocabulary, compatibility behavior, evidence strategy, collector boundary, and verification checkpoint are fixed by the approved plan.
