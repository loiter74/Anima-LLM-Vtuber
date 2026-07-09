import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DashboardPage from '@/views/DashboardPage.vue'

function mockStatsFetch() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url.includes('/api/stats/traces/trace-latest/tree')) {
      return Promise.resolve({
        json: () => Promise.resolve({
          trace_id: 'trace-latest',
          session_id: 'desktop',
          input_type: 'text',
          user_text: '把刚才那段话用更元气的语气说一遍',
          total_duration_ms: 2860,
          status: 'error',
          error_msg: 'tts provider returned empty audio buffer',
          created_at: '2026-07-08T22:41:16',
          spans: [
            {
              span_id: 'span-memory',
              parent_span_id: null,
              node_name: 'memory',
              duration_ms: 210,
              status: 'success',
              input_summary: '用户原始输入：把刚才那段话用更元气的语气说一遍',
              output_summary: '召回记忆：用户喜欢元气风格，最近聊过晚饭。',
              attributes: null,
              events: null,
              created_at: '2026-07-08T22:41:16',
            },
            {
              span_id: 'span-llm',
              parent_span_id: null,
              node_name: 'llm',
              duration_ms: 1061,
              status: 'success',
              input_summary: '用户：把刚才那段话用更元气的语气说一遍\n记忆：用户喜欢元气风格，最近聊过晚饭。',
              output_summary: '好的，我会用更元气的语气说：今天也要好好吃饭哦！',
              attributes: null,
              events: null,
              created_at: '2026-07-08T22:41:17',
            },
            {
              span_id: 'span-tts',
              parent_span_id: null,
              node_name: 'tts',
              duration_ms: 1468,
              status: 'error',
              input_summary: '好的，我会用更元气的语气说：今天也要好好吃饭哦！',
              output_summary: 'provider returned empty audio buffer',
              attributes: null,
              events: null,
              created_at: '2026-07-08T22:41:18',
            },
          ],
        }),
      })
    }
    if (url.includes('/api/stats/traces/trace-previous/tree')) {
      return Promise.resolve({
        json: () => Promise.resolve({
          trace_id: 'trace-previous',
          session_id: 'desktop',
          input_type: 'text',
          user_text: '今天的记忆系统状态怎么样？',
          total_duration_ms: 1794,
          status: 'success',
          error_msg: null,
          created_at: '2026-07-08T22:38:02',
          conversation_turn: {
            trace_id: 'trace-previous',
            session_id: 'desktop',
            input_type: 'text',
            user_text: '今天的记忆系统状态怎么样？这是完整的长文本输入。',
            assistant_text: '系统正常，最近没有失败节点。',
            status: 'success',
            error_msg: null,
            metadata: { source: 'test' },
            created_at: '2026-07-08T22:38:02',
          },
          spans: [],
        }),
      })
    }
    if (url.includes('/api/stats/overview')) {
      return Promise.resolve({
        json: () => Promise.resolve({
          total_requests: 2,
          success_rate: 50,
          avg_duration_ms: 2300,
          p95_duration_ms: 2860,
        }),
      })
    }
    if (url.includes('/api/stats/nodes')) {
      return Promise.resolve({
        json: () => Promise.resolve([
          { node_name: 'llm', call_count: 2, avg_duration_ms: 1061, error_count: 0, error_rate: 0 },
          { node_name: 'tts', call_count: 1, avg_duration_ms: 1468, error_count: 1, error_rate: 100 },
        ]),
      })
    }
    return Promise.resolve({
      json: () => Promise.resolve([
        {
          trace_id: 'trace-latest',
          session_id: 'desktop',
          input_type: 'text',
          user_text: '把刚才那段话用更元气的语气说一遍',
          total_duration_ms: 2860,
          status: 'error',
          created_at: '2026-07-08T22:41:16',
        },
        {
          trace_id: 'trace-previous',
          session_id: 'desktop',
          input_type: 'text',
          user_text: '今天的记忆系统状态怎么样？',
          total_duration_ms: 1794,
          status: 'success',
          created_at: '2026-07-08T22:38:02',
        },
      ]),
    })
  }))
}

async function flushPromises() {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve()
  }
}

describe('DashboardPage trace debugger', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockStatsFetch()
  })

  it('renders the latest trace as a graph-based debugging dashboard', async () => {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('历史 Trace')
    expect(wrapper.text()).toContain('Trace Debug Dashboard')
    expect(wrapper.text()).toContain('把刚才那段话用更元气的语气说一遍')
    expect(wrapper.text()).toContain('LLM')
    expect(wrapper.text()).toContain('TTS')
    expect(wrapper.text()).toContain('节点详情')
  })

  it('navigates to older and newer traces with arrow buttons', async () => {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="older-trace"]').trigger('click')
    expect(wrapper.text()).toContain('今天的记忆系统状态怎么样？')

    await wrapper.get('[data-testid="newer-trace"]').trigger('click')
    expect(wrapper.text()).toContain('把刚才那段话用更元气的语气说一遍')
  })

  it('keeps trace history collapsed until the user opens it', async () => {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="history-traces"]').exists()).toBe(false)

    await wrapper.get('[data-testid="history-toggle"]').trigger('click')

    expect(wrapper.find('[data-testid="history-traces"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('今天的记忆系统状态怎么样？')
  })

  it('shows real span payloads for the selected node data flow', async () => {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="trace-node-llm"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('用户喜欢元气风格')
    expect(wrapper.text()).toContain('今天也要好好吃饭哦')
    expect(wrapper.text()).not.toContain('prompt + memory context')
  })

  it('falls back to stored conversation text when node spans are absent', async () => {
    const wrapper = mount(DashboardPage, {
      global: {
        plugins: [createPinia()],
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="older-trace"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('节点详情OKInput')

    await wrapper.get('[data-testid="trace-node-llm"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('今天的记忆系统状态怎么样？这是完整的长文本输入。')
    expect(wrapper.text()).toContain('系统正常，最近没有失败节点。')
  })
})
