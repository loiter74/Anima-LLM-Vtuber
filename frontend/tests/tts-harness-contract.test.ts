import { describe, expect, it } from 'vitest'
import {
  buildTtsHarnessAssertions,
  parseTtsFailoverHarnessResponse,
  type TtsFailoverHarnessResponse,
} from '../scripts/review/tts-harness-contract'

function acceptedPayload(): TtsFailoverHarnessResponse {
  return {
    report: {
      actual_backend: 'fallback',
      actual_provider: 'qwen3-tts-gguf-host',
      primary_error_category: 'billing',
      readiness: {
        ready: true,
        degraded: true,
        active_backend: 'fallback',
        circuit: { state: 'open' },
      },
      first_audio_seconds: 0.4,
      rtf: 0.2,
      sample_rate: 24_000,
      channels: 1,
      sample_width_bytes: 2,
      pcm_bytes: 48_000,
      complete: true,
    },
    audio_wav: '/artifacts/audio.wav',
    backend_report: '/artifacts/backend.json',
    mouth_timeline: [0, 0.5, 1],
  }
}

describe('parseTtsFailoverHarnessResponse', () => {
  it('returns a fully accepted billing-to-fallback response', () => {
    expect(parseTtsFailoverHarnessResponse(acceptedPayload()).report.actual_backend).toBe(
      'fallback',
    )
  })

  it('derives every technical assertion from report values', () => {
    const payload = acceptedPayload()
    expect(buildTtsHarnessAssertions(payload).every(({ passed }) => passed)).toBe(true)

    payload.report.rtf = 0.5
    expect(buildTtsHarnessAssertions(payload)).toContainEqual({
      name: 'rtf<=0.35',
      passed: false,
    })
  })

  it.each([
    [
      'provider identity',
      (payload: TtsFailoverHarnessResponse) => (payload.report.actual_provider = 'other'),
    ],
    ['sample rate', (payload: TtsFailoverHarnessResponse) => (payload.report.sample_rate = 16_000)],
    ['odd PCM bytes', (payload: TtsFailoverHarnessResponse) => (payload.report.pcm_bytes = 3)],
    [
      'first audio',
      (payload: TtsFailoverHarnessResponse) => (payload.report.first_audio_seconds = 0.751),
    ],
    ['RTF', (payload: TtsFailoverHarnessResponse) => (payload.report.rtf = 0.351)],
    ['mouth timeline', (payload: TtsFailoverHarnessResponse) => (payload.mouth_timeline = [1.1])],
  ])('rejects an invalid %s contract', (_name, mutate) => {
    const payload = acceptedPayload()
    mutate(payload)
    expect(() => parseTtsFailoverHarnessResponse(payload)).toThrow(
      'TTS failover harness did not satisfy its acceptance contract',
    )
  })
})
