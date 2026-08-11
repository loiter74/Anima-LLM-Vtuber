import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MusicCard from './MusicCard.vue'
import { useSingingStore } from '@/stores/singing'
import { readSingingPlayback } from '@/singing/playback-sync'

vi.mock('@/composables/useSinging', () => ({
  useSinging: () => ({ process: vi.fn(), cancel: vi.fn() }),
}))
vi.mock('@/components/live2d/useLipSync', () => ({
  startLipSync: vi.fn(),
  stopLipSync: vi.fn(),
}))

describe('MusicCard live playback control', () => {
  let pinia: ReturnType<typeof createPinia>

  beforeEach(() => {
    localStorage.clear()
    pinia = createPinia()
    setActivePinia(pinia)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('publishes dashboard play and pause commands for live', async () => {
    const store = useSingingStore()
    store.setResult({
      task_id: 'dashboard-task',
      audio_url: '/song_final.wav',
      vocals_url: '/song_vocals.wav',
      original_url: '/song_original.wav',
      subtitle_url: '',
      tts_audio_url: '',
      video_title: '完整歌曲',
      duration: 240,
      lyrics: [],
      volumes: [0.1, 0.6],
    })
    const wrapper = mount(MusicCard, {
      global: {
        plugins: [pinia],
        stubs: {
          WaveformDisplay: { template: '<div />', methods: { connectAudio: vi.fn() } },
          ProcessTimeline: true,
        },
      },
    })

    await wrapper.get('audio').trigger('loadedmetadata')
    await wrapper.get('[aria-label="播放RVC 混音"]').trigger('click')

    expect(readSingingPlayback()).toMatchObject({
      taskId: 'dashboard-task',
      track: 'mix',
      audioUrl: '/song_final.wav',
      volumes: [0.1, 0.6],
      state: 'playing',
    })

    await wrapper.get('[aria-label="暂停RVC 混音"]').trigger('click')
    expect(readSingingPlayback()).toMatchObject({ state: 'paused' })
    wrapper.unmount()
  })
})
