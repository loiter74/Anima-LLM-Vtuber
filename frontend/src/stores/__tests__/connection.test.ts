import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useConnectionStore } from '@/stores/connection'

describe('useConnectionStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('starts disconnected with empty error', () => {
    const store = useConnectionStore()
    expect(store.status).toBe('disconnected')
    expect(store.authStatus).toBe('checking')
    expect(store.errorMessage).toBe('')
  })

  it.each(['authenticated', 'unauthenticated', 'unavailable'] as const)(
    'tracks %s authentication separately from the socket',
    (authStatus) => {
      const store = useConnectionStore()
      store.setStatus('connected')
      store.setAuthStatus(authStatus)

      expect(store.authStatus).toBe(authStatus)
      expect(store.status).toBe('connected')
    },
  )

  it('setStatus updates to connected', () => {
    const store = useConnectionStore()
    store.setStatus('connected')
    expect(store.status).toBe('connected')
    expect(store.errorMessage).toBe('')
  })

  it('setStatus updates to error with message', () => {
    const store = useConnectionStore()
    store.setStatus('error', 'Connection refused')
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('Connection refused')
  })

  it('setStatus updates to connecting', () => {
    const store = useConnectionStore()
    store.setStatus('connecting')
    expect(store.status).toBe('connecting')
  })

  it('setStatus clears previous error message', () => {
    const store = useConnectionStore()
    store.setStatus('error', 'timeout')
    store.setStatus('connected')
    expect(store.errorMessage).toBe('')
  })

  it('cycles through status transitions', () => {
    const store = useConnectionStore()
    store.setStatus('connecting')
    expect(store.status).toBe('connecting')
    store.setStatus('connected')
    expect(store.status).toBe('connected')
    store.setStatus('disconnected')
    expect(store.status).toBe('disconnected')
    store.setStatus('error', 'lost')
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('lost')
  })
})
