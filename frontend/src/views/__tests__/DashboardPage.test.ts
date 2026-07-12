import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/views/DashboardPage.vue'

const baseTrace = {
  api_version: '2',
  message_id: 'message-1',
  conversation_id: 'conversation-1',
  session_id: 'desktop',
  input_type: 'text',
  privacy_mode: 'redacted',
  started_at: 1_784_000_000,
  finished_at: 1_784_000_002,
  duration_ms: 2000,
  error_type: null,
} as const

function operation(
  operationId: string,
  name: string,
  status: 'success' | 'degraded' | 'error' = 'success',
  children: object[] = [],
) {
  return {
    operation_id: operationId,
    trace_id: 'golden-task',
    parent_operation_id: null,
    layer: 'workflow',
    name,
    critical_path: true,
    started_at: 1_784_000_000,
    finished_at: 1_784_000_001,
    duration_ms: 100,
    status,
    provider: null,
    model: null,
    error_type: null,
    error_summary: null,
    attributes: {},
    children,
  }
}

function detail(traceId: string, golden: boolean) {
  const names = golden
    ? ['conversation_start', 'personality', 'reasoner', 'anima_composer', 'response_guard', 'reply_output', 'tts', 'emotion', 'performance_output', 'conversation_finalizer']
    : ['personality', 'llm', 'humor_rewrite', 'humor_validation', 'tts', 'emotion', 'output']
  const operations = names.map((name, index) => operation(
    `${traceId}-${name}`,
    name,
    golden && index === 4 ? 'degraded' : 'success',
    name === (golden ? 'reasoner' : 'llm')
      ? [{
          ...operation(`${traceId}-service`, 'llm.chat'),
          trace_id: traceId,
          parent_operation_id: `${traceId}-${name}`,
          layer: 'service',
          provider: 'openai',
          model: 'gpt-test',
        }]
      : [],
  ))
  return {
    ...baseTrace,
    trace_id: traceId,
    runtime_profile: golden ? 'golden' : 'development',
    outcome: golden ? 'degraded' : 'success',
    error_summary: null,
    content: {
      user: { text: null, character_count: 18, byte_count: 36, digest: 'abcdef1234567890' },
      assistant: { text: null, character_count: 12, byte_count: 24, digest: '123456abcdef7890' },
    },
    attributes: {},
    operations,
    operation_tree: operations,
    events: [{
      event_id: `${traceId}-delivery`,
      trace_id: traceId,
      operation_id: `${traceId}-performance_output`,
      direction: 'egress',
      name: 'chat:text',
      phase: 'delivered',
      occurred_at: 1_784_000_002,
      payload_size: 12,
      identity_valid: true,
      attributes: {},
    }],
    post_turn: {
      pending: golden ? 1 : 0,
      completed: golden ? 2 : 0,
      failed: 0,
      operations: [],
    },
    schema_version: 2,
  }
}

function mockStatsFetch() {
  vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
    const url = String(input)
    if (url.includes('/api/stats/traces/golden-task/tree')) {
      return Promise.resolve({ json: () => Promise.resolve(detail('golden-task', true)) })
    }
    if (url.includes('/api/stats/traces/standard-task/tree')) {
      return Promise.resolve({ json: () => Promise.resolve(detail('standard-task', false)) })
    }
    if (url.includes('/api/stats/overview')) {
      return Promise.resolve({ json: () => Promise.resolve({
        api_version: '2', total_requests: 2, success_count: 1, degraded_count: 1,
        failed_count: 0, success_rate: 50, avg_duration_ms: 1800,
      }) })
    }
    if (url.includes('/api/stats/nodes')) return Promise.resolve({ json: () => Promise.resolve([]) })
    return Promise.resolve({ json: () => Promise.resolve([
      { ...baseTrace, trace_id: 'golden-task', runtime_profile: 'golden', outcome: 'degraded' },
      { ...baseTrace, trace_id: 'standard-task', runtime_profile: 'development', outcome: 'success' },
    ]) })
  }))
}

async function flushPromises() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve()
}

describe('DashboardPage canonical observation tree', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockStatsFetch()
  })

  async function mountDashboard() {
    const wrapper = mount(DashboardPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    return wrapper
  }

  it('renders the actual golden topology and typed degraded outcome', async () => {
    const wrapper = await mountDashboard()
    expect(wrapper.text()).toContain('DEGRADED')
    expect(wrapper.text()).toContain('conversation_start')
    expect(wrapper.text()).toContain('reasoner')
    expect(wrapper.text()).toContain('conversation_finalizer')
  })

  it('renders the actual standard topology after trace navigation', async () => {
    const wrapper = await mountDashboard()
    await wrapper.get('[data-testid="older-trace"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('humor_rewrite')
    expect(wrapper.text()).toContain('output')
    expect(wrapper.text()).not.toContain('conversation_finalizer')
  })

  it('shows redaction facts without exposing content', async () => {
    const wrapper = await mountDashboard()
    expect(wrapper.text()).toContain('已脱敏 · 18 chars · abcdef123456…')
    expect(wrapper.text()).not.toContain('secret prompt')
  })

  it('shows provider identity and committed delivery events', async () => {
    const wrapper = await mountDashboard()
    await wrapper.get('[data-testid="trace-node-golden-task-service"]').trigger('click')
    expect(wrapper.text()).toContain('openai')
    expect(wrapper.text()).toContain('gpt-test')
    await wrapper.get('[data-testid="trace-node-golden-task-performance_output"]').trigger('click')
    expect(wrapper.text()).toContain('egress · chat:text · delivered')
  })

  it('shows post-turn memory work separately from the critical path', async () => {
    const wrapper = await mountDashboard()
    expect(wrapper.text()).toContain('2 done · 1 pending · 0 failed')
  })
})
