// @vitest-environment node

import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TtsReviewClient } from '../scripts/review/tts-review-client'
import type { ReviewAttemptContext } from '../scripts/review/registry'

const roots: string[] = []

function acceptedPayload() {
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
      pcm_bytes: 4,
      complete: true,
    },
    audio_wav: '/artifacts/audio.wav',
    backend_report: '/artifacts/backend.json',
    mouth_timeline: [0.1, 0.5],
  }
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})

describe('TtsReviewClient', () => {
  it('owns authenticated synthesis and artifact downloads without exposing the token', async () => {
    const runDir = await mkdtemp(join(tmpdir(), 'animetta-tts-review-'))
    roots.push(runDir)
    const fetcher = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/v1/review/synthesize')) {
        expect(init?.headers).toMatchObject({ authorization: 'Bearer secret-token' })
        return new Response(JSON.stringify(acceptedPayload()), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url.endsWith('/audio.wav')) return new Response(new Uint8Array([1, 2, 3, 4]))
      if (url.endsWith('/backend.json')) return new Response('{"safe":true}')
      throw new Error(`unexpected URL: ${url}`)
    })
    const context: ReviewAttemptContext = {
      runId: 'run',
      runDir,
      repositoryDir: runDir,
      baseUrl: 'http://127.0.0.1:3000',
      sceneId: 'semantic-catalog',
      attempt: 1,
    }
    const client = new TtsReviewClient('http://127.0.0.1:8765', 'secret-token', fetcher)

    const result = await client.synthesize(context, {
      sceneId: 'live2d-calm',
      artifactKey: 'calm',
    })

    expect(result.audioUrl).toBe('http://127.0.0.1:8765/artifacts/audio.wav')
    expect(await readFile(result.audioWav)).toEqual(Buffer.from([1, 2, 3, 4]))
    expect(await readFile(result.backendReport, 'utf8')).toBe('{"safe":true}')
    expect(JSON.stringify(result)).not.toContain('secret-token')
  })
})
