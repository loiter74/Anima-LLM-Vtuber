import { describe, expect, it } from 'vitest'
import { recordAssertion } from '../scripts/review/assertions'
import type { AssertionRecord } from '../scripts/review/browser'

describe('recordAssertion', () => {
  it('records successful asynchronous assertions in order', async () => {
    const assertions: AssertionRecord[] = []

    await recordAssertion(assertions, 'first', async () => {})
    await recordAssertion(assertions, 'second', () => {})

    expect(assertions).toEqual([
      { name: 'first', passed: true },
      { name: 'second', passed: true },
    ])
  })

  it('records the safe failure detail without rejecting', async () => {
    const assertions: AssertionRecord[] = []

    await recordAssertion(assertions, 'failed', () => {
      throw new Error('expected detail')
    })

    expect(assertions).toEqual([{ name: 'failed', passed: false, detail: 'expected detail' }])
  })
})
