import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ConversationSandbox from '@/components/dashboard/ConversationSandbox.vue'
import PreflightDrawer from '@/components/dashboard/PreflightDrawer.vue'
import MemoryWorkspace from '@/components/memory/MemoryWorkspace.vue'
import MemeWorkspace from '@/components/meme/MemeWorkspace.vue'
import { Events } from '@/constants/socket-events'
import { useMemoryStore, type WikiPageEntry } from '@/stores/memory'

const socket = vi.hoisted(() => ({
  connected: true,
  emit: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  timeout: vi.fn(),
}))

const runtimeApi = vi.hoisted(() => ({ fetchRuntimeStatus: vi.fn() }))
vi.mock('@/composables/useSocket', () => ({ getSocket: () => socket }))
vi.mock('@/composables/useDanmaku', () => ({
  useDanmaku: () => ({
    connect: vi
      .fn()
      .mockResolvedValue({ accepted: true, state: 'live', error_code: null, message: '' }),
    disconnect: vi
      .fn()
      .mockResolvedValue({ accepted: true, state: 'stopped', error_code: null, message: '' }),
    updateRoom: vi
      .fn()
      .mockResolvedValue({ accepted: true, state: 'live', error_code: null, message: '' }),
  }),
}))
vi.mock('@/services/runtimeStatus', () => runtimeApi)

const memory: WikiPageEntry = {
  id: 'memory-1',
  path: 'viewer/rain-radio',
  title: '雨夜电台偏好',
  content: '观众喜欢雨夜电台和轻声聊天。',
  summary: '偏好雨夜电台',
  layer: 'semantic',
  page_type: 'concept',
  scope: 'viewer',
  visibility: 'internal',
  subject_ids: ['viewer-1'],
  origin: { source: 'livestream' },
  confidence: 0.9,
  salience: 0.8,
  trust_level: 0.8,
  retention_policy: 'normal',
  index_state: 'indexed',
  relations: [],
  tags: ['preference'],
  source_ids: [],
  version: 2,
  is_archived: false,
  occurred_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

async function flushPromises() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

describe('dashboard domain workspaces', () => {
  beforeEach(() => {
    socket.connected = true
    socket.emit.mockReset()
    socket.on.mockReset()
    socket.off.mockReset()
    socket.timeout.mockReset()
    socket.timeout.mockReturnValue(socket)
    runtimeApi.fetchRuntimeStatus.mockReset()
    runtimeApi.fetchRuntimeStatus.mockResolvedValue({
      components: {
        llm: {
          ready: true,
          reason: '',
          configured: { provider: 'mock' },
          resolved: { provider: 'mock' },
        },
        asr: {
          ready: true,
          reason: '',
          configured: { provider: 'mock' },
          resolved: { provider: 'mock' },
        },
        tts: {
          ready: true,
          reason: '',
          configured: { provider: 'mock' },
          resolved: { provider: 'mock' },
        },
        vad: {
          ready: true,
          reason: '',
          configured: { provider: 'mock' },
          resolved: { provider: 'mock' },
        },
      },
    })
  })

  afterEach(() => vi.useRealTimers())

  it('runs the conversation sandbox locally and records a zero-network boundary', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ConversationSandbox, { props: { modelValue: '验证这条记忆' } })
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '开始本地演练')!
      .trigger('click')
    await vi.runAllTimersAsync()

    expect(wrapper.text()).toContain('当前沙盒未连接模型')
    expect(wrapper.text()).toContain('网络请求')
    expect(wrapper.text()).toContain('公开输出')
  })

  it('keeps memory actions in the memory workspace and emits a sandbox draft', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useMemoryStore()
    store.wikiPages = [memory]
    store.fetchMemories = vi.fn().mockResolvedValue(undefined)
    store.organizeMemory = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(MemoryWorkspace, {
      global: {
        plugins: [pinia],
        stubs: { MemoryGraph: { template: '<div data-testid="memory-graph" />' } },
      },
    })
    await wrapper
      .findAll('button')
      .find((button) => button.text().includes('雨夜电台偏好'))!
      .trigger('click')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '发送到对话沙盒')!
      .trigger('click')

    expect(wrapper.emitted('send-to-sandbox')).toEqual([[memory.content]])
    expect(wrapper.text()).not.toContain('手动添加梗')
  })

  it('loads, reviews, and exports Meme candidates through the Meme protocol', async () => {
    socket.emit.mockImplementation(
      (event: string, _payload: unknown, callback?: (...args: unknown[]) => void) => {
        if (event === Events.MEME.LIST) {
          callback?.({
            memes: [
              {
                id: 'meme-1',
                text: '需求真的不会再改了',
                context_hint: '直播开发现场',
                tags: ['反差'],
                source_platform: 'bilibili',
                base_score: 0.8,
                cognitive_analysis: {
                  humor_mechanism: '反讽',
                  emotional_tone: '轻松',
                  persona_fit_score: 0.9,
                  source_url: 'https://www.bilibili.com/video/example',
                },
              },
            ],
          })
        } else if (event === Events.MEME.REVIEW) callback?.({ ok: true, feedback: '已收录为好梗' })
        else if (event === Events.MEME.DATASET) callback?.({ memes: [{ id: 'meme-1' }] })
      },
    )
    const wrapper = mount(MemeWorkspace)
    await flushPromises()

    expect(wrapper.text()).toContain('需求真的不会再改了')
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '通过')!
      .trigger('click')
    expect(socket.emit).toHaveBeenCalledWith(
      Events.MEME.REVIEW,
      { meme_id: 'meme-1', status: 'good' },
      expect.any(Function),
    )
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '准备导出')!
      .trigger('click')
    expect(wrapper.get('a[download="meme_dataset.json"]')).toBeTruthy()
  })

  it('closes preflight with Escape and exposes the three preparation sections', async () => {
    socket.emit.mockImplementation(
      (event: string, _payload: unknown, callback?: (...args: unknown[]) => void) => {
        if (event === Events.PERSONA.LIST)
          callback?.({ personas: ['Aura'], current_persona: 'Aura' })
      },
    )
    const wrapper = mount(PreflightDrawer, {
      props: { open: true },
      global: {
        plugins: [createPinia()],
        stubs: {
          Teleport: true,
          BackgroundSettings: { template: '<div data-testid="background-settings" />' },
        },
      },
    })
    await flushPromises()

    expect(
      wrapper.findAll('[aria-label="开播准备分区"] [role="tab"]').map((item) => item.text()),
    ).toEqual(['连接', '人格', '画面'])
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
