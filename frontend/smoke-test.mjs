import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const releaseMode = process.env.PLAYWRIGHT_RELEASE_MODE === '1'
const releaseAudioTimeoutMs = Number(process.env.PLAYWRIGHT_RELEASE_AUDIO_TIMEOUT_MS ?? 60000)
if (!Number.isSafeInteger(releaseAudioTimeoutMs) || releaseAudioTimeoutMs <= 0) {
  throw new Error('PLAYWRIGHT_RELEASE_AUDIO_TIMEOUT_MS must be a positive integer')
}
const browser = await chromium.launch({
  headless: true,
  args: releaseMode ? ['--autoplay-policy=no-user-gesture-required'] : [],
})
const context = await browser.newContext()
if (releaseMode) {
  await context.addInitScript(() => {
    window.__releaseAudio = {
      play_calls: 0,
      play_resolved: 0,
      play_rejected: 0,
      ended: 0,
      errors: [],
    }
    const nativeOnEnded = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'onended')
    if (!nativeOnEnded?.get || !nativeOnEnded.set) {
      throw new Error('Unable to instrument HTML media completion')
    }
    Object.defineProperty(HTMLMediaElement.prototype, 'onended', {
      configurable: true,
      enumerable: nativeOnEnded.enumerable,
      get() {
        return nativeOnEnded.get.call(this)
      },
      set(handler) {
        const wrapped =
          typeof handler === 'function'
            ? function (event) {
                window.__releaseAudio.ended += 1
                return handler.call(this, event)
              }
            : handler
        nativeOnEnded.set.call(this, wrapped)
      },
    })
    const originalPlay = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function (...args) {
      const state = window.__releaseAudio
      state.play_calls += 1
      this.addEventListener(
        'error',
        () => {
          state.errors.push('media-error')
        },
        { once: true },
      )
      try {
        const playback = originalPlay.apply(this, args)
        return Promise.resolve(playback).then(
          (value) => {
            state.play_resolved += 1
            return value
          },
          (error) => {
            state.play_rejected += 1
            state.errors.push(String(error))
            throw error
          },
        )
      } catch (error) {
        state.play_rejected += 1
        state.errors.push(String(error))
        throw error
      }
    }
  })
}
const page = await context.newPage()
const evidenceDir = process.env.PLAYWRIGHT_EVIDENCE_DIR
  ? path.resolve(process.env.PLAYWRIGHT_EVIDENCE_DIR)
  : path.resolve('..')
await mkdir(evidenceDir, { recursive: true })
const screenshotPath = process.env.PLAYWRIGHT_EVIDENCE_DIR
  ? path.join(evidenceDir, 'homepage.png')
  : path.join(evidenceDir, 'smoke-test-homepage.png')
const evidencePath = process.env.PLAYWRIGHT_EVIDENCE_DIR
  ? path.join(evidenceDir, 'evidence.json')
  : path.join(evidenceDir, 'smoke-test-evidence.json')

const consoleErrors = []
const pageErrors = []
const requestFailures = []
const httpErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('requestfailed', (request) => {
  requestFailures.push({ url: request.url(), error: request.failure()?.errorText ?? 'unknown' })
})
page.on('response', (response) => {
  if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() })
})

console.log('Navigating to http://localhost:80...')
await page.goto('http://localhost:80', { waitUntil: 'networkidle', timeout: 30000 })
await page.screenshot({ path: screenshotPath, fullPage: true })

const title = await page.title()
const hasCanvas = (await page.$('canvas')) !== null
const bodyText = (await page.textContent('body')) ?? ''
const buttons = await page.$$('button')
const inputs = await page.$$('input, textarea')
const coreUi = {
  passed:
    Boolean(title.trim()) &&
    hasCanvas &&
    bodyText.length >= 100 &&
    buttons.length > 0 &&
    inputs.length > 0,
  title,
  has_canvas: hasCanvas,
  body_length: bodyText.length,
  button_count: buttons.length,
  input_count: inputs.length,
}

const releaseAcceptance = {
  required: releaseMode,
  passed: !releaseMode,
  provider_rows_exact: false,
  chinese_turn_complete: false,
  marker_leaks: [],
  audio: {
    play_calls: 0,
    play_resolved: 0,
    play_rejected: 0,
    ended: 0,
    errors: [],
  },
}

