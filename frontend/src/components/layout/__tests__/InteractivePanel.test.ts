import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
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
})
