import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import DashboardPage from '@/views/DashboardPage.vue'

const leafStubs = {
  TitleBar: { template: '<header data-testid="title-bar" />' },
  LiveOperationsWorkspace: { template: '<main data-testid="live-workspace" />' },
  ProgramScriptEditor: { template: '<section data-testid="script-workspace" />' },
  MusicCard: { template: '<section data-testid="singing-workspace" />' },
  MemeWorkspace: { template: '<section data-testid="meme-workspace" />' },
  MemoryWorkspace: {
    emits: ['send-to-sandbox'],
    template:
      '<main data-testid="memory-workspace"><button data-testid="send-memory" @click="$emit(\'send-to-sandbox\', \'记住观众喜欢雨夜电台\')">发送到沙盒</button></main>',
  },
  ConversationSandbox: {
    props: ['modelValue'],
    template: '<section data-testid="sandbox-workspace">{{ modelValue }}</section>',
  },
  ProgramReplayPanel: { template: '<section data-testid="replay-workspace" />' },
}

function mountPage() {
  return mount(DashboardPage, {
    global: {
      plugins: [createPinia()],
      stubs: leafStubs,
    },
  })
}

function tab(wrapper: ReturnType<typeof mountPage>, label: string) {
  const button = wrapper.findAll('[role="tab"]').find((item) => item.text() === label)
  if (!button) throw new Error(`missing tab ${label}`)
  return button
}

describe('DashboardPage information architecture', () => {
  it('keeps exactly four backend tasks and starts in live operations', () => {
    const wrapper = mountPage()

    const taskTabs = wrapper.findAll('[aria-label="后台任务"] [role="tab"]')
    expect(taskTabs.map((item) => item.text())).toEqual(['现场', '节目', '记忆', '验证'])
    expect(wrapper.get('[data-testid="title-bar"]')).toBeTruthy()
    expect(wrapper.get('[data-testid="live-workspace"]')).toBeTruthy()
    expect(wrapper.find('[data-testid="script-workspace"]').exists()).toBe(false)
  })

  it('keeps scripts, singing, and Meme in the program task', async () => {
    const wrapper = mountPage()
    await tab(wrapper, '节目').trigger('click')

    expect(wrapper.get('[data-testid="script-workspace"]')).toBeTruthy()
    expect(
      wrapper.findAll('[aria-label="节目工作区"] [role="tab"]').map((item) => item.text()),
    ).toEqual(['脚本编排', '唱歌制作', 'Meme 梗库'])

    await tab(wrapper, '唱歌制作').trigger('click')
    expect(wrapper.get('[data-testid="singing-workspace"]')).toBeTruthy()
    await tab(wrapper, 'Meme 梗库').trigger('click')
    expect(wrapper.get('[data-testid="meme-workspace"]')).toBeTruthy()
  })

  it('moves a memory draft into the private validation sandbox without sending it', async () => {
    const wrapper = mountPage()
    await tab(wrapper, '记忆').trigger('click')
    await wrapper.get('[data-testid="send-memory"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="sandbox-workspace"]').text()).toContain(
      '记住观众喜欢雨夜电台',
    )
    expect(
      wrapper.findAll('[aria-label="验证工作区"] [role="tab"]').map((item) => item.text()),
    ).toEqual(['对话沙盒', '弹幕重放'])
  })

  it('keeps replay exclusively under validation', async () => {
    const wrapper = mountPage()
    await tab(wrapper, '验证').trigger('click')
    await tab(wrapper, '弹幕重放').trigger('click')

    expect(wrapper.get('[data-testid="replay-workspace"]')).toBeTruthy()
    expect(wrapper.find('[data-testid="meme-workspace"]').exists()).toBe(false)
  })
})
