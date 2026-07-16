import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useHoverPhysics } from '@/composables/useHoverPhysics'

// Mock gsap
vi.mock('gsap', () => ({
  gsap: {
    to: vi.fn(),
  },
}))

describe('useHoverPhysics', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns hover handlers', () => {
    const TestComponent = defineComponent({
      setup() {
        const elementRef = ref<HTMLElement | null>(null)
        return {
          ...useHoverPhysics(elementRef),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.isHovered).toBeDefined()
    expect(wrapper.vm.onEnter).toBeDefined()
    expect(wrapper.vm.onLeave).toBeDefined()
  })

  it('calls gsap.to on hover enter', async () => {
    const { gsap } = await import('gsap')
    const element = document.createElement('div')

    const TestComponent = defineComponent({
      setup() {
        const elementRef = ref<HTMLElement | null>(element)
        return {
          ...useHoverPhysics(elementRef, { scale: 1.05 }),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    await wrapper.vm.onEnter()

    expect(gsap.to).toHaveBeenCalledWith(
      element,
      expect.objectContaining({
        scale: 1.05,
        duration: 0.7,
        ease: 'power2.out',
      }),
    )
  })

  it('calls gsap.to on hover leave with scale 1', async () => {
    const { gsap } = await import('gsap')
    const element = document.createElement('div')

    const TestComponent = defineComponent({
      setup() {
        const elementRef = ref<HTMLElement | null>(element)
        return {
          ...useHoverPhysics(elementRef),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    await wrapper.vm.onLeave()

    expect(gsap.to).toHaveBeenCalledWith(
      element,
      expect.objectContaining({
        scale: 1,
        duration: 0.7,
        ease: 'power2.out',
      }),
    )
  })

  it('tracks hover state', async () => {
    const element = document.createElement('div')

    const TestComponent = defineComponent({
      setup() {
        const elementRef = ref<HTMLElement | null>(element)
        return {
          ...useHoverPhysics(elementRef),
          elementRef,
        }
      },
      template: '<div ref="elementRef"></div>',
    })

    const wrapper = mount(TestComponent)
    expect(wrapper.vm.isHovered).toBe(false)

    await wrapper.vm.onEnter()
    expect(wrapper.vm.isHovered).toBe(true)

    await wrapper.vm.onLeave()
    expect(wrapper.vm.isHovered).toBe(false)
  })
})
