import { describe, expect, it } from 'vitest'
import socketSource from '../composables/useSocket.ts?raw'
import liveSource from '../live/main.ts?raw'
import viteSource from '../../vite.config.ts?raw'

describe('frontend runtime configuration sources', () => {
  it('removes VITE_API_URL and keeps deployment endpoints in Vite only', () => {
    const sources = [socketSource, liveSource, viteSource].join('\n')

    expect(sources).not.toContain('VITE_API_URL')
    expect(sources).toContain('ANIMETTA_BACKEND_URL')
  })
})
