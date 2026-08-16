import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DisplayCredentialsPanel from '../DisplayCredentialsPanel.vue'

const api = vi.hoisted(() => ({
  approveDisplayPairing: vi.fn(),
  listDisplayCredentials: vi.fn(),
  revokeDisplayCredential: vi.fn(),
}))

vi.mock('@/auth/api', async (loadOriginal) => ({
  ...(await loadOriginal<typeof import('@/auth/api')>()),
  ...api,
}))

const credential = {
  id: 'display-1',
  name: 'B站直播场景',
  approved_by_user_id: 'admin-1',
  bound_origin: 'http://127.0.0.1',
  issued_at: 1_000,
  expires_at: 2_593_000,
  last_seen_at: 1_010,
}

describe('DisplayCredentialsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listDisplayCredentials.mockResolvedValue([credential])
    api.approveDisplayPairing.mockResolvedValue(undefined)
    api.revokeDisplayCredential.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('approves a short code without exposing a user session credential', async () => {
    const wrapper = mount(DisplayCredentialsPanel)
    await flushPromises()

    await wrapper.get('input[placeholder="ABCD-EFGH"]').setValue('ABCD-EFGH')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.approveDisplayPairing).toHaveBeenCalledWith('ABCD-EFGH', 'B站直播场景')
    expect(wrapper.text()).toContain('下一次轮询后自动连接')
    expect(wrapper.text()).toContain('最近连接')
    expect(wrapper.text()).not.toContain('animetta_session')
  })

  it('requires confirmation before immediately revoking a display', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    const wrapper = mount(DisplayCredentialsPanel)
    await flushPromises()

    await wrapper.get('article button').trigger('click')
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledOnce()
    expect(api.revokeDisplayCredential).toHaveBeenCalledWith('display-1')
    expect(wrapper.text()).toContain('直播设备已撤销')
  })
})
