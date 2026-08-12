import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LiveOperationsWorkspace from '@/components/dashboard/LiveOperationsWorkspace.vue'
import { Events } from '@/constants/socket-events'
import { useDanmakuStore } from '@/stores/danmaku'

const socket = vi.hoisted(() => ({ emit: vi.fn(), on: vi.fn(), off: vi.fn() }))
vi.mock('@/composables/useSocket', () => ({ getSocket: () => socket }))
vi.mock('@/composables/useDanmaku', () => ({ useDanmaku: () => ({}) }))

const turn = {
  trace_id: '00000000-0000-4000-8000-000000000003',
  message_id: '00000000-0000-4000-8000-000000000002',
  conversation_id: '00000000-0000-4000-8000-000000000001',
  actor_role: 'developer',
  source: 'developer_console',
  live_session_id: 'live-1',
  audience: 'livestream',
  started_at: 1_784_000_000,
  finished_at: 1_784_000_002,
  duration_ms: 2000,
  outcome: 'success',
  privacy_mode: 'full',
  content: {
    user: { text: '去 Minecraft 看看基地', character_count: 18, byte_count: 36, digest: 'a' },
    assistant: {
      text: '开发者在后台提到基地，我现在去看看。',
      character_count: 22,
      byte_count: 44,
      digest: 'b',
    },
  },
  tool_calls: 1,
  mc_status: 'success',
}

const summary = {
  api_version: '1',
  metrics: {
    turn_count: 1,
    model_calls: 2,
    tool_calls: 1,
    tool_success_rate: 100,
    mc_command_count: 1,
    mc_status: 'success',
  },
  turns: [turn],
}

const detail = {
  api_version: '1',
  ...turn,
  activities: [
    {
      id: 'tool-1',
      kind: 'tool',
      label: '决定并调用工具',
      name: 'tool:mc_operate_bot',
      layer: 'service',
      status: 'success',
      started_at: 1_784_000_001,
      duration_ms: 125,
      provider: null,
      model: null,
      error: null,
      attributes: {
        tool_source: 'mcp',
        mcp_server: 'minecraft',
        arguments_text: '{"operation":"progress","command_id":"command-1"}',
        result_text: '{"state":"succeeded"}',
      },
      minecraft: {
        command_id: 'command-1',
        state: 'succeeded',
        failure_reason: null,
        transitions: [
          { from_state: null, to_state: 'queued', reason_code: 'accepted' },
          { from_state: 'queued', to_state: 'succeeded', reason_code: 'completed' },
        ],
      },
    },
  ],
  events: [],
}

function response(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
}

async function flushPromises() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

function mountWorkspace() {
  const pinia = createPinia()
  const wrapper = mount(LiveOperationsWorkspace, {
    global: {
      plugins: [pinia],
      stubs: {
        ProgramRunPanel: { template: '<section data-testid="program-run-panel" />' },
        PreflightDrawer: {
          props: ['open'],
          template: '<aside v-if="open" data-testid="preflight-drawer" />',
        },
      },
    },
  })
  return { wrapper, pinia }
}

describe('LiveOperationsWorkspace', () => {
  beforeEach(() => {
    socket.emit.mockReset()
    socket.on.mockReset()
    socket.off.mockReset()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) =>
        String(input).includes('/turns/') ? response(detail) : response(summary),
      ),
    )
  })

  afterEach(() => vi.unstubAllGlobals())

  it('shows trusted turn content and raw tool evidence only in the inspector', async () => {
    const { wrapper } = mountWorkspace()
    await flushPromises()

    expect(wrapper.text()).toContain('执行回合')
    expect(wrapper.text()).toContain('执行检查器')
    expect(wrapper.text()).toContain('去 Minecraft 看看基地')
    expect(wrapper.text()).toContain('决定并调用工具')
    expect(wrapper.text()).toContain('MCP minecraft')
    expect(wrapper.text()).toContain('queued → succeeded')
    expect(wrapper.text()).toContain('"operation":"progress"')
    wrapper.unmount()
  })

  it('uses only the trusted developer event for backstage intervention', async () => {
    const { wrapper } = mountWorkspace()
    await flushPromises()
    const textarea = wrapper.get('[data-testid="chat-input-bar"] textarea')
    await textarea.setValue('去 Minecraft 看看基地')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(socket.emit).toHaveBeenCalledOnce()
    expect(socket.emit.mock.calls[0][0]).toBe(Events.CHAT.DEVELOPER_TEXT)
    expect(socket.emit.mock.calls[0][1]).toMatchObject({ text: '去 Minecraft 看看基地' })
    expect(wrapper.text()).toContain('投递中')
    wrapper.unmount()
  })

  it('switches to the raw danmaku feed with connection, audience, and count evidence', async () => {
    const { wrapper, pinia } = mountWorkspace()
    const danmaku = useDanmakuStore(pinia)
    danmaku.connected = true
    danmaku.addMessage({
      text: '今晚唱哪一首',
      user_name: '夜班观众',
      user_id: 7,
      timestamp: 1_784_000_003,
    })
    await flushPromises()
    const rawTab = wrapper.findAll('button').find((button) => button.text() === '原始弹幕')
    await rawTab!.trigger('click')

    expect(wrapper.get('[data-testid="raw-danmaku-list"]').text()).toContain('连接 直播中')
    expect(wrapper.text()).toContain('观众 1')
    expect(wrapper.text()).toContain('累计 1')
    expect(wrapper.text()).toContain('今晚唱哪一首')
    wrapper.unmount()
  })

  it('opens preflight and refreshes MC detail on command transitions', async () => {
    const { wrapper } = mountWorkspace()
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '开播准备')!
      .trigger('click')
    expect(wrapper.get('[data-testid="preflight-drawer"]')).toBeTruthy()

    const registration = socket.on.mock.calls.find(
      ([event]) => event === Events.MINECRAFT.COMMAND_TRANSITION,
    )
    await registration![1]({ command_id: 'command-1' })
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/stats/live/turns/'))
    wrapper.unmount()
  })
})
