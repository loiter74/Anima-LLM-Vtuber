import { describe, expect, it } from 'vitest'

import { createDomLiveView } from '../view'

describe('standalone live DOM view', () => {
  function mountLiveView() {
    document.body.innerHTML = `
      <div id="danmakuList"></div>
      <div id="emptyState"></div>
      <span id="messageCount"></span>
      <section id="danmakuPanel"></section>
      <span id="socketStatus"></span>
      <span id="livestreamStatus"></span>
      <div id="liveBackground"></div>
      <section id="subtitleOverlay" hidden><p id="subtitleText"></p></section>
      <aside id="publicActivityPanel" hidden>
        <section id="publicNarrationState" hidden></section>
        <span id="publicCurrentIntent"></span>
        <span id="publicRecentObservation"></span>
        <span id="publicNextPhase"></span>
        <ol id="publicActivityList"></ol>
      </aside>
    `
    return createDomLiveView(document)
  }

  it('does not expose the removed danmaku collapse API', () => {
    const view = mountLiveView()

    expect('bindToggle' in view).toBe(false)
    expect('setCollapsed' in view).toBe(false)
  })

  it.each([
    ['connecting', '服务连接中'],
    ['connected', '服务已连接'],
    ['disconnected', '服务已断开'],
  ] as const)('renders %s as %s', (state, label) => {
    const view = mountLiveView()

    view.setSocketState(state)

    const status = document.getElementById('socketStatus')!
    expect(status.dataset.state).toBe(state)
    expect(status.textContent).toBe(label)
  })

  it('labels gift and super-chat messages while preserving their content', () => {
    const view = mountLiveView()

    view.renderMessages([
      {
        user_name: '人事部小王',
        user_id: -201,
        text: '送出「摸鱼许可证」×1',
        timestamp: 1,
        is_gift: true,
      },
      {
        user_name: '测试组阿灯',
        user_id: -202,
        text: '今天的需求真的不会再改了（大概）',
        timestamp: 2,
        is_super_chat: true,
      },
    ])

    const gift = document.querySelector('.danmaku-item.is-gift')
    const superChat = document.querySelector('.danmaku-item.is-super-chat')
    expect(gift?.querySelector('.danmaku-kind')?.textContent).toBe('礼物')
    expect(gift?.textContent).toContain('人事部小王')
    expect(gift?.textContent).toContain('送出「摸鱼许可证」×1')
    expect(superChat?.querySelector('.danmaku-kind')?.textContent).toBe('醒目留言')
    expect(superChat?.textContent).toContain('测试组阿灯')
    expect(superChat?.textContent).toContain('今天的需求真的不会再改了（大概）')
  })

  it('shows and clears public subtitles without interpreting reply markup', () => {
    const view = mountLiveView()
    const overlay = document.getElementById('subtitleOverlay')!

    view.setSubtitle('<开发者回复>')
    expect(overlay.hidden).toBe(false)
    expect(document.getElementById('subtitleText')?.textContent).toBe('<开发者回复>')

    view.setSubtitle(null)
    expect(overlay.hidden).toBe(true)
    expect(document.getElementById('subtitleText')?.textContent).toBe('')
  })

  it('shares the ordered public activity and narration DOM contract', () => {
    const view = mountLiveView()
    view.renderPublicActivities([
      {
        schema_version: '1',
        event: 'minecraft.activity.projection',
        event_id: 'activity:1',
        projection_kind: 'activity',
        projection_version: 1,
        occurred_at_ms: 10,
        entity_id: 'minecraft',
        payload: {
          phase: 'observing',
          intent: 'acquire',
          focus: { kind: 'item', label: '铁矿' },
          outcome: 'active',
        },
        phaseLabel: '观察',
        visualText: '观察 · 铁矿',
      },
    ])
    view.setPublicNarration({
      schema_version: '1',
      cue_id: 'cue:1',
      source_event_id: 'activity:1',
      task_id: 'task-1',
      phase: 'observing',
      visual_text: '这里看起来有铁矿。',
      emotion: 'thinking',
      speech_state: 'speaking',
      occurred_at_ms: 11,
    })

    expect(document.querySelector('[data-event-id="activity:1"]')?.textContent).toContain(
      '观察 · 铁矿',
    )
    expect(document.getElementById('publicNarrationState')?.dataset.taskId).toBe('task-1')
    expect(document.getElementById('publicCurrentIntent')?.textContent).toBe('收集 · 铁矿')
    expect(document.getElementById('publicRecentObservation')?.textContent).toBe('铁矿')
    expect(document.getElementById('publicNextPhase')?.textContent).toBe('确认行动')
    expect(document.getElementById('publicActivityPanel')?.hidden).toBe(false)
  })

  it('persists Bilibili reply identities without changing visible status text', () => {
    const view = mountLiveView()
    const status = document.getElementById('livestreamStatus')!
    status.textContent = '弹幕直播中'

    view.setBilibiliReplyEvidence({
      source_message_id: 'source-1',
      reply_id: 'reply-1',
    })

    expect(status).toHaveProperty('dataset.lastBilibiliSourceMessageId', 'source-1')
    expect(status).toHaveProperty('dataset.lastBilibiliReplyId', 'reply-1')
    expect(status.textContent).toBe('弹幕直播中')
  })

  it('distinguishes a connected pre-live room from an active broadcast', () => {
    const view = mountLiveView()

    view.setLivestreamStatus({
      state: 'prelive',
      connected: true,
      room_id: 1234567890,
      desired_room_id: 1234567890,
      retry_count: 0,
      error_code: null,
      generation_id: 1,
      message: 'Waiting for broadcast',
      updated_at: 1,
    })

    const status = document.getElementById('livestreamStatus')!
    expect(status.dataset.state).toBe('prelive')
    expect(status.textContent).toBe('弹幕姬已连接 · 等待开播')
  })

  it('increments the live list without rebuilding old nodes and caps it at 60 items', () => {
    const view = mountLiveView()
    const messages = Array.from({ length: 100 }, (_, index) => ({
      source_message_id: `m-${index}`,
      user_name: '观众',
      user_id: index,
      text: `弹幕 ${index}`,
      timestamp: index,
    }))

    view.renderMessages(messages.slice(0, 99))
    const previousLast = document.querySelector('[data-message-id="m-98"]')
    view.renderMessages(messages)

    expect(document.querySelectorAll('.danmaku-item')).toHaveLength(60)
    expect(document.querySelector('[data-message-id="m-40"]')).not.toBeNull()
    expect(document.querySelector('[data-message-id="m-99"]')).not.toBeNull()
    expect(document.querySelector('[data-message-id="m-98"]')).toBe(previousLast)
    expect(document.getElementById('messageCount')?.textContent).toBe('100')
  })

  it('does not force the list back to the tail after the viewer scrolls up', () => {
    const view = mountLiveView()
    const list = document.getElementById('danmakuList')!
    Object.defineProperties(list, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 1000 },
      scrollTop: { configurable: true, value: 200, writable: true },
    })

    view.renderMessages([
      {
        source_message_id: 'new-message',
        user_name: '观众',
        user_id: 1,
        text: '新弹幕',
        timestamp: 1,
      },
    ])

    expect(list.scrollTop).toBe(200)
  })
})
