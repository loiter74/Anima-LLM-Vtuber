// 回归测试：ISSUE-009——此前前端没有测试。

import { describe, it, expect, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from '@/App.vue'

// Mock router since App uses composables that depend on route
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'chat', path: '/' }),
  createRouter: vi.fn(),
  createMemoryHistory: vi.fn(),
}))

describe('App', () => {
  it('mounts without errors', () => {
    const app = createApp(App)
    app.use(createPinia())
    expect(() => app.mount(document.createElement('div'))).not.toThrow()
  })
})
