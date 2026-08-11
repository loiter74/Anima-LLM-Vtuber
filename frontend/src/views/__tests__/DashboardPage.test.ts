import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/views/DashboardPage.vue'
import { Events } from '@/constants/socket-events'

const socket = vi.hoisted(() => ({ emit: vi.fn(), on: vi.fn(), off: vi.fn() }))
vi.mock('@/composables/useSocket', () => ({ getSocket: () => socket }))

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
    user: {
      text: '去 Minecraft 看看基地',
      character_count: 18,
      byte_count: 36,
      digest: 'abcdef1234567890',
    },
    assistant: {
      text: '开发者刚刚在后台提到基地，我现在去看看。',
      character_count: 24,
      byte_count: 48,
      digest: '123456abcdef7890',
    },
  },
  tool_calls: 1,
  mc_status: 'success',
} as const

const livePayload = {
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

const detailPayload = {
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

describe('DashboardPage livestream operations console', () => {
  beforeEach(() => {
    localStorage.clear()
    socket.emit.mockReset()
    socket.on.mockReset()
    socket.off.mockReset()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request) =>
        String(input).includes('/turns/') ? response(detailPayload) : response(livePayload),
      ),
    )
  })

  afterEach(() => vi.unstubAllGlobals())

  async function mountDashboard() {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
        stubs: { TitleBar: { template: '<header data-testid="shared-titlebar" />' } },
      },
    })
    await flushPromises()
    return wrapper
  }

  it('shows full developer and tool content in the trusted operations console', async () => {
    const wrapper = await mountDashboard()

    expect(wrapper.get('[data-testid="shared-titlebar"]')).toBeTruthy()
    expect(wrapper.text()).toContain('开发者对话')
    expect(wrapper.text()).toContain('执行检查器')
    expect(wrapper.text()).toContain('开发者')
    expect(wrapper.text()).toContain('模型调用')
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).toContain('决定并调用工具')
    expect(wrapper.text()).toContain('MCP minecraft')
    expect(wrapper.text()).toContain('queued → succeeded')
    expect(wrapper.text()).toContain('去 Minecraft 看看基地')
    expect(wrapper.text()).toContain('开发者刚刚在后台提到基地')
    expect(wrapper.text()).toContain('command-1')
    expect(wrapper.text()).toContain('"operation":"progress"')
    expect(wrapper.text()).toContain('后台原文')
    expect(wrapper.text()).not.toContain('已脱敏')
    wrapper.unmount()
  })

  it('sends dashboard text only through the trusted developer event', async () => {
    const wrapper = await mountDashboard()
    const textarea = wrapper.get('[data-testid="chat-input-bar"] textarea')
    await textarea.setValue('去 Minecraft 看看基地')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(socket.emit).toHaveBeenCalledOnce()
    expect(socket.emit.mock.calls[0][0]).toBe(Events.CHAT.DEVELOPER_TEXT)
    expect(socket.emit.mock.calls[0][1]).toMatchObject({
      text: '去 Minecraft 看看基地',
      source: 'text',
    })
    expect(wrapper.text()).toContain('投递中')
    wrapper.unmount()
  })

  it('refreshes selected MC detail immediately on command transition', async () => {
    const wrapper = await mountDashboard()
    const registration = socket.on.mock.calls.find(
      ([event]) => event === Events.MINECRAFT.COMMAND_TRANSITION,
    )
    expect(registration).toBeTruthy()

    await registration![1]({ command_id: 'command-1' })
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/stats/live/turns/'))
    wrapper.unmount()
  })
})
