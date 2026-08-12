import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearCommandTask, readCommandTask, startCommandTask } from '../commandTasks'

describe('commandTasks', () => {
  beforeEach(() => localStorage.clear())

  it('reuses a task id for the same pending command', () => {
    const uuid = vi.fn().mockReturnValueOnce('task-one').mockReturnValueOnce('task-two')

    const first = startCommandTask('singing.process', 'BV1', localStorage, uuid)
    const second = startCommandTask('singing.process', 'BV1', localStorage, uuid)

    expect(first).toBe('task-one')
    expect(second).toBe('task-one')
    expect(uuid).toHaveBeenCalledOnce()
    expect(readCommandTask('singing.process')).toEqual({ taskId: 'task-one', requestKey: 'BV1' })
  })

  it('creates a new task only for an explicit retry', () => {
    const uuid = vi.fn().mockReturnValueOnce('task-one').mockReturnValueOnce('task-two')
    startCommandTask('meme.collect', 'bilibili', localStorage, uuid)

    const retried = startCommandTask('meme.collect', 'bilibili', localStorage, uuid, true)

    expect(retried).toBe('task-two')
  })

  it('clears a terminal task without changing other command identities', () => {
    startCommandTask('chat.sandbox', 'request', localStorage, () => 'task-one')
    startCommandTask('singing.process', 'BV1', localStorage, () => 'task-two')

    clearCommandTask('chat.sandbox')

    expect(readCommandTask('chat.sandbox')).toBeNull()
    expect(readCommandTask('singing.process')?.taskId).toBe('task-two')
  })
})
