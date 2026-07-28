import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { StructuredObservation } from './browser'
import type { ReviewAttemptContext } from './registry'
import {
  buildTtsHarnessAssertions,
  parseTtsFailoverHarnessResponse,
  type TtsFailoverHarnessResponse,
  type TtsHarnessAssertion,
} from './tts-harness-contract'

export interface TtsReviewSampleDescriptor {
  sceneId: string
  artifactKey?: string
}

export interface PreparedTtsReviewSample {
  payload: TtsFailoverHarnessResponse
  audioUrl: string
  audioWav: string
  backendReport: string
}

type Fetcher = (input: string | URL, init?: RequestInit) => Promise<Response>

export class TtsReviewClient {
  constructor(
    readonly baseUrl: string,
    private readonly token: string,
    private readonly fetcher: Fetcher = fetch,
  ) {}

  async assertReady(): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/ready`, {
      method: 'POST',
      headers: this.headers(),
      signal: AbortSignal.timeout(60_000),
    })
    if (!response.ok) throw new Error(`TTS failover harness readiness failed (${response.status})`)
    const payload = (await response.json()) as {
      readiness?: { active_backend?: string; primary?: { error_category?: string } }
    }
    if (
      payload.readiness?.active_backend !== 'fallback' ||
      payload.readiness.primary?.error_category !== 'billing'
    ) {
      throw new Error('TTS failover harness readiness identity mismatch')
    }
  }

  async synthesize(
    context: ReviewAttemptContext,
    descriptor: TtsReviewSampleDescriptor,
  ): Promise<PreparedTtsReviewSample> {
    const response = await this.fetcher(`${this.baseUrl}/v1/review/synthesize`, {
      method: 'POST',
      headers: { ...this.headers(), 'content-type': 'application/json' },
      body: JSON.stringify({ scene_id: descriptor.sceneId }),
      signal: AbortSignal.timeout(60_000),
    })
    if (!response.ok) throw new Error(`TTS failover attempt failed (${response.status})`)
    const payload = parseTtsFailoverHarnessResponse(await response.json())
    const evidenceDir = join(context.runDir, 'evidence')
    await mkdir(evidenceDir, { recursive: true })
    const stem = [context.sceneId, String(context.attempt).padStart(3, '0'), descriptor.artifactKey]
      .filter(Boolean)
      .join('-')
    const audioWav = join(evidenceDir, `${stem}-audio.wav`)
    const backendReport = join(evidenceDir, `${stem}-backend.json`)
    const [audioResponse, reportResponse] = await Promise.all([
      this.fetcher(new URL(payload.audio_wav, this.baseUrl)),
      this.fetcher(new URL(payload.backend_report, this.baseUrl)),
    ])
    if (!audioResponse.ok || !reportResponse.ok) {
      throw new Error('TTS failover artifacts could not be downloaded')
    }
    await Promise.all([
      writeFile(audioWav, Buffer.from(await audioResponse.arrayBuffer())),
      writeFile(backendReport, Buffer.from(await reportResponse.arrayBuffer())),
    ])
    return {
      payload,
      audioUrl: new URL(payload.audio_wav, this.baseUrl).href,
      audioWav,
      backendReport,
    }
  }

  private headers(): { authorization: string } {
    return { authorization: `Bearer ${this.token}` }
  }
}

export function ttsReviewPageParams(
  payload: TtsFailoverHarnessResponse,
  audioUrl: string,
): Record<string, string> {
  return {
    audio: audioUrl,
    backend: payload.report.actual_backend,
    provider: payload.report.actual_provider,
    firstAudio: payload.report.first_audio_seconds.toFixed(3),
    rtf: payload.report.rtf.toFixed(3),
    sampleRate: String(payload.report.sample_rate),
    mouthTimeline: JSON.stringify(payload.mouth_timeline),
  }
}

export function ttsReviewAssertions(
  payload: TtsFailoverHarnessResponse,
): readonly TtsHarnessAssertion[] {
  return buildTtsHarnessAssertions(payload)
}

export function ttsReviewObservations(
  payload: TtsFailoverHarnessResponse,
): readonly StructuredObservation[] {
  return [
    { name: 'actual_backend', value: payload.report.actual_backend },
    { name: 'primary_error_category', value: payload.report.primary_error_category },
    { name: 'first_audio', value: payload.report.first_audio_seconds, unit: 'seconds' },
    { name: 'rtf', value: payload.report.rtf },
    { name: 'pcm_bytes', value: payload.report.pcm_bytes, unit: 'bytes' },
  ]
}
