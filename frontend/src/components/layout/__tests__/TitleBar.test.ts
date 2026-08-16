import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TitleBar from '@/components/layout/TitleBar.vue'
import { useConnectionStore } from '@/stores/connection'

const route = vi.hoisted(() => ({ name: 'dashboard' }))

vi.mock('vue-router', () => ({
  useRoute: () => route,
}))

describe('TitleBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    route.name = 'dashboard'
  })

  it('exposes the live view, backstage dashboard, and account page', () => {
    const wrapper = mount(TitleBar, {
      global: {
        plugins: [createPinia()],
      },
    })

    expect(wrapper.get('[data-testid="nav-live"]').attributes('href')).toBe('/live.html')
    expect(wrapper.get('[data-testid="nav-dashboard"]').attributes('href')).toBe('/dashboard')
    expect(wrapper.get('[data-testid="nav-account"]').attributes('href')).toBe('/account')
    expect(wrapper.findAll('.nav-btn')).toHaveLength(3)
    expect(wrapper.find('.nav-btn.active').text()).toBe('后台控制')
  })

  it.each([
    ['unauthenticated', '未登录'],
    ['unavailable', '登录服务不可用'],
  ] as const)('shows %s without calling it disconnected', (authStatus, label) => {
    const pinia = createPinia()
    const store = useConnectionStore(pinia)
    store.setAuthStatus(authStatus)
    store.setStatus('disconnected')

    const wrapper = mount(TitleBar, { global: { plugins: [pinia] } })

    expect(wrapper.get('.status-text').text()).toBe(label)
    expect(wrapper.get('.status-text').text()).not.toBe('服务已断开')
  })

  it('shows the password requirement independently from socket state', () => {
    const pinia = createPinia()
    const store = useConnectionStore(pinia)
    store.applyAuthSession({
      status: 'authenticated',
      user: { id: 'user-1', username: 'admin', role: 'admin' },
      passwordChangeRequired: true,
    })
    store.setStatus('disconnected')

    const wrapper = mount(TitleBar, { global: { plugins: [pinia] } })

    expect(wrapper.get('.status-text').text()).toBe('需修改密码')
  })
})
