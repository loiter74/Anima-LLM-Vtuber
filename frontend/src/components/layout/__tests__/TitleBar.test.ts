import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TitleBar from '@/components/layout/TitleBar.vue'

const route = vi.hoisted(() => ({ name: 'dashboard' }))

vi.mock('vue-router', () => ({
  useRoute: () => route,
}))

describe('TitleBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    route.name = 'dashboard'
  })

  it('exposes only the public live view and backstage dashboard', () => {
    const wrapper = mount(TitleBar, {
      global: {
        plugins: [createPinia()],
      },
    })

    expect(wrapper.get('[data-testid="nav-live"]').attributes('href')).toBe('/live.html')
    expect(wrapper.get('[data-testid="nav-dashboard"]').attributes('href')).toBe('/dashboard')
    expect(wrapper.findAll('.nav-btn')).toHaveLength(2)
    expect(wrapper.find('.nav-btn.active').text()).toBe('后台控制')
  })
})
