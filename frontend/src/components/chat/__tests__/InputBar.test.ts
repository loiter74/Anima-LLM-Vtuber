import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import InputBar from '@/components/chat/InputBar.vue'

function createWrapper(sendText: (text: string) => void = vi.fn()) {
  return mount(InputBar, {
    props: { sendText },
    global: {
      stubs: {
        VoiceButton: true,
      },
    },
    attachTo: document.body,
  })
}

describe('InputBar', () => {
  it('renders textarea and send button', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('send button is disabled when input is empty', () => {
    const wrapper = createWrapper()
    const sendBtn = wrapper.find('button:last-of-type')
    expect(sendBtn.attributes('disabled')).toBeDefined()
  })

  it('send button is enabled when input has text', async () => {
    const wrapper = createWrapper()
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Hello')
    const sendBtn = wrapper.find('button:last-of-type')
    expect(sendBtn.attributes('disabled')).toBeUndefined()
  })

  it('calls sendText and clears input on send', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Test message')
    await wrapper.find('button:last-of-type').trigger('click')
    expect(sendText).toHaveBeenCalledWith('Test message')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('sends on Enter key', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Enter send')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: false })
    expect(sendText).toHaveBeenCalledWith('Enter send')
  })

  it('does not send on Shift+Enter', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Shift enter')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(sendText).not.toHaveBeenCalled()
  })

  it('does not send empty or whitespace-only text', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    const textarea = wrapper.find('textarea')
    await textarea.setValue('   ')
    await wrapper.find('button:last-of-type').trigger('click')
    expect(sendText).not.toHaveBeenCalled()
  })

  it('does not send on button click when input is empty', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    await wrapper.find('button:last-of-type').trigger('click')
    expect(sendText).not.toHaveBeenCalled()
  })

  it('clears textarea height after sending', async () => {
    const sendText = vi.fn()
    const wrapper = createWrapper(sendText)
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Clear height test')
    // Set a custom style height
    ;(textarea.element as HTMLTextAreaElement).style.height = '100px'
    await wrapper.find('button:last-of-type').trigger('click')
    // After send, height should be reset to 'auto'
    expect((textarea.element as HTMLTextAreaElement).style.height).toBe('auto')
  })

  it('renders VoiceButton stub', () => {
    const wrapper = createWrapper()
    // The VoiceButton should be rendered as a stub
    const voiceBtn = wrapper.findComponent({ name: 'VoiceButton' })
    expect(voiceBtn.exists()).toBe(true)
  })
})
