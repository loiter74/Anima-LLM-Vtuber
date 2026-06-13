import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import AppLayout from '@/components/layout/AppLayout.vue'

// Mock useDanmaku to avoid socket initialization
vi.mock('@/composables/useDanmaku', () => ({
  useDanmaku: () => ({ store: {}, connect: vi.fn(), disconnect: vi.fn(), updateRoom: vi.fn() }),
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
})
