// 回归测试：ISSUE-009——此前前端没有测试。

import { describe, it, expect } from 'vitest'
import router from '@/router'

describe('Router', () => {
  it('redirects / to the backstage dashboard', () => {
    const route = router.resolve('/')
    expect(route.redirectedFrom).toBeUndefined()
    expect(route.matched[0]?.redirect).toBe('/dashboard')
  })

  it('resolves /dashboard route', () => {
    const route = router.resolve('/dashboard')
    expect(route.name).toBe('dashboard')
  })

  it('redirects removed and unknown SPA pages to the dashboard', () => {
    const route = router.resolve('/music')
    expect(route.matched[0]?.redirect).toBe('/dashboard')
  })

  it('registers only application routes', () => {
    expect(
      router
        .getRoutes()
        .map(({ name }) => name)
        .filter(Boolean),
    ).toEqual(['dashboard'])
  })
})
