import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePersonalityStore } from '@/stores/personality'
import { Events } from '@/constants/socket-events'

const socket = {
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}

vi.mock('@/composables/useSocket', () => ({
  getSocket: () => socket,
}))

describe('usePersonalityStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    socket.on.mockReset()
    socket.off.mockReset()
    socket.emit.mockReset()
  })

  it('tracks the current persona returned by persona:list', async () => {
    socket.emit.mockImplementation((event, _payload, callback) => {
      if (event === Events.PERSONA.LIST) {
        callback({
          personas: ['default', 'anima'],
          current_persona: 'anima',
        })
      }
    })

    const store = usePersonalityStore()
    await store.fetchAvailablePersonas()

    expect(store.availablePersonas).toEqual(['default', 'anima'])
    expect(store.currentPersona).toBe('anima')
  })

  it('updates current persona from persona:updated events', () => {
    const store = usePersonalityStore()
    const listener = socket.on.mock.calls.find(
      ([event]) => event === Events.PERSONA.UPDATED
    )?.[1]

    listener?.({ persona_name: 'streamer', mbti: null })

    expect(store.currentPersona).toBe('streamer')
    expect(store.mbtiType).toBeNull()
    expect(store.mbtiDimensions).toBeNull()
  })

  it('sets current persona after a successful persona:set ack', async () => {
    socket.emit.mockImplementation((event, _payload, callback) => {
      if (event === Events.PERSONA.SET) {
        callback({})
      }
    })

    const store = usePersonalityStore()
    await store.setPersona('anima')

    expect(store.currentPersona).toBe('anima')
    expect(store.personaError).toBeNull()
  })
})
