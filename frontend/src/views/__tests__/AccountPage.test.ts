import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccountPage from '../AccountPage.vue'
import { useConnectionStore } from '@/stores/connection'

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  logout: vi.fn(),
}))
const socket = vi.hoisted(() => ({ ensureAuthenticatedSession: vi.fn() }))

vi.mock('@/auth/api', async (loadOriginal) => ({
  ...(await loadOriginal<typeof import('@/auth/api')>()),
  changePassword: api.changePassword,
  logout: api.logout,
}))
vi.mock('@/composables/useSocket', () => socket)
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))

describe('AccountPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.changePassword.mockResolvedValue(undefined)
    api.logout.mockResolvedValue(undefined)
    socket.ensureAuthenticatedSession.mockResolvedValue('authenticated')
  })

  it('shows the first-login gate and does not expose administration before password change', () => {
    const pinia = createPinia()
    useConnectionStore(pinia).applyAuthSession({
      status: 'authenticated',
      user: { id: 'admin-1', username: 'admin', role: 'admin' },
      passwordChangeRequired: true,
    })

    const wrapper = mount(AccountPage, {
      global: { plugins: [pinia], stubs: { TitleBar: true } },
    })

    expect(wrapper.get('[data-testid="password-required-notice"]').text()).toContain('首次登录')
    expect(wrapper.text()).not.toContain('用户管理')
  })

  it('changes the password without persisting or echoing it', async () => {
    const pinia = createPinia()
    useConnectionStore(pinia).applyAuthSession({
      status: 'authenticated',
      user: { id: 'user-1', username: 'viewer', role: 'user' },
      passwordChangeRequired: false,
    })
    const wrapper = mount(AccountPage, {
      global: { plugins: [pinia], stubs: { TitleBar: true } },
    })

    const passwords = wrapper.findAll('input[type="password"]')
    await passwords[0].setValue('current-password')
    await passwords[1].setValue('replacement-password')
    await passwords[2].setValue('replacement-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.changePassword).toHaveBeenCalledWith('current-password', 'replacement-password')
    expect(socket.ensureAuthenticatedSession).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('密码已更新')
    expect(passwords.every((input) => (input.element as HTMLInputElement).value === '')).toBe(true)
    expect(wrapper.text()).not.toContain('用户管理')
  })
})
