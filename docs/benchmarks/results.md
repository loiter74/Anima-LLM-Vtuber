# Benchmark Results
**Date:** 2026-05-10 11:51
**Mode:** quick

## Run Configuration

| Parameter | Value |
|-----------|-------|
| Turns | 5 |
| Concurrency | 1 |
| Provider | mock |
| QPS | 20449.90 turns/sec |

## E2E Latency Summary

| Scenario | Iterations | P50 | P95 | P99 | Min | Max |
|----------|-----------|-----|-----|-----|-----|-----|
| text_e2e_mock | 5 | 0ms | 0ms | 0ms | 0ms | 0ms |

| **Std** | | 0ms | | | | |

## Per-Node Timing (StatsStore)

_No node timing data available._

### Sub-Node Timing

| Step | Calls | Avg (ms) |
|------|-------|----------|
| asr.preload | 31 | 31609 |
| tts.synthesize | 73 | 7371 |
| llm.chat | 31 | 5004 |
| llm.chat_with_tools | 77 | 3111 |
| llm.chat_stream | 4 | 1623 |
| asr.transcribe | 24 | 993 |
| asr.close | 6 | 28 |
| llm.close | 6 | 1 |
| tts.close | 6 | 1 |
| vad.close | 51 | 0 |