if (releaseMode) {
  const settingsButton = page.getByRole('button', { name: /设置/ }).last()
  await settingsButton.click()
  const ttsRow = page.locator('[data-service="tts"]')
  const llmRow = page.locator('[data-service="llm"]')
  await ttsRow.waitFor({ state: 'visible', timeout: 15000 })
  await llmRow.waitFor({ state: 'visible', timeout: 15000 })
  const ttsText = (await ttsRow.innerText()).toLowerCase()
  const llmText = (await llmRow.innerText()).toLowerCase()
  releaseAcceptance.provider_rows_exact =
    ['ready', '配置', '实际', 'qwen3', 'qwen/qwen3-tts-12hz-0.6b-base', 'alice'].every((value) =>
      ttsText.includes(value),
    ) && ['ready', '配置', '实际', 'deepseek'].every((value) => llmText.includes(value))
  await page.screenshot({ path: path.join(evidenceDir, 'provider-rows.png'), fullPage: true })

  await page.getByRole('button', { name: /聊天/ }).last().click()
  const prompt = '请用一句纯中文确认 Alice 语音播放正常。'
  const textarea = page.locator('[data-testid="chat-input-bar"] textarea')
  await textarea.fill(prompt)
  await textarea.press('Enter')
  await page.getByText(prompt, { exact: true }).waitFor({ timeout: 10000 })
  await page.waitForFunction(
    (value) => {
      const list = document.querySelector('[data-testid="message-list"]')
      return (
        Boolean(list?.textContent?.includes(value)) &&
        (list?.querySelectorAll(':scope > div.flex').length ?? 0) >= 2
      )
    },
    prompt,
    { timeout: 60000 },
  )
  await page.waitForFunction(
    () =>
      window.__releaseAudio?.play_calls >= 2 &&
      window.__releaseAudio?.play_rejected === 0 &&
      window.__releaseAudio?.ended >= 1,
    undefined,
    { timeout: releaseAudioTimeoutMs },
  )
  const messageText = await page.locator('[data-testid="message-list"]').innerText()
  const assistantText = await page
    .locator('[data-testid="message-list"] > div.flex')
    .last()
    .innerText()
  releaseAcceptance.marker_leaks = [
    '<|assistant|>',
    '<|system|>',
    'the user just said',
    '[affinity:',
    'normal_response',
    'final_response',
  ].filter((marker) => assistantText.toLowerCase().includes(marker))
  releaseAcceptance.audio = await page.evaluate(() => ({ ...window.__releaseAudio }))
  releaseAcceptance.chinese_turn_complete =
    messageText.includes(prompt) &&
    /[\u4e00-\u9fff]/.test(assistantText) &&
    releaseAcceptance.marker_leaks.length === 0
  releaseAcceptance.passed =
    releaseAcceptance.provider_rows_exact &&
    releaseAcceptance.chinese_turn_complete &&
    releaseAcceptance.audio.play_calls === 2 &&
    releaseAcceptance.audio.play_resolved === 2 &&
    releaseAcceptance.audio.play_rejected === 0 &&
    releaseAcceptance.audio.ended >= 1 &&
    releaseAcceptance.audio.errors.length === 0
  await page.screenshot({ path: path.join(evidenceDir, 'chinese-alice-turn.png'), fullPage: true })
}

const failures =
  consoleErrors.length + pageErrors.length + requestFailures.length + httpErrors.length
const status = failures === 0 && coreUi.passed && releaseAcceptance.passed ? 'passed' : 'failed'
const evidence = {
  schema_version: 1,
  status,
  captured_at: new Date().toISOString(),
  context: 'fresh',
  page: 'fresh',
  url: page.url(),
  screenshot: screenshotPath,
  core_ui: coreUi,
  release_acceptance: releaseAcceptance,
  console_errors: consoleErrors,
  page_errors: pageErrors,
  request_failures: requestFailures,
  http_errors: httpErrors,
}
await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')

await context.close()
await browser.close()

console.log('\n=== SMOKE TEST RESULT ===')
if (status === 'passed') {
  console.log('PASS - Fresh browser evidence is complete')
} else {
  console.error('FAIL - Browser evidence is incomplete')
  process.exitCode = 1
}
console.log('Status:', status.toUpperCase())
