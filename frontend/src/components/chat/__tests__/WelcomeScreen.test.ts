import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import WelcomeScreen from '@/components/chat/WelcomeScreen.vue'

// Mock gsap
vi.mock('gsap', () => ({
  gsap: {
    context: vi.fn((callback) => ({
      callback,
      revert: vi.fn(),
    })),
    timeline: vi.fn(() => ({
      from: vi.fn().mockReturnThis(),
    })),
    set: vi.fn(),
  },
}))

// Mock SceneEffects
vi.mock('@/components/shared/SceneEffects.vue', () => ({
  default: {
    name: 'SceneEffects',
    template: '<div class="mock-scene-effects"></div>',
  },
}))

describe('WelcomeScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
  })

  it('renders hero section fitting the narrow chat panel', () => {
    // WelcomeScreen is rendered inside the 340px chat panel (MessageList empty
    // state), so it must use h-full/min-h — not h-screen which overflows.
    const wrapper = mount(WelcomeScreen)
    const root = wrapper.find('.h-full')
    expect(root.exists()).toBe(true)
    expect(root.classes()).not.toContain('h-screen')
  })

  it('renders title with accent dot', () => {
    const wrapper = mount(WelcomeScreen)
    const title = wrapper.find('h1')
    expect(title.exists()).toBe(true)
    expect(title.text()).toContain('Animetta')
    expect(wrapper.find('.text-c-accent').exists()).toBe(true)
  })

  it('renders subtitle', () => {
    const wrapper = mount(WelcomeScreen)
    expect(wrapper.text()).toContain('和我一起聊会儿天吧')
  })

  it('renders two CTA buttons', () => {
    const wrapper = mount(WelcomeScreen)
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBe(2)
    expect(buttons[0].text()).toBe('开始对话')
    expect(buttons[1].text()).toBe('了解更多')
  })

  it('emits dismiss when start chat clicked', async () => {
    const wrapper = mount(WelcomeScreen)
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('dismiss')).toBeTruthy()
  })

  it('renders a radial wash overlay so the title pops over the panel', () => {
    // The background image is no longer local to this component — the global
    // preset shows through the translucent panel. We still keep a radial wash
    // overlay for title legibility.
    const wrapper = mount(WelcomeScreen)
    expect(wrapper.find('.bg-gradient-radial').exists()).toBe(true)
  })

  it('renders SceneEffects', () => {
    const wrapper = mount(WelcomeScreen)
    expect(wrapper.find('.mock-scene-effects').exists()).toBe(true)
  })

  it('stacks CTA buttons vertically to fit the 340px panel width', () => {
    const wrapper = mount(WelcomeScreen)
    // The CTA container uses flex-col (stacked) instead of sm:flex-row
    const ctaContainer = wrapper
      .findAll('.flex')
      .find((el) => el.classes().includes('flex-col') && el.findAll('button').length === 2)
    expect(ctaContainer).toBeTruthy()
  })
})
