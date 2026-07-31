## 1. Change artifacts

- [x] 1.1 Create proposal, design, and capability specifications for Chinese cleaning and enrichment
- [x] 1.2 Create and validate the Obsidian Canvas cleaning architecture diagram

## 2. Schema v2 and validation

- [x] 2.1 Add failing tests for schema v1 compatibility, schema v2 manifest provenance, real/effective workload, and one-second rolling windows
- [x] 2.2 Add failing tests for Chinese dominance, parent linkage, synthetic actor/prefix/payload consistency, ratio, counts, and checksum rejection
- [x] 2.3 Implement schema v2 writing and validation while preserving schema v1 capture and replay behavior

## 3. Balanced cleaning and localization

- [x] 3.1 Add failing tests for deterministic noise removal, intent preservation, contextual ambiguity, same-actor deduplication, and cross-actor reactions
- [x] 3.2 Implement deterministic balanced rules, context windows, decision models, and hash-only decision cache
- [x] 3.3 Add failing tests for strict batched LLM processing, retry limits, Chinese localization, proper nouns, malformed responses, and mock rejection
- [x] 3.4 Implement the strict DeepSeek semantic adapter with injected deterministic test support

## 4. Medium derivation and scenario enrichment

- [x] 4.1 Add failing tests for fixed-seed medium sampling, original offsets, source sequences, rolling qualification, and unqualified failure
- [x] 4.2 Implement the real-only medium sampler targeting 40 replyable messages per minute
- [x] 4.3 Add failing tests and implement bounded deterministic real-only high-heat time compression with duration and qualification gates
- [x] 4.4 Add failing tests for exact 10 percent enrichment, monetary clamps, scenario rotation, provenance, sorting, and checksum repeatability
- [x] 4.5 Implement context-bound synthetic danmaku, gifts, and super chats with approved markers and privacy/language validation

## 5. CLI, atomic publication, and evidence

- [x] 5.1 Add failing tests for the clean CLI contract, immutable inputs, paired atomic publication, cleanup on failure, and no overwrite
- [x] 5.2 Implement clean orchestration, CLI arguments, parent discovery, output naming, and atomic staging publication
- [x] 5.3 Implement JSON, Markdown, deterministic review CSV, and real/synthetic reporting without source-text duplication

## 6. Dataset generation and verification

- [x] 6.1 Generate paired v2 outputs for the two valid Bilibili sources and the Twitch high source, plus paired derived medium outputs
- [x] 6.2 Validate all eight outputs and verify Chinese, provenance, ratio, checksum, heat, and deterministic repeatability gates
- [x] 6.3 Run focused Python 3.13 tests, `make quality-validate`, `make test-affected`, and 10x transport replay for all outputs
- [x] 6.4 Run representative low, medium, and high enriched full-stack replays using the host-local persistent-Qwen protocol and fresh QA/Playwright evidence

## 7. Final high-source replacement and burst proof

- [x] 7.1 Add tested anonymous Twitch VOD capture with dense-page refinement, immediate sanitization, deterministic real-only prefiltering, exact rolling rate capping, and atomic failure cleanup
- [x] 7.2 Require cleaned high-heat timelines to remain at least 90 minutes and reject configured burst profiles that cannot finish every window
- [x] 7.3 Generate and validate the replacement 96-minute high real/enriched pair and its real-only medium pair, then pass all four independent-process 10x transport runs
- [x] 7.4 Run the replacement high enriched dataset at 1x with every configured burst window and collect fresh full-stack, runtime, report, and Playwright evidence
- [x] 7.5 Re-run the current Python 3.13 impact-aware quality gates and update the evidence audit with the replacement baselines

## 8. Independent review hardening

- [x] 8.1 Enforce schema-v2 top-level/payload allowlists, real-event provenance, banned manifest keys, workload equality, cleaning counts, and complete processing metadata
- [x] 8.2 Route Chinese-dominant fragments without a recognizable local intent through contextual semantic filtering instead of defaulting them to opinions
- [x] 8.3 Persist origin, source sequence, intent, scenario, and parent sequence in conversation/report/manual-review evidence with separate real/synthetic outcomes
- [x] 8.4 Reject event-sink accounting failures, remove fabricated safety zeros, and require server-targeted RSS in full-stack runs
- [x] 8.5 Replace the historical 1x evidence with new low, medium, and high server-RSS runs and fresh QA evidence
- [ ] 8.6 Complete human scoring and safety review before freezing the live-readiness baseline
- [x] 8.7 Add post-run safety review forms, exact 30-row readiness enforcement, and hash-only advisory content audits
