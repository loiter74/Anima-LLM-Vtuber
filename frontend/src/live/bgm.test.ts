import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createLiveBgmController } from './bgm'

describe('standalone live BGM', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = `
      <audio id="bgmAudio"></audio>
      <span id="audioStatus" data-bgm-state="idle"></span>
    `
    const audio = document.getElementById('bgmAudio') as HTMLAudioElement
    vi.spyOn(audio, 'play').mockResolvedValue()
    vi.spyOn(audio, 'pause').mockImplementation(() => undefined)
    vi.spyOn(audio, 'load').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads the configured track and ducks under spoken audio', async () => {
    const audio = document.getElementById('bgmAudio') as HTMLAudioElement
    const controller = createLiveBgmController(
      document,
      new URLSearchParams('bgm=%2Faudio%2Fbgm%2Flicensed.mp3&bgmVolume=0.2'),
    )
    await Promise.resolve()

    expect(audio.getAttribute('src')).toBe('/audio/bgm/licensed.mp3')
    expect(audio.loop).toBe(true)
    expect(audio.volume).toBe(0.2)

    controller.duck()
    vi.advanceTimersByTime(175)
    expect(audio.volume).toBeCloseTo(0.035, 3)
    controller.release()
    vi.advanceTimersByTime(325)
    expect(audio.volume).toBeCloseTo(0.2, 3)
    controller.dispose()
  })

  it('stays silent when bgm=off', () => {
    const audio = document.getElementById('bgmAudio') as HTMLAudioElement
    const controller = createLiveBgmController(document, new URLSearchParams('bgm=off'))

    expect(audio.play).not.toHaveBeenCalled()
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.bgmState', 'off')
    controller.dispose()
  })
})
