import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BentoGrid from '@/components/shared/BentoGrid.vue'
import BentoCard from '@/components/shared/BentoCard.vue'

// Mock composables
vi.mock('@/composables/useScrollTrigger', () => ({
  useScrollTrigger: vi.fn(() => ({
    ctx: { value: null },
    prefersReducedMotion: { value: false },
  })),
}))

vi.mock('@/composables/useHoverPhysics', () => ({
  useHoverPhysics: vi.fn(() => ({
    isHovered: { value: false },
    onEnter: vi.fn(),
    onLeave: vi.fn(),
  })),
}))

describe('BentoGrid', () => {
  it('renders with correct grid classes', () => {
    const wrapper = mount(BentoGrid)
    expect(wrapper.find('.grid').exists()).toBe(true)
    expect(wrapper.find('.grid-cols-1').exists()).toBe(true)
    expect(wrapper.find('.xl\\:grid-cols-4').exists()).toBe(true)
  })

  it('applies custom gap', () => {
    const wrapper = mount(BentoGrid, {
      props: { gap: 24 },
    })
    const grid = wrapper.find('.grid')
    expect(grid.attributes('style')).toContain('gap: 24px')
  })

  it('renders slot content', () => {
    const wrapper = mount(BentoGrid, {
      slots: {
        default: '<div class="test-card">Card</div>',
      },
    })
    expect(wrapper.find('.test-card').exists()).toBe(true)
  })
})

describe('BentoCard', () => {
  it('renders with glass class', () => {
    const wrapper = mount(BentoCard)
    expect(wrapper.find('.glass').exists()).toBe(true)
    expect(wrapper.find('.rounded-2xl').exists()).toBe(true)
  })

  it('applies col-span-2 when colSpan is 2', () => {
    const wrapper = mount(BentoCard, {
      props: { colSpan: 2 },
    })
    expect(wrapper.find('.col-span-2').exists()).toBe(true)
  })

  it('applies row-span-2 when rowSpan is 2', () => {
    const wrapper = mount(BentoCard, {
      props: { rowSpan: 2 },
    })
    expect(wrapper.find('.row-span-2').exists()).toBe(true)
  })

  it('applies overflow-hidden for image type', () => {
    const wrapper = mount(BentoCard, {
      props: { type: 'image' },
    })
    expect(wrapper.find('.overflow-hidden').exists()).toBe(true)
  })

  it('applies stat styling for stat type', () => {
    const wrapper = mount(BentoCard, {
      props: { type: 'stat' },
    })
    expect(wrapper.find('.flex-col').exists()).toBe(true)
    expect(wrapper.find('.items-center').exists()).toBe(true)
    expect(wrapper.find('.text-center').exists()).toBe(true)
  })

  it('renders slot content', () => {
    const wrapper = mount(BentoCard, {
      slots: {
        default: '<p>Card content</p>',
      },
    })
    expect(wrapper.find('p').text()).toBe('Card content')
  })

  it('has cursor-pointer when hover is enabled', () => {
    const wrapper = mount(BentoCard, {
      props: { hover: true },
    })
    expect(wrapper.find('.cursor-pointer').exists()).toBe(true)
  })
})
