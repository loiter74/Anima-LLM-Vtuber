## Context

The existing livestream evaluator writes privacy-safe schema v1 datasets and replays them through the Gateway boundary, but it deliberately preserves source chat content. The three selected replay sources contain Chinese Bilibili comments and English Twitch chat with emotes, copy spam, ambiguous fragments, and repeated messages. They need an auditable transformation before they can measure Chinese interaction quality.

The cleaner operates only on already-sanitized datasets. Source directories remain immutable, generated data stays under the ignored runtime data root, and evidence must never duplicate the original foreign text. The production DeepSeek provider is available through Animetta's LLM factory, while tests require a deterministic injected processor.

## Goals / Non-Goals

**Goals:**

- Produce Chinese-dominant real-only and clearly marked enriched variants without changing source datasets.
- Remove non-actionable noise while preserving understandable questions, instructions, opinions, greetings, emotions, and contextual replies.
- Preserve a reproducible high tier after cleaning by compressing only the continuous relative timeline when required.
- Derive a reproducible medium tier exclusively from cleaned real high-heat events.
- Preserve schema v1 validation/replay while adding strict schema v2 provenance and rolling workload rules.
- Emit deterministic reports and review samples that can be audited without copying source text.

**Non-Goals:**

- Retrain or fine-tune a language model.
- Re-identify viewers, persist source URLs, or restore raw platform payloads.
- Generate entry, follow, like, popularity, or connection events.
- Add a frontend control surface or change the Socket.IO danmaku contract.

## Decisions

### 1. Use a two-stage balanced cleaner with an injected semantic processor

Deterministic rules reject empty content, symbol-only lines, laughter-only lines, standalone emotes, meaningless abbreviations, same-actor short-window duplicates, and repeated copypasta. Clear Chinese messages are kept and assigned an intent locally. Remaining candidates are sent in batches of at most 40 with up to three preceding and three following messages from a 20-second context window.

The production processor wraps `LLMFactory` in strict mode, uses temperature zero and structured JSON, limits concurrency to four, and retries invalid responses three times. Tests inject a deterministic processor. A mock or malformed production response fails the run instead of silently emitting partially cleaned data.

Pure rules were rejected because Twitch slang and contextual fragments cannot be classified reliably. Sending every event independently to the LLM was rejected because it loses context, costs more, and makes duplicate translations inconsistent.

### 2. Keep v1 immutable and add a provenance-aware schema v2

Schema v2 keeps the `LivestreamEvent` shape and stores evaluation metadata in the whitelisted payload. Replyable real events carry `origin=real`, `source_sequence`, and `intent`. Synthetic events carry `origin=synthetic`, `scenario`, and `parent_sequence`, use `synthetic_NNNN` actors, and start visible text with `[合成补充]`.

The manifest records the parent dataset ID and checksum, cleaning/prompt/model versions, fixed seed, result counts, variant, ratio, and derivation settings. `workload` is calculated from real replyable events; `effective_workload` includes synthetic events. Schema v1 retains its aligned-minute compatibility calculation, while schema v2 uses 60-second windows sampled every second.

Adding top-level event fields was rejected because it would broaden production message contracts. Prefix-only marking was rejected because it is not reliable for machine accounting.

### 3. Publish output atomically as paired variants

The command validates the source, writes staging siblings, validates parent linkage, language, provenance, counts, checksums, workload, and synthetic ratio, then renames both outputs into place. Existing output directories are never overwritten. Failure removes staging directories and leaves no published half-pair.

The real variant contains only retained source events. The enriched variant copies the real events and adds exactly `ceil(real_replyable_count * ratio)` synthetic replyable events. Monetary events are about one percent of the real count, clamped to 6–30 and to the total synthetic budget, with gifts and super chats split approximately 2:1.

### 4. Calibrate cleaned high heat with bounded real-only time compression

Cleaning can remove enough Twitch emote and spam traffic for a valid high-heat source to fall below the high-tier rolling-window threshold. The pipeline tests deterministic compression factors from 1.00 through 2.00 in 0.05 steps, keeps all retained real events in their original order, scales only their relative offsets, and accepts the first factor for which at least 80 percent of rolling windows contain 61–300 real replyable events. The calibrated timeline must remain at least 90 minutes long so the canonical 30-, 60-, and 80-minute burst windows can complete, and the manifest records the factor and original duration.

