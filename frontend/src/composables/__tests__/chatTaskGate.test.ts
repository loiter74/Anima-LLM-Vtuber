import { beforeEach, describe, expect, it } from 'vitest'
import { activateChatTask, isCurrentChatTask, resetChatTaskGate } from '../chatTaskGate'
import type { ChatIdentity } from '@/types/socket-events'

const identity = (taskId: string): ChatIdentity => ({
  message_id: '00000000-0000-4000-8000-000000000001',
  conversation_id: '00000000-0000-4000-8000-000000000002',
  task_id: taskId,
  turn_id: taskId,
})

describe('chatTaskGate', () => {
  beforeEach(resetChatTaskGate)

  it('rejects media from a stale task after a newer task activates', () => {
    const oldTask = identity('00000000-0000-4000-8000-000000000003')
    const newTask = identity('00000000-0000-4000-8000-000000000004')
    activateChatTask(oldTask)
    activateChatTask(newTask)

    expect(isCurrentChatTask(oldTask)).toBe(false)
    expect(isCurrentChatTask(newTask)).toBe(true)
  })

  it('rejects malformed turn identity', () => {
    const task = identity('00000000-0000-4000-8000-000000000003')
    activateChatTask(task)
    expect(isCurrentChatTask({ ...task, turn_id: 'different' })).toBe(false)
  })
})
