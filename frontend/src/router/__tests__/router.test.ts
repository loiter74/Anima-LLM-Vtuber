// 回归测试：ISSUE-009——此前前端没有测试。

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

  it('registers only application routes', () => {
    expect(
      router
        .getRoutes()
        .map(({ name }) => name)
        .sort(),
    ).toEqual(['chat', 'dashboard', 'meme-review', 'music'])
  })
})
