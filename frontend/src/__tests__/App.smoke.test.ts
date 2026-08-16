// 回归测试：ISSUE-009——此前前端没有测试。

import { afterEach, describe, it, expect, vi } from 'vitest'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import App from '@/App.vue'
import { useConnectionStore } from '@/stores/connection'

const socketMocks = vi.hoisted(() => ({
  useSocket: vi.fn(() => ({})),
  ensureAuthenticatedSession: vi.fn(),
}))

vi.mock('@/composables/useSocket', () => socketMocks)

// Mock router since App uses composables that depend on route
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'chat', path: '/' }),
  createRouter: vi.fn(),
  createMemoryHistory: vi.fn(),
}))

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('mounts without errors', () => {
    const wrapper = mount(App, {
      global: { plugins: [createPinia()], stubs: { RouterView: true } },
    })

    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('submits account credentials and clears the password', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal('fetch', fetchMock)
    socketMocks.ensureAuthenticatedSession.mockResolvedValue('authenticated')
    const pinia = createPinia()
    useConnectionStore(pinia).setAuthStatus('unauthenticated')
    const wrapper = mount(App, {
      global: { plugins: [pinia], stubs: { RouterView: true } },
    })

    await nextTick()
    expect(wrapper.get('[data-testid="auth-gate"]').text()).toContain('未登录')
    expect(wrapper.get<HTMLInputElement>('#auth-username').element.value).toBe('admin')
    await wrapper.get('#auth-username').setValue('admin')
    await wrapper.get('#auth-password').setValue('correct horse battery staple')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({
        body: JSON.stringify({
          username: 'admin',
          password: 'correct horse battery staple',
        }),
      }),
    )
    expect(wrapper.get<HTMLInputElement>('#auth-password').element.value).toBe('')
    wrapper.unmount()
  })

  it('shows a distinct session-store failure state', async () => {
    const pinia = createPinia()
    useConnectionStore(pinia).setAuthStatus('unavailable')
    const wrapper = mount(App, {
      global: { plugins: [pinia], stubs: { RouterView: true } },
    })

    expect(wrapper.get('[data-testid="auth-gate"]').text()).toContain('登录服务不可用')
    wrapper.unmount()
  })
})