Synthetic repair and cross-room concatenation were rejected because both would make real workload qualification artificial. Compression above 2x was rejected because it would materially distort conversational pacing; if no bounded factor qualifies, generation fails.

### 5. Derive medium heat after cleaning and before enrichment

The sampler groups real events by aligned minute, intent, and actor, then selects toward 40 replyable events per minute with a fixed seed. It preserves original offsets and source sequences, applies a chronological upper-bound pass for every rolling window, and fills underrepresented windows from unselected real candidates. The result is accepted only if at least 80 percent of rolling windows contain 11–60 real replyable events.

Synthetic repair was rejected because it would make the canonical heat tier depend on generated traffic.

### 6. Generate context-bound scenarios from a fixed catalog

Synthetic danmaku rotate deterministically across direct questions, follow-ups, correction/challenge, topic shifts, emotional support, and privacy/safety boundaries. Gifts and super chats use Chinese allowlisted names and bounded numeric payloads. Insertions occur after selected real parent events, are sorted by offset plus deterministic tie-breaker, and are resequenced.

All generated text passes the existing privacy sanitizer, the same Chinese-dominance validator, and the synthetic marker validator. The decision cache stores only source checksum, sequence, text hash, decision, intent, and Chinese output.

### 7. Separate dataset artifacts from audit evidence

Generated datasets contain only manifests and event JSONL. Cleaning JSON/Markdown summaries and deterministic review CSVs are written under `artifacts/livestream-eval/<dataset-id>-cleaning/`. Reports expose retention, drop reasons, translation counts, intents, synthetic scenarios, and both workload views without copying source text.

### 8. Acquire anonymous Twitch VOD chat without persisting source identity

The capture CLI can read public Twitch VOD chat anonymously through the public GraphQL endpoint. It walks fixed five-second pages, refines dense pages before deduplication, converts platform offsets to a dataset-relative monotonic timeline, and passes every selected event directly through the existing in-memory sanitizer and schema-v1 writer. The VOD identifier, commenter login/ID, comment ID, absolute timestamp, source URL, and raw GraphQL payload are never written.

For unusually dense recordings, the operator may enable a deterministic real-only quality prefilter and an exact rolling 60-second rate cap before persistence. The manifest records only the derivation kind, configured cap, prefilter flag, and observed/eligible/selected counts. It does not record the VOD identifier or another recoverable source locator. Synthetic events never participate in capture shaping.

## Risks / Trade-offs

- [Remote LLM output drifts] → Pin provider/model/prompt version, use temperature zero, cache accepted structured decisions, and verify repeat runs by checksum.
- [Aggressive filtering drops useful crowd context] → Apply only narrow deterministic drops globally; send ambiguous content with context to the semantic processor and produce seeded review samples.
- [Chinese validation rejects useful proper nouns] → Allow a small explicit proper-noun/acronym list while rejecting consecutive untranslated English sentences.
- [True rolling windows invalidate a high source after cleaning] → Try deterministic bounded real-only time compression, record the factor, and fail if no factor qualifies; never add synthetic events to repair canonical heat.
- [Large Twitch input triggers rate limits] → Deduplicate translation work by text hash, batch up to 40 entries, limit concurrency, retry boundedly, and resume from the hash-only cache.
- [Schema v2 breaks older callers] → Keep v1 parsing and replay behavior unchanged and confine v2 metadata to optional payload and manifest fields.

## Migration Plan

1. Add v2 validation and tests while retaining v1 behavior.
2. Add the cleaner, semantic adapter, high-heat calibrator, medium sampler, enricher, reports, and CLI command.
3. Generate paired outputs into new runtime directories; do not migrate or overwrite v1 sources.
4. Validate and replay all outputs before selecting low/medium/high enriched baselines.
5. Roll back by deleting generated v2 directories and leaving capture/replay v1 paths unchanged.

## Open Questions

None.
