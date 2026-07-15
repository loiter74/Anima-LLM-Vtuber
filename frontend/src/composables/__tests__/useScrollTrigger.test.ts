import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useScrollTrigger } from '@/composables/useScrollTrigger'

// Mock gsap and ScrollTrigger
vi.mock('gsap', () => ({
  gsap: {
    context: vi.fn((callback) => ({
      callback,
      revert: vi.fn(),
    })),
    fromTo: vi.fn(),
    registerPlugin: vi.fn(),
  },
}))

vi.mock('gsap/ScrollTrigger', () => ({
  ScrollTrigger: {
    create: vi.fn(),
    getAll: vi.fn(() => []),
    kill: vi.fn(),
  },
}))

describe('useScrollTrigger', () => {
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

  it('returns ctx and prefersReducedMotion', () => {
    const TestComponent = defineComponent({
      setup() {
        const elementRef = ref<HTMLElement | null>(null)
        return {
          ...useScrollTrigger(elementRef),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.ctx).toBeDefined()
    expect(wrapper.vm.prefersReducedMotion).toBeDefined()
  })

  it('respects prefers-reduced-motion', () => {
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
        const elementRef = ref<HTMLElement | null>(null)
        return {
          ...useScrollTrigger(elementRef),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.prefersReducedMotion).toBe(true)
  })
})
