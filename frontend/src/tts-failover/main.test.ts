import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const overlayStyles = readFileSync(resolve(process.cwd(), 'src/tts-failover/styles.css'), 'utf8')

describe('TTS failover live notification', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.resetModules()
    document.body.innerHTML = `
      <main class="live-shell">
        <aside class="status-rail" aria-label="直播状态"></aside>
        <section class="danmaku-panel" aria-label="实时弹幕"></section>
      </main>
    `
    window.history.replaceState(
      {},
      '',
      '/live.html?review=1&scene=empty&ttsFailover=1&audio=http%3A%2F%2F127.0.0.1%3A8768%2Fartifacts%2Fa.wav&backend=fallback&firstAudio=0.420&rtf=0.210&sampleRate=24000&provider=qwen3-tts-gguf-host&mouthTimeline=%5B0.1%2C0.5%5D',
    )
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('mounts a compact takeover notification without replacing the live surface', async () => {
    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
    )

    const notification = document.querySelector<HTMLElement>('[data-tts-failover-review]')
    const audio = document.querySelector<HTMLAudioElement>('#reviewAudio')!

    expect(document.querySelector('.live-shell')).not.toBeNull()
    expect(document.querySelector('[aria-label="直播状态"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="实时弹幕"]')).not.toBeNull()
    expect(notification?.getAttribute('aria-label')).toBe('TTS 降级接管通知')
    expect(notification?.textContent).toContain('云端语音暂不可用')
    expect(notification?.textContent).toContain('本地语音已接管')
    expect(notification?.textContent).toContain('fallback')
    expect(notification?.textContent).toContain('首包 0.420s')
    expect(notification?.textContent).toContain('RTF 0.210')
    expect(notification?.textContent).not.toContain('晚上好，欢迎来到直播间')
    expect(audio.src).toBe('http://127.0.0.1:8768/artifacts/a.wav')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledOnce()
    expect(handle?.element).toBe(notification)
    expect(handle?.audio).toBe(audio)

    audio.dispatchEvent(new Event('ended'))
    expect(audio.dataset.complete).toBe('true')
  })

  it('does not mount or play audio without the explicit review flag', async () => {
    const { mountTtsFailoverReviewNotification } = await import('./main')
    mountTtsFailoverReviewNotification(document, new URLSearchParams('review=1&scene=empty'))

    expect(document.querySelector('[data-tts-failover-review]')).toBeNull()
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('can defer playback until the Live2D stage is ready', async () => {
    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
      { autoplay: false },
    )

    expect(handle).not.toBeNull()
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('collapses once after 1.4 seconds and cleanup cancels detached updates', async () => {
    vi.useFakeTimers()
    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
      { autoplay: false },
    )!
    const notification = handle.element

    expect(notification.dataset.state).toBe('expanded')
    expect(notification.textContent).toContain('云端语音暂不可用')
    expect(notification.textContent).toContain('本地语音已接管')

    await vi.advanceTimersByTimeAsync(1_399)
    expect(notification.dataset.state).toBe('expanded')
    await vi.advanceTimersByTimeAsync(1)
    expect(notification.dataset.state).toBe('collapsed')
    expect(notification.querySelector('.tts-failover-collapsed-label')?.textContent).toBe(
      '本地语音接管',
    )

    notification.dataset.state = 'expanded'
    handle.dispose()
    handle.dispose()
    notification.remove()
    await vi.runAllTimersAsync()
    expect(notification.dataset.state).toBe('expanded')
  })

  it('renders the collapsed visual immediately for reduced motion while announcing full copy', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: true,
        media: '(prefers-reduced-motion: reduce)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    )
    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
      { autoplay: false },
    )!
    const notification = handle.element

    expect(notification.dataset.state).toBe('collapsed')
    expect(notification.getAttribute('aria-live')).toBe('polite')
    expect(notification.textContent).toContain('云端语音暂不可用')
    expect(notification.textContent).toContain('本地语音已接管')
  })

  it('publishes placement variables from the measured top-bar gap', async () => {
    const statusRail = document.querySelector<HTMLElement>('.status-rail')!
    const danmakuPanel = document.querySelector<HTMLElement>('.danmaku-panel')!
    vi.spyOn(statusRail, 'getBoundingClientRect').mockReturnValue({
      x: 28,
      y: 28,
      width: 220,
      height: 80,
      top: 28,
      right: 248,
      bottom: 108,
      left: 28,
      toJSON: () => ({}),
    })
    vi.spyOn(danmakuPanel, 'getBoundingClientRect').mockReturnValue({
      x: 632,
      y: 28,
      width: 420,
      height: 320,
      top: 28,
      right: 1052,
      bottom: 348,
      left: 632,
      toJSON: () => ({}),
    })

    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
      { autoplay: false },
    )!
    const notification = handle.element

    expect(notification.style.getPropertyValue('--tts-failover-island-left')).toBe('440px')
    expect(notification.style.getPropertyValue('--tts-failover-island-max-width')).toBe('360px')
  })

  it('owns ResizeObserver and media listeners through an idempotent handle', async () => {
    const disconnect = vi.fn()
    const observe = vi.fn()
    class ResizeObserverMock {
      observe = observe
      disconnect = disconnect
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
    const { mountTtsFailoverReviewNotification } = await import('./main')
    const handle = mountTtsFailoverReviewNotification(
      document,
      new URLSearchParams(window.location.search),
      { autoplay: false },
    )!

    expect(observe).toHaveBeenCalledTimes(2)
    handle.dispose()
    handle.dispose()
    expect(disconnect).toHaveBeenCalledOnce()

    handle.audio.dataset.complete = 'false'
    handle.audio.dispatchEvent(new Event('ended'))
    expect(handle.audio.dataset.complete).toBe('false')
  })

  it('uses the translucent top-bar island visual contract', () => {
    expect(overlayStyles).toMatch(/\.tts-failover-notification\s*{[\s\S]*top:\s*28px/)
    expect(overlayStyles).toMatch(
      /\.tts-failover-notification\s*{[\s\S]*left:\s*var\(--tts-failover-island-left,\s*50%\)/,
    )
    expect(overlayStyles).toMatch(
      /\.tts-failover-notification\s*{[\s\S]*transform:\s*translateX\(-50%\)/,
    )
    expect(overlayStyles).toMatch(
      /\.tts-failover-notification\s*{[\s\S]*background:\s*color-mix\(in srgb,\s*var\(--c-panel\)\s*52%,\s*transparent\)/,
    )
    expect(overlayStyles).toMatch(/\.tts-failover-copy\s*{[\s\S]*opacity:\s*1/)
    expect(overlayStyles).toMatch(/backdrop-filter:\s*blur\(20px\)/)
    expect(overlayStyles).toMatch(/transition:[\s\S]*200ms/)
    expect(overlayStyles).toMatch(
      /\.tts-failover-notification\[data-state='expanded'\]\s*{[\s\S]*width:\s*min\(280px/,
    )
    expect(overlayStyles).toMatch(
      /\.tts-failover-notification\[data-state='collapsed'\]\s*{[\s\S]*width:\s*min\(180px/,
    )
    expect(overlayStyles).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*{[\s\S]*animation:\s*none[\s\S]*transition:\s*none/,
    )
  })
})
