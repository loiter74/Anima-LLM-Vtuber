import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SectionTabs from '@/components/shared/SectionTabs.vue'

const tabs = [
  { id: 'live', label: '现场', description: '查看直播执行' },
  { id: 'program', label: '节目', description: '编排内容' },
  { id: 'memory', label: '记忆', description: '治理记忆' },
] as const

describe('SectionTabs', () => {
  it('exposes a real tablist with one roving tab stop', () => {
    const wrapper = mount(SectionTabs, {
      props: { tabs, modelValue: 'live', label: '后台任务' },
    })

    expect(wrapper.get('[role="tablist"]').attributes('aria-label')).toBe('后台任务')
    const buttons = wrapper.findAll('[role="tab"]')
    expect(buttons.map((button) => button.attributes('tabindex'))).toEqual(['0', '-1', '-1'])
    expect(buttons[0].attributes('aria-selected')).toBe('true')
    expect(buttons[1].attributes('aria-selected')).toBe('false')
  })

  it('supports arrow, Home, and End keyboard navigation', async () => {
    const wrapper = mount(SectionTabs, {
      props: { tabs, modelValue: 'live', label: '后台任务' },
    })

    await wrapper.get('[role="tablist"]').trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['program'])

    await wrapper.setProps({ modelValue: 'program' })
    await wrapper.get('[role="tablist"]').trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['memory'])

    await wrapper.setProps({ modelValue: 'memory' })
    await wrapper.get('[role="tablist"]').trigger('keydown', { key: 'Home' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['live'])
  })
})
