import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import UserManagementPanel from '../UserManagementPanel.vue'

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  resetUserPassword: vi.fn(),
  revokeUserSessions: vi.fn(),
}))

vi.mock('@/auth/api', async (loadOriginal) => ({
  ...(await loadOriginal<typeof import('@/auth/api')>()),
  ...api,
}))

const users = [
  {
    id: 'admin-1',
    username: 'admin',
    role: 'admin',
    enabled: true,
    must_change_password: false,
    created_at: 1,
    updated_at: 1,
    last_login_at: 1,
    active_sessions: 1,
  },
  {
    id: 'user-1',
    username: 'viewer',
    role: 'user',
    enabled: true,
    must_change_password: true,
    created_at: 1,
    updated_at: 1,
    last_login_at: null,
    active_sessions: 0,
  },
]

describe('UserManagementPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listUsers.mockResolvedValue(users)
    api.createUser.mockResolvedValue(users[1])
    api.updateUser.mockResolvedValue(undefined)
    api.resetUserPassword.mockResolvedValue(undefined)
    api.revokeUserSessions.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('loads role, status, first-login, and session summaries', async () => {
    const wrapper = mount(UserManagementPanel, { props: { currentUserId: 'admin-1' } })
    await flushPromises()

    expect(wrapper.text()).toContain('viewer')
    expect(wrapper.text()).toContain('待改密')
    expect(wrapper.text()).toContain('有效会话 1')
    const currentRole = wrapper.get('select[aria-label="admin 的角色"]')
    expect(currentRole.attributes()).toHaveProperty('disabled')
  })

  it('creates a user with a temporary password and clears the password field', async () => {
    const wrapper = mount(UserManagementPanel, { props: { currentUserId: 'admin-1' } })
    await flushPromises()

    await wrapper.get('input[autocomplete="off"]').setValue('new-user')
    const temporaryPassword = wrapper.get<HTMLInputElement>('input[autocomplete="new-password"]')
    await temporaryPassword.setValue('temporary-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.createUser).toHaveBeenCalledWith({
      username: 'new-user',
      role: 'user',
      temporaryPassword: 'temporary-password',
    })
    expect(temporaryPassword.element.value).toBe('')
    expect(wrapper.text()).not.toContain('temporary-password')
  })

  it('confirms role, status, reset, and session-revocation operations', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    const wrapper = mount(UserManagementPanel, { props: { currentUserId: 'admin-1' } })
    await flushPromises()
    const viewer = () => wrapper.findAll('article')[1]

    await viewer().get('select').setValue('admin')
    await flushPromises()
    expect(api.updateUser).toHaveBeenCalledWith('user-1', { role: 'admin' })

    const button = (label: string) =>
      viewer()
        .findAll('button')
        .find((candidate) => candidate.text() === label)!
    await button('禁用').trigger('click')
    await flushPromises()
    expect(api.updateUser).toHaveBeenCalledWith('user-1', { enabled: false })

    await button('重置密码').trigger('click')
    const resetInput = wrapper.get<HTMLInputElement>('[role="dialog"] input[type="password"]')
    await resetInput.setValue('replacement-temporary-password')
    await wrapper.get('[role="dialog"] form').trigger('submit')
    await flushPromises()
    expect(api.resetUserPassword).toHaveBeenCalledWith('user-1', 'replacement-temporary-password')
    expect(wrapper.text()).not.toContain('replacement-temporary-password')

    await button('撤销会话').trigger('click')
    await flushPromises()
    expect(api.revokeUserSessions).toHaveBeenCalledWith('user-1')
  })
})
