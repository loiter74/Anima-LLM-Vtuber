const ACCEPTED_PROVIDER = 'qwen3-tts-gguf-host'
const MAX_MOUTH_TIMELINE_FRAMES = 3_000

export interface TtsHarnessAssertion {
  name: string
  passed: boolean
}

export interface TtsFailoverHarnessResponse {
  report: {
    actual_backend: string
    actual_provider: string
    primary_error_category: string
    readiness: {
      ready: boolean
      degraded: boolean
      active_backend: string
      circuit: { state: string }
    }
    first_audio_seconds: number
    rtf: number
    sample_rate: number
    channels: number
    sample_width_bytes: number
    pcm_bytes: number
    complete: boolean
    performance?: {
      passed: boolean
      enforced: boolean
    }
  }
  audio_wav: string
  backend_report: string
  mouth_timeline: number[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseTtsFailoverHarnessResponse(
  value: unknown,
  options: { performancePolicy?: 'strict' | 'observe' } = {},
): TtsFailoverHarnessResponse {
  if (!isRecord(value) || !isRecord(value.report)) {
    throw new Error('TTS failover harness did not satisfy its acceptance contract')
  }
  const payload = value as unknown as TtsFailoverHarnessResponse
  const report = payload.report
  const validMouthTimeline =
    Array.isArray(payload.mouth_timeline) &&
    payload.mouth_timeline.length > 0 &&
    payload.mouth_timeline.length <= MAX_MOUTH_TIMELINE_FRAMES &&
    payload.mouth_timeline.every((volume) => Number.isFinite(volume) && volume >= 0 && volume <= 1)
  const validPerformance =
    Number.isFinite(report.first_audio_seconds) &&
    report.first_audio_seconds >= 0 &&
    Number.isFinite(report.rtf) &&
    report.rtf >= 0 &&
    (options.performancePolicy === 'observe' ||
      (report.first_audio_seconds <= 0.75 && report.rtf <= 0.35))
  const valid =
    report.actual_backend === 'fallback' &&
    report.actual_provider === ACCEPTED_PROVIDER &&
    report.primary_error_category === 'billing' &&
    report.readiness?.ready === true &&
    report.readiness.degraded === true &&
    report.readiness.active_backend === 'fallback' &&
    typeof report.readiness.circuit?.state === 'string' &&
    report.sample_rate === 24_000 &&
    report.channels === 1 &&
    report.sample_width_bytes === 2 &&
    Number.isInteger(report.pcm_bytes) &&
    report.pcm_bytes > 0 &&
    report.pcm_bytes % 2 === 0 &&
    report.complete === true &&
    validPerformance &&
    typeof payload.audio_wav === 'string' &&
    payload.audio_wav.startsWith('/') &&
    typeof payload.backend_report === 'string' &&
    payload.backend_report.startsWith('/') &&
    validMouthTimeline
  if (!valid) throw new Error('TTS failover harness did not satisfy its acceptance contract')
  return payload
}

export function buildTtsHarnessAssertions(
  payload: TtsFailoverHarnessResponse,
  options: { includePerformance?: boolean } = {},
): TtsHarnessAssertion[] {
  const { report } = payload
  const assertions: TtsHarnessAssertion[] = [
    { name: 'primary-error:billing', passed: report.primary_error_category === 'billing' },
    { name: 'actual-backend:fallback', passed: report.actual_backend === 'fallback' },
    {
      name: 'readiness:ready-degraded',
      passed:
        report.readiness.ready === true &&
        report.readiness.degraded === true &&
        report.readiness.active_backend === 'fallback',
    },
    {
      name: 'pcm:complete-24khz-mono',
      passed:
        report.complete === true &&
        report.sample_rate === 24_000 &&
        report.channels === 1 &&
        report.sample_width_bytes === 2 &&
        Number.isInteger(report.pcm_bytes) &&
        report.pcm_bytes > 0 &&
        report.pcm_bytes % 2 === 0,
    },
  ]
  if (options.includePerformance !== false) {
    assertions.push({
      name: 'first-audio<=0.75s',
      passed:
        Number.isFinite(report.first_audio_seconds) &&
        report.first_audio_seconds >= 0 &&
        report.first_audio_seconds <= 0.75,
    })
    assertions.push({
      name: 'rtf<=0.35',
      passed: Number.isFinite(report.rtf) && report.rtf >= 0 && report.rtf <= 0.35,
    })
  }
  return assertions
}
