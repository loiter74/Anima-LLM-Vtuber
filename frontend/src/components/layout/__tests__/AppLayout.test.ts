import { beforeEach, describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import AppLayout from '@/components/layout/AppLayout.vue'

const mockIsMobile = vi.hoisted(() => ({ value: false, __v_isRef: true }))

// Mock useDanmaku to avoid socket initialization
vi.mock('@/composables/useDanmaku', () => ({
  useDanmaku: () => ({ store: {}, connect: vi.fn(), disconnect: vi.fn(), updateRoom: vi.fn() }),
}))

vi.mock('@/composables/useMobile', () => ({
  useMobile: () => ({
    isMobile: mockIsMobile,
    isTablet: { value: false, __v_isRef: true },
    isDesktop: { value: true, __v_isRef: true },
    breakpoint: { value: 'desktop', __v_isRef: true },
  }),
}))

function createWrapper() {
  return mount(AppLayout, {
    global: {
      plugins: [createPinia()],
      stubs: {
        TitleBar: true,
        Live2DRenderer: true,
        SceneEffects: true,
        InteractivePanel: true,
      },
    },
  })
}

describe('AppLayout', () => {
  beforeEach(() => {
    mockIsMobile.value = false
  })

  it('renders Live2DRenderer stub', () => {
    const wrapper = createWrapper()
    const renderer = wrapper.findComponent({ name: 'Live2DRenderer' })
    expect(renderer.exists()).toBe(true)
  })

  it('renders SceneEffects stub', () => {
    const wrapper = createWrapper()
    const effects = wrapper.findComponent({ name: 'SceneEffects' })
    expect(effects.exists()).toBe(true)
  })

  it('renders InteractivePanel stub', () => {
    const wrapper = createWrapper()
    const panel = wrapper.findComponent({ name: 'InteractivePanel' })
    expect(panel.exists()).toBe(true)
  })

  it('has Live2DRenderer visible by default (not popout)', () => {
    const wrapper = createWrapper()
    // Live2DRenderer renders inside .stage div when not popped out
    const stageDiv = wrapper.find('.stage')
    expect(stageDiv.exists()).toBe(true)
    const renderer = stageDiv.findComponent({ name: 'Live2DRenderer' })
    expect(renderer.exists()).toBe(true)
  })

  it('passes live2dPopout prop to InteractivePanel', () => {
    const wrapper = createWrapper()
    const panel = wrapper.findComponent({ name: 'InteractivePanel' })
    expect(panel.props('live2dPopout')).toBe(false)
  })

  it('renders without errors', () => {
    const wrapper = createWrapper()
    expect(wrapper.exists()).toBe(true)
  })

  it('uses a full-screen Live2D stage behind the mobile panel', () => {
    mockIsMobile.value = true

    const wrapper = createWrapper()
    const stage = wrapper.find('.mobile-stage')
    const panel = wrapper.find('.mobile-panel')

    expect(stage.exists()).toBe(true)
    expect(stage.classes()).toContain('mobile-stage-fullscreen')
    expect(panel.exists()).toBe(true)
    expect(panel.classes()).toContain('mobile-panel-overlay')
  })
})
