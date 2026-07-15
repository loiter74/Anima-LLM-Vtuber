import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPanel from '../SettingsPanel.vue'

const socket = {
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}

vi.mock('@/composables/useSocket', () => ({ getSocket: () => socket }))

describe('SettingsPanel runtime status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 200,
        json: vi.fn().mockResolvedValue({
          schema_version: 1,
          status: 'ready',
          ready: true,
          service: 'anima',
          profile: 'production',
          version: 7,
          persona: 'anima.v0.1',
          effective_hash: 'effective',
          semantic_hash: 'semantic',
          components: {
            llm: {
              state: 'ready',
              ready: true,
              reason: null,
              configured: {
                name: 'deepseek',
                type: 'deepseek',
                provider: 'deepseek',
                model: 'deepseek-v4-flash',
                voice: null,
              },
              resolved: {
                type: 'deepseek',
                provider: 'deepseek',
                model: 'deepseek-v4-flash',
                voice: null,
              },
            },
            asr: {
              state: 'ready',
              ready: true,
              reason: null,
              configured: {
                name: 'mimo-asr',
                type: 'mimo',
                provider: 'mimo',
                model: 'mimo-v2.5-asr',
                voice: null,
              },
              resolved: { type: 'mimo', provider: 'mimo', model: 'mimo-v2.5-asr', voice: null },
            },
            tts: {
              state: 'ready',
              ready: true,
              reason: null,
              configured: {
                name: 'qwen-alice',
                type: 'remote',
                provider: 'qwen3',
                model: 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                voice: 'alice',
              },
              resolved: {
                type: 'remote',
                provider: 'qwen3',
                model: 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                voice: 'alice',
              },
            },
            vad: {
              state: 'ready',
              ready: true,
              reason: null,
              configured: {
                name: 'mimo-vad',
                type: 'mimo',
                provider: 'mimo',
                model: 'mimo-v2.5-asr',
                voice: null,
              },
              resolved: { type: 'mimo', provider: 'mimo', model: 'mimo-v2.5-asr', voice: null },
            },
          },
        }),
      }),
    )
  })

  it('renders separate configured and resolved ASR/TTS identities', async () => {
    const wrapper = mount(SettingsPanel, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()

    const asr = wrapper.get('[data-service="asr"]').text()
    const tts = wrapper.get('[data-service="tts"]').text()
    expect(asr).toContain('配置')
    expect(asr).toContain('实际')
    expect(asr).toContain('mimo-v2.5-asr')
    expect(tts).toContain('Qwen/Qwen3-TTS-12Hz-0.6B-Base')
    expect(tts).toContain('alice')
    expect(asr).not.toEqual(tts)
  })
})
