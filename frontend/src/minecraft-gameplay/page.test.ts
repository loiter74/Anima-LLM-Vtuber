import { describe, expect, it } from 'vitest'

import { mountMinecraftGameplayShell } from './page'

describe('minecraft gameplay preview shell', () => {
  it('renders only the broadcast surfaces required by the approved composition', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('preview=1'))

    expect(handle.element.dataset.mode).toBe('preview')
    expect(handle.element.style.getPropertyValue('--broadcast-width')).toBe('1920px')
    expect(handle.element.style.getPropertyValue('--screen-width')).toBe('1488px')
    expect(document.querySelector('[aria-label="Minecraft 游戏画面"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="实时弹幕"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="直播字幕"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="Hiyori 主播"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="附身状态"]')?.textContent).toContain('等待 LUN077')
    expect(document.body.textContent).not.toContain('BotDashboard')
    expect(document.body.textContent).not.toContain('表情调试')

    handle.dispose()
    expect(document.querySelector('.minecraft-gameplay')).toBeNull()
  })

  it('turns the game aperture into a transparent OBS hole in overlay mode', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('overlay=1'))

    expect(handle.element.dataset.mode).toBe('overlay')
    expect(handle.element.querySelector('.game-aperture')?.getAttribute('data-transparent')).toBe(
      'true',
    )

    handle.dispose()
  })

  it('disposes idempotently', () => {
    const handle = mountMinecraftGameplayShell(document, new URLSearchParams('preview=1'))

    handle.dispose()
    expect(() => handle.dispose()).not.toThrow()
  })

  it('renders confirmed attachment and bounded review audio parameters', () => {
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        overlay: '1',
        review: '1',
        bindingState: 'following',
        confirmed: 'true',
        target: 'AnimettaBot',
        attempt: '2',
        reason: 'viewer_joined',
        audio: 'http://127.0.0.1:49152/artifacts/review.wav',
        mouthTimeline: '[0,0.3,0.8,0.1]',
        subtitle: '铁装流程开始，本小姐要认真起来了。',
      }),
    )

    const status = document.querySelector<HTMLElement>('[aria-label="附身状态"]')
    expect(status?.dataset.confirmed).toBe('true')
    expect(status?.dataset.bindingState).toBe('following')
    expect(status?.textContent).toContain('已附身 LUN077 → AnimettaBot')
    expect(document.querySelector('[aria-label="直播字幕"]')?.textContent).toContain('铁装流程开始')
    const runtime = document.querySelector<HTMLElement>('.minecraft-review-runtime')
    expect(runtime?.dataset.mouthTimeline).toBe('[0,0.3,0.8,0.1]')
    expect(runtime?.querySelector('audio')?.src).toBe('http://127.0.0.1:49152/artifacts/review.wav')

    handle.dispose()
  })

  it('rejects untrusted review audio origins and invalid mouth samples', () => {
    const handle = mountMinecraftGameplayShell(
      document,
      new URLSearchParams({
        review: '1',
        audio: 'https://example.com/private.wav',
        mouthTimeline: '[0,-1,2]',
      }),
    )

    expect(document.querySelector('.minecraft-review-runtime')).toBeNull()
    handle.dispose()
  })
})
