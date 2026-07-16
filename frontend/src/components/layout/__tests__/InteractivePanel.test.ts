import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InteractivePanel from '@/components/layout/InteractivePanel.vue'

const mockIsMobile = vi.hoisted(() => ({ value: true, __v_isRef: true }))

vi.mock('@/composables/useMobile', () => ({
  useMobile: () => ({ isMobile: mockIsMobile }),
}))

vi.mock('@/composables/useDanmaku', () => ({
  useDanmaku: () => ({ store: {}, connect: vi.fn(), disconnect: vi.fn(), updateRoom: vi.fn() }),
}))

const stubs = {
  ChatPanel: true,
  LiveChatPanel: true,
  MemoryPanel: true,
  PersonalityPanel: true,
  MusicCard: true,
  SettingsPanel: true,
  PopOutButton: true,
}

describe('InteractivePanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
    mockIsMobile.value = true
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses equal-width mobile tab buttons with stable spacing', () => {
    const wrapper = mount(InteractivePanel, {
      props: { live2dPopout: false },
      global: { stubs },
    })

    const tabbar = wrapper.find('[data-testid="mobile-tabbar"]')
    const buttons = wrapper.findAll('[data-testid="mobile-tab-button"]')

    expect(tabbar.exists()).toBe(true)
    expect(tabbar.classes()).toContain('mobile-tabbar')
    expect(buttons).toHaveLength(6)
    expect(buttons.every((button) => button.classes().includes('flex-1'))).toBe(true)
  })

  it('shows reload success state without changing tabs', async () => {
    mockIsMobile.value = false
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            ok: true,
            version: 4,
            persona: 'anima.v0.1',
            refreshed: ['persona', 'llm'],
          }),
      }),
    )

    const wrapper = mount(InteractivePanel, {
      props: { live2dPopout: false },
      global: { stubs },
    })

    const button = wrapper.get('[aria-label="重载人格配置"]')
    await button.trigger('click')
    await Promise.resolve()
    await Promise.resolve()

    expect(wrapper.find('.config-reload-label').text()).toBe('已加载 anima.v0.1 · v4')
    expect(wrapper.find('.panel-tab.active').text()).toContain('聊天')
  })
})
