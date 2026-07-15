import { describe, expect, it, vi } from 'vitest'
import { fetchRuntimeStatus } from '../runtimeStatus'

describe('fetchRuntimeStatus', () => {
  it('uses the same-origin relative readiness endpoint and keeps ASR/TTS distinct', async () => {
    const payload = {
      components: {
        asr: { configured: { model: 'mimo-v2.5-asr' } },
        tts: { configured: { model: 'mimo-v2.5-tts' } },
      },
    }
    const fetcher = vi.fn().mockResolvedValue({
      json: vi.fn().mockResolvedValue(payload),
    })

    const result = await fetchRuntimeStatus(fetcher as unknown as typeof fetch)

    expect(fetcher).toHaveBeenCalledWith('/ready', {
      headers: { accept: 'application/json' },
    })
    expect(result.components.asr).not.toEqual(result.components.tts)
  })
})
