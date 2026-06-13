// Regression: ISSUE-009 — 0 frontend tests
// Found by /qa on 2026-06-02
// Report: .gstack/qa-reports/qa-report-localhost-3000-2026-06-02.md

import { describe, it, expect } from 'vitest'
import router from '@/router'

describe('Router', () => {
  it('resolves / (chat) route', () => {
    const route = router.resolve('/')
    expect(route.name).toBe('chat')
  })

  it('resolves /dashboard route', () => {
    const route = router.resolve('/dashboard')
    expect(route.name).toBe('dashboard')
  })

  it('resolves /meme-review route', () => {
    const route = router.resolve('/meme-review')
    expect(route.name).toBe('meme-review')
  })

  it('resolves /music route', () => {
    const route = router.resolve('/music')
    expect(route.name).toBe('music')
  })

  it('has at least 5 routes', () => {
    expect(router.getRoutes().length).toBeGreaterThanOrEqual(5)
  })
})
