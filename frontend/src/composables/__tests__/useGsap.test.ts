import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useGsap } from '@/composables/useGsap'

// Mock gsap
vi.mock('gsap', () => ({
  gsap: {
    context: vi.fn((callback) => ({
      callback,
      revert: vi.fn(),
    })),
  },
}))

describe('useGsap', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Mock matchMedia
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
  })

  it('creates GSAP context on mount', () => {
    const TestComponent = defineComponent({
      setup() {
        return useGsap(() => {})
      },
      template: '<div></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.ctx).toBeDefined()
  })

  it('detects prefers-reduced-motion', () => {
    // Mock matchMedia to return reduced motion
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })

    const TestComponent = defineComponent({
      setup() {
        return useGsap(() => {})
      },
      template: '<div></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.prefersReducedMotion).toBe(true)
  })

  it('reverts context on unmount', async () => {
    const revertSpy = vi.fn()
    const { gsap } = await import('gsap')
    vi.mocked(gsap.context).mockReturnValue({
      isReverted: false,
      callback: () => {},
      revert: revertSpy,
      add: vi.fn(),
      ignore: vi.fn(),
      kill: vi.fn(),
      clear: vi.fn(),
    } as unknown as gsap.Context)

    const TestComponent = defineComponent({
      setup() {
        return useGsap(() => {})
      },
      template: '<div></div>',
    })

    const wrapper = mount(TestComponent)
    wrapper.unmount()
    expect(revertSpy).toHaveBeenCalled()
  })
})
