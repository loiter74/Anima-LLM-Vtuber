import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { useSubtitleStore } from '@/stores/subtitle'

describe('useSubtitleStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  describe('initial state', () => {
    it('starts with subtitles enabled', () => {
      const store = useSubtitleStore()
      expect(store.enabled).toBe(true)
    })

    it('defaults to bilingual display mode', () => {
      const store = useSubtitleStore()
      expect(store.displayMode).toBe('bilingual')
    })

    it('defaults to large font', () => {
      const store = useSubtitleStore()
      expect(store.fontSize).toBe('large')
    })

    it('defaults target language to English', () => {
      const store = useSubtitleStore()
      expect(store.targetLanguage).toBe('English')
    })

    it('starts with null position', () => {
      const store = useSubtitleStore()
      expect(store.posX).toBeNull()
      expect(store.posY).toBeNull()
    })

    it('loads a valid ratio-based persisted config', () => {
      localStorage.setItem(
        'animetta_subtitle_config',
        JSON.stringify({
          _version: 2,
          enabled: false,
          displayMode: 'translated',
          fontSize: 'small',
          targetLanguage: 'Japanese',
          posX: 0.25,
          posY: 0.75,
        }),
      )

      const store = useSubtitleStore()

      expect(store.enabled).toBe(false)
      expect(store.displayMode).toBe('translated')
      expect(store.fontSize).toBe('small')
      expect(store.targetLanguage).toBe('Japanese')
      expect(store.posX).toBe(0.25)
      expect(store.posY).toBe(0.75)
    })

    it('falls back safely when persisted fields have invalid types', () => {
      localStorage.setItem(
        'animetta_subtitle_config',
        JSON.stringify({
          _version: 2,
          enabled: 'yes',
          displayMode: 'invalid',
          fontSize: 99,
          targetLanguage: null,
          posX: 'left',
          posY: {},
        }),
      )

      const store = useSubtitleStore()

      expect(store.enabled).toBe(true)
      expect(store.displayMode).toBe('bilingual')
      expect(store.fontSize).toBe('large')
      expect(store.targetLanguage).toBe('English')
      expect(store.posX).toBeNull()
      expect(store.posY).toBeNull()
    })
  })

  describe('toggle', () => {
    it('toggles enabled state', () => {
      const store = useSubtitleStore()
      store.toggle()
      expect(store.enabled).toBe(false)
      store.toggle()
      expect(store.enabled).toBe(true)
    })
  })

  describe('setDisplayMode', () => {
    it('sets display mode to original', () => {
      const store = useSubtitleStore()
      store.setDisplayMode('original')
      expect(store.displayMode).toBe('original')
    })

    it('sets display mode to translated', () => {
      const store = useSubtitleStore()
      store.setDisplayMode('translated')
      expect(store.displayMode).toBe('translated')
    })

    it('sets display mode to bilingual', () => {
      const store = useSubtitleStore()
      store.setDisplayMode('bilingual')
      expect(store.displayMode).toBe('bilingual')
    })
  })

  describe('setFontSize', () => {
    it('sets font size to small', () => {
      const store = useSubtitleStore()
      store.setFontSize('small')
      expect(store.fontSize).toBe('small')
    })

    it('sets font size to medium', () => {
      const store = useSubtitleStore()
      store.setFontSize('medium')
      expect(store.fontSize).toBe('medium')
    })

    it('sets font size to large', () => {
      const store = useSubtitleStore()
      store.setFontSize('large')
      expect(store.fontSize).toBe('large')
    })
  })

  describe('setTargetLanguage', () => {
    it('sets target language', () => {
      const store = useSubtitleStore()
      store.setTargetLanguage('Chinese')
      expect(store.targetLanguage).toBe('Chinese')
    })

    it('sets to Japanese', () => {
      const store = useSubtitleStore()
      store.setTargetLanguage('Japanese')
      expect(store.targetLanguage).toBe('Japanese')
    })
  })

  describe('position management', () => {
    it('setPosition stores coordinates', () => {
      const store = useSubtitleStore()
      store.setPosition(100, 50)
      expect(store.posX).toBe(100)
      expect(store.posY).toBe(50)
    })

    it('resetPosition clears coordinates', () => {
      const store = useSubtitleStore()
      store.setPosition(100, 50)
      store.resetPosition()
      expect(store.posX).toBeNull()
      expect(store.posY).toBeNull()
    })

    it('setPosition handles zero coordinates', () => {
      const store = useSubtitleStore()
      store.setPosition(0, 0)
      expect(store.posX).toBe(0)
      expect(store.posY).toBe(0)
    })
  })

  describe('persistence (localStorage)', () => {
    it('persists config to localStorage on change', async () => {
      const store = useSubtitleStore()
      store.setDisplayMode('original')
      store.setFontSize('small')
      store.setTargetLanguage('Chinese')

      // Watch fires asynchronously — wait for next tick
      await nextTick()

      const saved = JSON.parse(localStorage.getItem('animetta_subtitle_config')!)
      expect(saved.displayMode).toBe('original')
      expect(saved.fontSize).toBe('small')
      expect(saved.targetLanguage).toBe('Chinese')
    })

    it('persists position changes', async () => {
      const store = useSubtitleStore()
      store.setPosition(320, 240)

      await nextTick()

      const saved = JSON.parse(localStorage.getItem('animetta_subtitle_config')!)
      expect(saved.posX).toBe(320)
      expect(saved.posY).toBe(240)
    })
  })
})
