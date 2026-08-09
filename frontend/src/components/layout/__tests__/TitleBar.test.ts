import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TitleBar from '@/components/layout/TitleBar.vue'

const push = vi.fn()
const route = vi.hoisted(() => ({ name: 'dashboard' }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  useRoute: () => route,
}))

describe('TitleBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    route.name = 'dashboard'
    push.mockClear()
  })

  it('uses the livestream operations navigation label', () => {
    const wrapper = mount(TitleBar, {
      global: {
        plugins: [createPinia()],
      },
    })

    expect(wrapper.text()).toContain('Chat')
    expect(wrapper.text()).toContain('Memory')
    expect(wrapper.text()).toContain('直播执行')
    expect(wrapper.text()).toContain('Settings')
    expect(wrapper.find('.nav-btn.active').text()).toBe('直播执行')
  })

  it('dispatches a panel navigation event for Memory', async () => {
    const dispatchEvent = vi.spyOn(window, 'dispatchEvent')
    const wrapper = mount(TitleBar, {
      global: {
        plugins: [createPinia()],
      },
    })

    await wrapper.get('[data-testid="nav-memory"]').trigger('click')

    expect(dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'animetta:panel-tab',
      }),
    )
  })
})
