// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'
import { runReviewWorkflow } from '../scripts/review/orchestrator'
import { automaticDecision } from '../scripts/review/policies'

const definition = {
  id: 'test',
  contractVersion: 1,
  route: '/test.html',
  viewport: { width: 1080, height: 1920 },
  scenes: ['one', 'two', 'three'].map((id) => ({
    id,
    title: id,
    observe: id,
    readyTexts: [],
    timeline: [],
  })),
}

describe('review workflow orchestration', () => {
  it('does not retry automatic failures and continues independent scenes', async () => {
    const execute = vi
      .fn()
      .mockResolvedValueOnce({ technicalPassed: true })
      .mockResolvedValueOnce({ technicalPassed: false })
      .mockResolvedValueOnce({ technicalPassed: true })
    const persist = vi.fn().mockResolvedValue(undefined)

    const result = await runReviewWorkflow({
      definition,
      execute,
      decide: async (technicalPassed) => automaticDecision(technicalPassed),
      persist,
      interactive: false,
    })

    expect(execute).toHaveBeenCalledTimes(3)
    expect(execute.mock.calls.map(([scene, attempt]) => [scene.id, attempt])).toEqual([
      ['one', 1],
      ['two', 1],
      ['three', 1],
    ])
    expect(result.allPass).toBe(false)
    expect(result.attempts.map(({ decision }) => decision.outcome)).toEqual([
      'passed',
      'failed',
      'passed',
    ])
    expect(persist).toHaveBeenCalledTimes(3)
  })

  it('repeats only the current scene for interactive adjust or redo', async () => {
    const execute = vi.fn().mockResolvedValue({ technicalPassed: true })
    const decisions = [
      {
        outcome: 'failed' as const,
        decisionSource: 'human' as const,
        humanVerdict: 'adjust' as const,
        humanNote: 'raise panel',
      },
      {
        outcome: 'passed' as const,
        decisionSource: 'human' as const,
        humanVerdict: 'pass' as const,
        humanNote: '',
      },
    ]

    const result = await runReviewWorkflow({
      definition: { ...definition, scenes: definition.scenes.slice(0, 1) },
      execute,
      decide: vi.fn(async () => decisions.shift()!),
      persist: vi.fn().mockResolvedValue(undefined),
      interactive: true,
    })

    expect(execute.mock.calls.map(([scene, attempt]) => [scene.id, attempt])).toEqual([
      ['one', 1],
      ['one', 2],
    ])
    expect(result.allPass).toBe(true)
    expect(result.attempts).toHaveLength(2)
  })

  it('does not ask for or retry a human verdict after technical failure', async () => {
    const decide = vi.fn(async (technicalPassed: boolean) => automaticDecision(technicalPassed))

    const result = await runReviewWorkflow({
      definition: { ...definition, scenes: definition.scenes.slice(0, 1) },
      execute: vi.fn().mockResolvedValue({ technicalPassed: false }),
      decide,
      persist: vi.fn().mockResolvedValue(undefined),
      interactive: true,
    })

    expect(decide).toHaveBeenCalledWith(false)
    expect(decide).toHaveBeenCalledOnce()
    expect(result.allPass).toBe(false)
    expect(result.attempts).toHaveLength(1)
  })
})
