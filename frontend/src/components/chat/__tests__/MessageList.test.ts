import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import MessageList from '@/components/chat/MessageList.vue'

vi.mock('@/components/chat/WelcomeScreen.vue', () => ({
  default: { template: '<div />' },
}))

vi.mock('@/components/chat/MessageBubble.vue', () => ({
  default: { template: '<div />', props: ['message'] },
}))

vi.mock('@/composables/useMessageStore', () => ({
  useMessageStore: () => ({
    loadMessages: vi.fn().mockResolvedValue([]),
    saveMessages: vi.fn().mockResolvedValue(undefined),
    pruneMessages: vi.fn().mockResolvedValue(undefined),
  }),
}))

describe('MessageList', () => {
  it('uses a stable scroll container that prevents browser scroll anchoring jumps', () => {
    const wrapper = mount(MessageList, {
      global: {
        plugins: [createPinia()],
      },
    })

    const list = wrapper.find('[data-testid="message-list"]')
    expect(list.exists()).toBe(true)
    expect(list.classes()).toContain('message-list-stable')
  })
})
